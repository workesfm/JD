"""Standalone HTTP adapter. Supply a proper HTTPS public origin before deployment."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from core import Ledger, CheckedRPC, Problem, PRICE_RAW, MAX_BODY, clean


class App:
    def __init__(self, ledger, rpc, origin, origin_getter=None):
        self.ledger, self.rpc = ledger, rpc
        self.origin = self.validate_origin(origin)
        self.origin_getter = origin_getter
        self.lock = threading.Lock()
        self.refresh_locks, self.last_refresh = {}, {}

    @staticmethod
    def validate_origin(origin):
        if not isinstance(origin, str):
            raise ValueError('a trusted HTTPS public origin is required')
        origin = origin.rstrip('/')
        parsed = urlsplit(origin)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.path or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('a trusted HTTPS public origin is required')
        return origin

    def refresh(self, account_id, address):
        with self.lock:
            lock = self.refresh_locks.setdefault(account_id, threading.Lock())
        with lock:
            if time.monotonic() - self.last_refresh.get(account_id, -100) < 5:
                return
            payments = self.rpc.payments(address)
            self.ledger.refresh(account_id, payments)
            self.last_refresh[account_id] = time.monotonic()

    def payment_offer(self, quote):
        try:
            origin = self.validate_origin(self.origin_getter() if self.origin_getter else self.origin)
        except Exception:
            raise Problem(503, 'public_origin_unavailable')
        status_url = origin + '/api/x402/status/' + quote['id']
        complete_url = origin + '/api/x402/complete/' + quote['id']
        expires = datetime.fromtimestamp(quote['expires'], timezone.utc).isoformat()
        body = {'error':'payment_required','network':'nano:mainnet','price_raw':str(PRICE_RAW),
                'requestHash':quote['request_hash'],
                'payment':{'version':1,'paymentId':quote['id'],'requestHash':quote['request_hash'],
                    'statusUrl':status_url,'completeUrl':complete_url,'expiresAt':expires,
                    'accepted':[{'scheme':'nano','protocolScheme':'nano','network':'nano-mainnet',
                        'payTo':quote['address'],'amount':str(PRICE_RAW),'amountFormatted':'0.01 XNO',
                        'paymentId':quote['id'],'expiresAt':expires,
                        'statusUrl':status_url,'completeUrl':complete_url}]}}
        headers = {'x-payment-address':quote['address'],'x-payment-amount':'0.01',
                   'x-payment-id':quote['id'],'x-payment-network':'nano:mainnet',
                   'x-payment-status-url':status_url,'x-payment-complete-url':complete_url}
        return 402, body, headers

    def route(self, method, path, headers, body=b''):
        if method == 'GET' and path in ('/', '/health'):
            return 200, {'service':'ClearTable CSV API','mode':'pilot','network':'nano:mainnet',
                         'price_xno':'0.01','max_csv_bytes':100000,'max_data_rows':1000,
                         'endpoint':'/api/x402/v1/clean','wallet_rpc_actions':'read-only'}, {}
        if method == 'POST' and path in ('/v1/clean','/api/x402/v1/clean'):
            if headers.get('x-x402','nano') != 'nano': raise Problem(400,'unsupported_payment_scheme')
            clean(body)
            auth = headers.get('Authorization','')
            if auth:
                if not auth.startswith('Bearer '): raise Problem(401,'invalid_credit_token')
                token = auth[7:]
                account_id = self.ledger.authenticate(token)
                balance = self.ledger.balance(account_id)
                if balance['remaining_calls'] < 1:
                    self.refresh(account_id,balance['address'])
                result = self.ledger.credit_call(token,headers.get('Idempotency-Key',''),body)
                result['credit'] = self.ledger.balance(account_id)
                return 200,result,{}
            # Make sure the configured public RPC answers before issuing a payable quote.
            self.ledger.reserve_quote_check()
            with self.ledger.connect() as db:
                row = db.execute('SELECT address FROM address_pool ORDER BY idx LIMIT 1').fetchone()
            if row is None: raise Problem(503,'receiving_capacity_unavailable')
            self.rpc.payments(row['address'])
            return self.payment_offer(self.ledger.quote(body))
        match = re.fullmatch('/api/x402/status/(pay_[0-9a-f]{48})',path)
        if method == 'GET' and match:
            q = self.ledger.quote_info(match[1])
            if q['completed'] is not None:
                return 200,{'status':'completed','readyToComplete':False},{}
            balance = self.ledger.balance(q['account_id'])
            if balance['remaining_calls'] < 1:
                self.refresh(q['account_id'],q['address'])
                balance = self.ledger.balance(q['account_id'])
            paid = balance['remaining_calls'] >= 1
            if not paid and time.time() > q['expires']:
                return 410,{'status':'expired','readyToComplete':False},{}
            return 200,{'status':'paid' if paid else 'pending','readyToComplete':paid,
                        'network':'nano:mainnet'},{}
        match = re.fullmatch('/api/x402/complete/(pay_[0-9a-f]{48})',path)
        if method == 'POST' and match:
            quote_id = match[1]
            if headers.get('x-x402-payment-id','') != quote_id:
                raise Problem(400,'payment_id_header_required')
            q = self.ledger.quote_info(quote_id)
            result = clean(body)
            if result['source_sha256'] != q['body_hash']: raise Problem(409,'request_body_mismatch')
            if q['completed'] is not None: raise Problem(409,'payment_quote_already_completed')
            if self.ledger.balance(q['account_id'])['remaining_calls'] < 1:
                self.refresh(q['account_id'],q['address'])
            result,token = self.ledger.complete(quote_id,body,[])
            result['credit'] = self.ledger.balance(q['account_id'])
            return 200,result,{'x-cleartable-credit-token':token}
        if method == 'GET' and path == '/v1/credit':
            auth = headers.get('Authorization','')
            if not auth.startswith('Bearer '): raise Problem(401,'credit_token_required')
            account_id = self.ledger.authenticate(auth[7:])
            balance = self.ledger.balance(account_id)
            self.refresh(account_id,balance['address'])
            return 200,self.ledger.balance(account_id),{}
        match = re.fullmatch('/api/x402/receipt/(pay_[0-9a-f]{48})',path)
        if method == 'POST' and match:
            if headers.get('x-x402-payment-id','') != match[1]:
                raise Problem(400,'payment_id_header_required')
            result,token=self.ledger.receipt(match[1],body)
            return 200,result,{'x-cleartable-credit-token':token}
        raise Problem(404,'not_found')


def handler_for(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'ClearTable'
        sys_version = ''
        protocol_version = 'HTTP/1.1'

        def log_message(self,*args):
            pass  # URLs and headers can contain payment or credit capabilities.

        def handle_request(self):
            self.connection.settimeout(15)
            self.close_connection = True
            try:
                if self.headers.get('Transfer-Encoding'):
                    raise Problem(400,'unsupported_transfer_encoding')
                body = b''
                if self.command == 'POST':
                    lengths = self.headers.get_all('Content-Length',[])
                    if len(lengths) != 1: raise Problem(411,'content_length_required')
                    try: length = int(lengths[0])
                    except ValueError: raise Problem(400,'invalid_content_length')
                    if length < 0 or length > MAX_BODY: raise Problem(413,'request_too_large')
                    if self.headers.get_content_type() != 'application/json':
                        raise Problem(415,'application_json_required')
                    body = self.rfile.read(length)
                    if len(body) != length: raise Problem(400,'incomplete_request')
                if '?' in self.path: raise Problem(400,'query_parameters_not_supported')
                status,result,headers = app.route(self.command,self.path,self.headers,body)
            except Problem as error:
                status,result,headers = error.status,{'error':error.code},{}
            except (TimeoutError,ConnectionError):
                return
            except Exception:
                status,result,headers = 503,{'error':'service_unavailable'},{}
            encoded = json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(encoded)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Connection','close')
            for k,v in headers.items(): self.send_header(k,v)
            self.end_headers()
            self.wfile.write(encoded)

        do_GET = handle_request
        do_POST = handle_request
    return Handler


def main():
    folder = Path(os.environ.get('CLEARTABLE_NANO_PRIVATE_DIR',
                                '/root/.local/share/codex-revenue-accounts/nano-api'))
    config = json.loads((folder/'config.json').read_text())
    if str(folder.resolve()).startswith('/workspace/'):
        raise ValueError('private runtime state must stay outside the workspace')
    if folder.stat().st_mode & 0o077 or (folder/'config.json').stat().st_mode & 0o077:
        raise ValueError('private runtime state permissions are too broad')
    pool = json.loads((folder/'address-pool.json').read_text())
    ledger = Ledger(folder/'ledger.sqlite3',pool['addresses'],bytes.fromhex(config['credit_token_secret']))
    os.chmod(folder/'ledger.sqlite3',0o600)
    app = App(ledger,CheckedRPC(config['rpc_url'],config['verification_rpc_url']),config['public_origin'],
              origin_getter=lambda: json.loads((folder/'config.json').read_text())['public_origin'])
    server = ThreadingHTTPServer(('127.0.0.1',int(config.get('port',8789))),handler_for(app))
    print(json.dumps({'event':'listening','host':'127.0.0.1','port':server.server_port,
                      'network':'nano:mainnet','financial_rpc_actions':False}),flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
