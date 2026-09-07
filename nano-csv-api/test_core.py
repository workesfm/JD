import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import unittest

from core import Ledger, NanoRPC, Payment, PRICE_RAW, Problem, address_from_key, address_key, clean, state_hash

BODY = json.dumps({'csv':'name,email\n Alice ,a@example.test\nAlice,a@example.test\nBob,\nCara,c@example.test\n',
                   'required_columns':['name','email']},separators=(',',':')).encode()
POOL = [address_from_key(bytes([n])*32) for n in range(1,9)]


class Cases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'ledger.sqlite3'
        self.ledger = Ledger(self.path,POOL,b'test-secret-no-funds-'+bytes(32))

    def tearDown(self):
        self.temp.cleanup()

    def payment(self,q,amount=PRICE_RAW,hash='A'*64):
        return Payment(hash,q['address'],amount,POOL[-1])

    def error(self,code,fn,*args,**kwargs):
        with self.assertRaises(Problem) as ctx:fn(*args,**kwargs)
        self.assertEqual(ctx.exception.code,code)

    def test_cleanup_and_row_conservation(self):
        r=clean(BODY)
        self.assertEqual(r['cleaned_csv'],'name,email\nAlice,a@example.test\nCara,c@example.test\n')
        self.assertEqual(r['counts'],{'input_rows':4,'output_rows':2,'duplicate_rows':1,'exception_rows':1})

    def test_independent_sdk_hash_vector(self):
        vector=json.loads((Path(__file__).parent/'testdata/state-hash.json').read_text())
        self.assertEqual(state_hash(vector['block']),vector['expected_hash'])

    def test_json_escaped_unicode_within_csv_byte_limit(self):
        text='value\n'+'\U0001f642'*20000+'\n'
        body=json.dumps({'csv':text}).encode()
        self.assertGreater(len(body),210000)
        self.assertLess(len(text.encode()),100000)
        self.assertEqual(clean(body)['cleaned_csv'],text)

    def test_invalid_input_never_allocates_quote(self):
        for body in [b'{',b'{"csv":"x,x\\na,b"}',b'{"csv":"\\ud800"}',b'{"csv":"x\\n1","trim":"false"}']:
            with self.assertRaises(Problem):self.ledger.quote(body)
        with self.ledger.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM quotes').fetchone()[0],0)

    def test_body_binding_replay_and_restart(self):
        q=self.ledger.quote(BODY)
        self.error('request_body_mismatch',self.ledger.complete,q['id'],BODY+b' ',[self.payment(q)])
        r,token=self.ledger.complete(q['id'],BODY,[self.payment(q)])
        self.assertEqual(r['counts']['output_rows'],2)
        restarted=Ledger(self.path,POOL,b'test-secret-no-funds-'+bytes(32))
        self.error('payment_quote_already_completed',restarted.complete,q['id'],BODY,[self.payment(q)])
        self.assertEqual(restarted.balance(restarted.authenticate(token))['remaining_calls'],0)
        receipt,recovered_token=restarted.receipt(q['id'],BODY)
        self.assertEqual(recovered_token,token)
        self.assertEqual(receipt['cleaned_csv'],r['cleaned_csv'])
        self.assertEqual(receipt['billing']['charged_raw'],'0')
        self.error('request_body_mismatch',restarted.receipt,q['id'],BODY+b' ')

    def test_underpayment_and_wrong_destination(self):
        q=self.ledger.quote(BODY)
        self.error('payment_required',self.ledger.complete,q['id'],BODY,[self.payment(q,PRICE_RAW-1)])
        self.error('unverified_payment',self.ledger.complete,q['id'],BODY,[Payment('B'*64,POOL[-1],PRICE_RAW,POOL[-1])])
        self.assertIsNone(self.ledger.quote_info(q['id'])['completed'])

    def test_expired_unfunded_quote_and_late_deposit(self):
        q=self.ledger.quote(BODY,now=1000)
        self.error('payment_quote_expired',self.ledger.complete,q['id'],BODY,[],now=90000)
        result,_=self.ledger.complete(q['id'],BODY,[self.payment(q)],now=90000)
        self.assertEqual(result['counts']['output_rows'],2)

    def test_prepaid_credit_imported_once(self):
        q=self.ledger.quote(BODY)
        _,token=self.ledger.complete(q['id'],BODY,[self.payment(q)])
        account=self.ledger.authenticate(token)
        topup=self.payment(q,25*10**30,'B'*64)
        self.ledger.refresh(account,[self.payment(q),topup])
        self.ledger.refresh(account,[topup])
        self.assertEqual(self.ledger.balance(account)['remaining_calls'],2500)
        self.ledger.credit_call(token,'credit_request_001',BODY)
        replay=self.ledger.credit_call(token,'credit_request_001',BODY)
        self.assertTrue(replay['billing']['idempotent_replay'])
        self.assertEqual(self.ledger.balance(account)['remaining_calls'],2499)
        self.error('idempotency_body_mismatch',self.ledger.credit_call,token,'credit_request_001',BODY+b' ')

    def test_concurrent_completion_charges_once(self):
        q=self.ledger.quote(BODY)
        def call(_):
            try:self.ledger.complete(q['id'],BODY,[self.payment(q)]);return 'ok'
            except Problem as e:return e.code
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(call,range(8)))
        self.assertEqual(results.count('ok'),1)
        self.assertEqual(results.count('payment_quote_already_completed'),7)

    def test_concurrent_credit_requests_cannot_overspend(self):
        q=self.ledger.quote(BODY)
        _,token=self.ledger.complete(q['id'],BODY,[self.payment(q,2*PRICE_RAW)])
        def call(i):
            try:self.ledger.credit_call(token,f'credit_request_{i:04d}',BODY);return 'ok'
            except Problem as e:return e.code
        with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(call,range(8)))
        self.assertEqual(results.count('ok'),1)
        self.assertEqual(results.count('credit_exhausted'),7)
        self.assertEqual(self.ledger.balance(self.ledger.authenticate(token))['used_calls'],2)

    def test_confirmed_block_amount_and_destination(self):
        prev={'type':'state','account':POOL[-1],'representative':POOL[-2],
              'previous':'0'*64,'balance':str(10*PRICE_RAW),'link':'0'*64}
        block={'type':'state','account':POOL[-1],'representative':POOL[-2],
               'previous':state_hash(prev),'balance':str(9*PRICE_RAW),
               'link':address_key(POOL[0]).hex()}
        block_hash=state_hash(block)
        current={'confirmed':'true','amount':str(PRICE_RAW),'contents':block}
        previous={'confirmed':'true','contents':prev}
        paid=NanoRPC.verify_pair(block_hash,current,previous,POOL[0])
        self.assertEqual(paid.amount_raw,PRICE_RAW)
        for changed in [dict(current,confirmed='false'),dict(current,amount=str(2*PRICE_RAW)),dict(current,contents=dict(block,balance='0'))]:
            self.error('unverified_payment',NanoRPC.verify_pair,block_hash,changed,previous,POOL[0])
        self.error('unverified_payment',NanoRPC.verify_pair,block_hash,current,previous,POOL[1])

    def test_financial_rpc_actions_are_unavailable(self):
        rpc=NanoRPC('https://example.test')
        for action in ['send','receive','process','work_generate']:
            with self.assertRaises(ValueError):rpc.rpc(action)


if __name__=='__main__':unittest.main()
