"""CSV cleanup and durable Nano payment accounting. No sending/signing RPCs."""
from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import io
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request

PRICE_RAW = 10**28  # 0.01 XNO; one XNO is 10**30 raw.
MAX_BODY = 1_250_000  # Accommodate JSON escapes while CSV itself stays <=100 KB.
ALPHABET = '13456789abcdefghijkmnopqrstuwxyz'


class Problem(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def address_key(address):
    if not isinstance(address, str) or not address.startswith(('nano_', 'xrb_')):
        raise ValueError('invalid Nano address')
    value = address.split('_', 1)[1]
    if len(value) != 60 or value[0] not in '13':
        raise ValueError('invalid Nano address')
    def decode(text):
        n = 0
        for c in text:
            n = n * 32 + ALPHABET.index(c)
        return n
    key = decode(value[:52]).to_bytes(32, 'big')
    checksum = decode(value[52:]).to_bytes(5, 'big')
    if checksum != hashlib.blake2b(key, digest_size=5).digest()[::-1]:
        raise ValueError('invalid Nano checksum')
    return key


def address_from_key(key):
    def encode(data, length):
        n = int.from_bytes(data, 'big')
        out = ''
        for _ in range(length):
            out = ALPHABET[n & 31] + out
            n >>= 5
        return out
    return 'nano_' + encode(key, 52) + encode(hashlib.blake2b(key, digest_size=5).digest()[::-1], 8)


def state_hash(block):
    if block.get('type') != 'state':
        raise ValueError('state block required')
    material = (bytes(31) + b'\x06' + address_key(block['account'])
                + bytes.fromhex(block['previous']) + address_key(block['representative'])
                + int(block['balance']).to_bytes(16, 'big') + bytes.fromhex(block['link']))
    if len(material) != 176:
        raise ValueError('invalid state block fields')
    return hashlib.blake2b(material, digest_size=32).hexdigest().upper()


def clean(body: bytes):
    if len(body) > MAX_BODY:
        raise Problem(413, 'request_too_large')
    try:
        spec = json.loads(body.decode('utf-8'))
    except (ValueError, UnicodeError):
        raise Problem(400, 'invalid_json_utf8')
    if not isinstance(spec, dict) or set(spec) - {'csv', 'required_columns', 'trim', 'deduplicate'}:
        raise Problem(400, 'unsupported_request_fields')
    text = spec.get('csv')
    required = spec.get('required_columns', [])
    trim, dedup = spec.get('trim', True), spec.get('deduplicate', True)
    try:
        valid_text = isinstance(text, str) and len(text.encode('utf-8')) <= 100_000 and '\0' not in text
    except UnicodeError:
        valid_text = False
    if not valid_text:
        raise Problem(400, 'invalid_csv_or_csv_too_large')
    if not isinstance(required, list) or len(required) > 100 or not all(isinstance(x, str) for x in required):
        raise Problem(400, 'invalid_required_columns')
    if type(trim) is not bool or type(dedup) is not bool:
        raise Problem(400, 'options_must_be_boolean')
    try:
        rows = list(csv.reader(io.StringIO(text.removeprefix('\ufeff'), newline=''), strict=True))
    except csv.Error:
        raise Problem(400, 'malformed_csv')
    if not rows:
        raise Problem(400, 'header_required')
    header = [v.strip() if trim else v for v in rows[0]]
    if not header or len(header) > 100 or any(not x for x in header) or len(set(header)) != len(header):
        raise Problem(400, 'invalid_or_duplicate_header')
    if any(x not in header for x in required):
        raise Problem(400, 'required_column_not_in_header')
    data = [(i + 2, row) for i, row in enumerate(rows[1:]) if row]
    if len(data) > 1000:
        raise Problem(413, 'too_many_rows')
    indices = [header.index(x) for x in required]
    accepted, duplicates, exceptions, seen = [], [], [], set()
    for number, raw in data:
        row = tuple(x.strip() if trim else x for x in raw)
        if len(row) != len(header):
            exceptions.append({'row': number, 'reason': 'column_count'})
        elif any(not row[i].strip() for i in indices):
            exceptions.append({'row': number, 'reason': 'missing_required_value'})
        elif dedup and row in seen:
            duplicates.append(number)
        else:
            seen.add(row)
            accepted.append(row)
    out = io.StringIO(newline='')
    writer = csv.writer(out, lineterminator='\n')
    writer.writerow(header)
    writer.writerows(accepted)
    return {'cleaned_csv': out.getvalue(), 'counts': {'input_rows': len(data),
            'output_rows': len(accepted), 'duplicate_rows': len(duplicates),
            'exception_rows': len(exceptions)}, 'duplicate_row_numbers': duplicates,
            'exceptions': exceptions, 'source_sha256': hashlib.sha256(body).hexdigest()}


@dataclass(frozen=True)
class Payment:
    block_hash: str
    destination: str
    amount_raw: int
    source: str


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class NanoRPC:
    """Operator-configured read-only RPC. Never accepts RPC actions from customers."""
    ACTIONS = {'block_info', 'receivable'}

    def __init__(self, url):
        if not url.startswith('https://'):
            raise ValueError('HTTPS RPC required')
        self.url = url
        self.retry_after = 0

    def rpc(self, action, **params):
        if action not in self.ACTIONS:
            raise ValueError('read-only RPC action required')
        if time.monotonic() < self.retry_after:
            raise Problem(503, 'payment_verification_backoff')
        request = urllib.request.Request(self.url,
            data=json.dumps({'action': action, **params}).encode(),
            headers={'Content-Type': 'application/json', 'User-Agent': 'ClearTable Nano verification/1.0'})
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
                result = json.loads(response.read(1_000_000))
        except urllib.error.HTTPError as error:
            if error.code == 429:
                try: delay = max(60, int(error.headers.get('Retry-After','60')))
                except ValueError: delay = 60
                self.retry_after = time.monotonic() + delay
            raise Problem(503, 'payment_verification_unavailable')
        except Exception:
            raise Problem(503, 'payment_verification_unavailable')
        if not isinstance(result, dict) or result.get('error'):
            if isinstance(result,dict):
                try: delay = max(60,int(result.get('retry_after',60)))
                except (ValueError,TypeError): delay = 60
                self.retry_after = time.monotonic() + delay
            raise Problem(503, 'payment_verification_unavailable')
        return result

    @staticmethod
    def verify_pair(block_hash, current, previous, destination):
        try:
            if not re.fullmatch('[0-9A-Fa-f]{64}', block_hash):
                raise ValueError('hash')
            if current.get('confirmed') not in ('true', True) or previous.get('confirmed') not in ('true', True):
                raise ValueError('unconfirmed')
            block = current['contents']
            prev = previous['contents']
            if isinstance(block, str): block = json.loads(block)
            if isinstance(prev, str): prev = json.loads(prev)
            if state_hash(block) != block_hash.upper() or state_hash(prev) != block['previous'].upper():
                raise ValueError('hash mismatch')
            if address_key(block['account']) != address_key(prev['account']):
                raise ValueError('account mismatch')
            if bytes.fromhex(block['link']) != address_key(destination):
                raise ValueError('destination mismatch')
            amount = int(prev['balance']) - int(block['balance'])
            if amount <= 0 or amount >= 2**128 or str(amount) != str(current['amount']):
                raise ValueError('amount mismatch')
            return Payment(block_hash.upper(), destination, amount, address_from_key(address_key(block['account'])))
        except (KeyError, ValueError, TypeError, OverflowError):
            raise Problem(402, 'unverified_payment')

    def verify(self, block_hash, destination):
        current = self.rpc('block_info', hash=block_hash, json_block='true')
        block = current.get('contents', {})
        if isinstance(block, str):
            try: block = json.loads(block)
            except ValueError: raise Problem(402, 'unverified_payment')
        previous_hash = block.get('previous', '')
        if not re.fullmatch('[0-9A-Fa-f]{64}', previous_hash) or previous_hash == '0' * 64:
            raise Problem(402, 'unverified_payment')
        previous = self.rpc('block_info', hash=previous_hash, json_block='true')
        return self.verify_pair(block_hash, current, previous, destination)

    def payments(self, address):
        result = self.rpc('receivable', account=address, count='100', source='true',
                          include_only_confirmed='true', sorting='true')
        blocks = result.get('blocks', {})
        if blocks in ('', []): return []
        if not isinstance(blocks, dict):
            raise Problem(503, 'payment_verification_unavailable')
        return [self.verify(block_hash, address) for block_hash in blocks]


class CheckedRPC:
    def __init__(self, primary_url, verification_url):
        if primary_url == verification_url:
            raise ValueError('different public RPC endpoints required')
        self.primary, self.verifier = NanoRPC(primary_url), NanoRPC(verification_url)

    def payments(self, address):
        payments = self.primary.payments(address)
        for payment in payments:
            if self.verifier.verify(payment.block_hash,address) != payment:
                raise Problem(503,'payment_verifiers_disagree')
        return payments


class Ledger:
    def __init__(self, path: Path, addresses, token_secret: bytes):
        self.path, self.token_secret = Path(path), token_secret
        if len(token_secret) < 32:
            raise ValueError('credit token secret too short')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS address_pool(idx INTEGER PRIMARY KEY, address TEXT UNIQUE NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts(
                    id TEXT PRIMARY KEY, address_idx INTEGER UNIQUE NOT NULL REFERENCES address_pool(idx),
                    total_raw TEXT NOT NULL DEFAULT '0', spent INTEGER NOT NULL DEFAULT 0,
                    created INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS quotes(
                    id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
                    body_hash TEXT NOT NULL, created INTEGER NOT NULL, expires INTEGER NOT NULL,
                    completed INTEGER);
                CREATE TABLE IF NOT EXISTS payments(
                    hash TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(id),
                    amount_raw TEXT NOT NULL, source TEXT NOT NULL, credited INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS usages(
                    account_id TEXT NOT NULL REFERENCES accounts(id), request_id TEXT NOT NULL,
                    body_hash TEXT NOT NULL, created INTEGER NOT NULL,
                    PRIMARY KEY(account_id,request_id));
                CREATE TABLE IF NOT EXISTS quote_checks(at INTEGER NOT NULL);
            ''')
            for i, address in enumerate(addresses):
                address_key(address)
                prior = db.execute('SELECT address FROM address_pool WHERE idx=?', (i,)).fetchone()
                if prior and prior['address'] != address:
                    raise ValueError('receiving address pool changed')
                db.execute('INSERT OR IGNORE INTO address_pool VALUES(?,?)', (i, address))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=10000')
        try:
            with db:
                yield db
        finally:
            db.close()

    def token(self, account_id):
        return account_id + '.' + hmac.new(self.token_secret, account_id.encode(), hashlib.sha256).hexdigest()

    def authenticate(self, token):
        account_id = token.split('.', 1)[0]
        if not re.fullmatch('[0-9a-f]{32}', account_id) or not hmac.compare_digest(self.token(account_id), token):
            raise Problem(401, 'invalid_credit_token')
        return account_id

    def quote(self, body, account_id=None, now=None):
        clean(body)  # Invalid work must never solicit payment.
        now = int(time.time()) if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if account_id is None:
                if db.execute('SELECT count(*) FROM accounts WHERE created>?', (now - 3600,)).fetchone()[0] >= 20:
                    raise Problem(429, 'quote_rate_limit')
                row = db.execute('SELECT idx FROM address_pool WHERE idx NOT IN (SELECT address_idx FROM accounts) ORDER BY idx LIMIT 1').fetchone()
                if row is None: raise Problem(503, 'receiving_capacity_unavailable')
                account_id = secrets.token_hex(16)
                db.execute('INSERT INTO accounts(id,address_idx,created) VALUES(?,?,?)', (account_id,row['idx'],now))
            account = db.execute('SELECT a.*,p.address FROM accounts a JOIN address_pool p ON p.idx=a.address_idx WHERE a.id=?', (account_id,)).fetchone()
            if account is None: raise Problem(401, 'invalid_credit_token')
            quote_id = 'pay_' + secrets.token_hex(24)
            db.execute('INSERT INTO quotes VALUES(?,?,?,?,?,NULL)',
                       (quote_id,account_id,hashlib.sha256(body).hexdigest(),now,now+86400))
            return {'id':quote_id,'account_id':account_id,'address':account['address'],
                    'created':now,'expires':now+86400,'price_raw':str(PRICE_RAW),
                    'request_hash':hashlib.sha256(body).hexdigest()}

    def reserve_quote_check(self, now=None):
        now=int(time.time()) if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM quote_checks WHERE at<=?',(now-3600,))
            if db.execute('SELECT count(*) FROM quote_checks').fetchone()[0]>=20:
                raise Problem(429,'quote_rate_limit')
            db.execute('INSERT INTO quote_checks VALUES(?)',(now,))

    def quote_info(self, quote_id):
        with self.connect() as db:
            row = db.execute('SELECT q.*,p.address,a.total_raw,a.spent FROM quotes q JOIN accounts a ON a.id=q.account_id JOIN address_pool p ON p.idx=a.address_idx WHERE q.id=?', (quote_id,)).fetchone()
            if row is None: raise Problem(404,'unknown_payment_id')
            return dict(row)

    @staticmethod
    def import_payments(db, account_id, address, payments):
        total = int(db.execute('SELECT total_raw FROM accounts WHERE id=?',(account_id,)).fetchone()[0])
        for payment in payments:
            if (payment.destination != address or payment.amount_raw <= 0
                    or payment.amount_raw >= 2**128
                    or not re.fullmatch('[0-9A-F]{64}', payment.block_hash)):
                raise Problem(402,'unverified_payment')
            existing = db.execute('SELECT account_id,amount_raw FROM payments WHERE hash=?',(payment.block_hash,)).fetchone()
            if existing:
                if existing['account_id'] != account_id or existing['amount_raw'] != str(payment.amount_raw):
                    raise Problem(409,'payment_already_assigned')
                continue
            db.execute('INSERT INTO payments VALUES(?,?,?,?,?)',
                       (payment.block_hash,account_id,str(payment.amount_raw),payment.source,int(time.time())))
            total += payment.amount_raw
        db.execute('UPDATE accounts SET total_raw=? WHERE id=?',(str(total),account_id))

    def refresh(self, account_id, payments):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            account = db.execute('SELECT a.*,p.address FROM accounts a JOIN address_pool p ON p.idx=a.address_idx WHERE a.id=?',(account_id,)).fetchone()
            if account is None: raise Problem(401,'invalid_credit_token')
            self.import_payments(db,account_id,account['address'],payments)

    def balance(self, account_id):
        with self.connect() as db:
            row = db.execute('SELECT a.*,p.address FROM accounts a JOIN address_pool p ON p.idx=a.address_idx WHERE a.id=?',(account_id,)).fetchone()
            if row is None: raise Problem(401,'invalid_credit_token')
            remaining = int(row['total_raw']) - row['spent'] * PRICE_RAW
            return {'account_id':account_id,'address':row['address'],'remaining_raw':str(remaining),
                    'remaining_calls':remaining // PRICE_RAW,'used_calls':row['spent']}

    def complete(self, quote_id, body, payments, now=None):
        result = clean(body)
        now = int(time.time()) if now is None else now
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            q = db.execute('SELECT q.*,p.address FROM quotes q JOIN accounts a ON a.id=q.account_id JOIN address_pool p ON p.idx=a.address_idx WHERE q.id=?',(quote_id,)).fetchone()
            if q is None: raise Problem(404,'unknown_payment_id')
            if q['body_hash'] != result['source_sha256']: raise Problem(409,'request_body_mismatch')
            if q['completed'] is not None: raise Problem(409,'payment_quote_already_completed')
            self.import_payments(db,q['account_id'],q['address'],payments)
            a = db.execute('SELECT * FROM accounts WHERE id=?',(q['account_id'],)).fetchone()
            if int(a['total_raw']) - a['spent'] * PRICE_RAW < PRICE_RAW:
                if now > q['expires']: raise Problem(410,'payment_quote_expired')
                raise Problem(402,'payment_required')
            db.execute('UPDATE accounts SET spent=spent+1 WHERE id=?',(q['account_id'],))
            db.execute('UPDATE quotes SET completed=? WHERE id=?',(now,quote_id))
            db.execute('INSERT INTO usages VALUES(?,?,?,?)',(q['account_id'],quote_id,q['body_hash'],now))
            result['billing']={'charged_raw':str(PRICE_RAW),'payment_id':quote_id}
            account_id = q['account_id']
        return result, self.token(account_id)

    def credit_call(self, token, request_id, body):
        account_id = self.authenticate(token)
        if not re.fullmatch('[A-Za-z0-9_-]{16,100}',request_id):
            raise Problem(400,'idempotency_key_required')
        result = clean(body)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT body_hash FROM usages WHERE account_id=? AND request_id=?',(account_id,request_id)).fetchone()
            if prior:
                if prior['body_hash'] != result['source_sha256']: raise Problem(409,'idempotency_body_mismatch')
                result['billing']={'charged_raw':'0','idempotent_replay':True}
                return result
            a = db.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
            if a is None: raise Problem(401,'invalid_credit_token')
            if int(a['total_raw']) - a['spent'] * PRICE_RAW < PRICE_RAW: raise Problem(402,'credit_exhausted')
            db.execute('UPDATE accounts SET spent=spent+1 WHERE id=?',(account_id,))
            db.execute('INSERT INTO usages VALUES(?,?,?,?)',(account_id,request_id,result['source_sha256'],int(time.time())))
            result['billing']={'charged_raw':str(PRICE_RAW),'idempotent_replay':False}
        return result

    def receipt(self, quote_id, body):
        result=clean(body)
        q=self.quote_info(quote_id)
        if q['body_hash']!=result['source_sha256']:raise Problem(409,'request_body_mismatch')
        if q['completed'] is None:raise Problem(409,'payment_quote_not_completed')
        result['billing']={'charged_raw':'0','previous_result_receipt':True,
                           'original_charge_raw':str(PRICE_RAW),'payment_id':quote_id}
        return result,self.token(q['account_id'])
