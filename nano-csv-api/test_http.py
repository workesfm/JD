"""Exercise the real HTTP adapter with explicitly simulated, valueless payments."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from core import Ledger, Payment, PRICE_RAW, Problem
from server import App,handler_for
from test_core import BODY,POOL


class FakeRPC:
    def __init__(self):self.by_address={};self.fail=False;self.calls=0
    def payments(self,address):
        self.calls+=1
        if self.fail:raise Problem(503,'payment_verification_unavailable')
        return self.by_address.get(address,[])


class HTTPFlow(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.ledger=Ledger(Path(self.temp.name)/'ledger.sqlite3',POOL,b'fixture-secret-'+bytes(32))
        self.rpc=FakeRPC();self.app=App(self.ledger,self.rpc,'https://api.example.test')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_for(self.app))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temp.cleanup()

    def request(self,path,body=None,headers=None):
        hs={'Content-Type':'application/json','x-x402':'nano',**(headers or {})}
        try:r=urlopen(Request(self.base+path,data=body,headers=hs),timeout=3)
        except HTTPError as e:r=e
        with r:return r.status,dict(r.headers),json.loads(r.read())

    def test_quote_poll_complete_and_credit(self):
        status,headers,offer=self.request('/api/x402/v1/clean',BODY)
        self.assertEqual(status,402)
        self.assertEqual(headers['x-payment-amount'],'0.01')
        self.assertEqual(headers['x-payment-network'],'nano:mainnet')
        self.assertEqual(offer['payment']['accepted'][0]['amount'],str(PRICE_RAW))
        self.assertEqual(offer['payment']['accepted'][0]['amountFormatted'],'0.01 XNO')
        self.assertEqual(offer['payment']['accepted'][0]['payTo'],headers['x-payment-address'])
        qid=headers['x-payment-id'];address=headers['x-payment-address']
        self.assertEqual(self.request('/api/x402/status/'+qid)[2]['status'],'pending')
        self.rpc.by_address[address]=[Payment('A'*64,address,PRICE_RAW,POOL[-1])]
        q=self.ledger.quote_info(qid);self.app.last_refresh.clear()
        self.assertTrue(self.request('/api/x402/status/'+qid)[2]['readyToComplete'])
        status,hs,result=self.request('/api/x402/complete/'+qid,BODY,{'x-x402-payment-id':qid})
        self.assertEqual(status,200);self.assertEqual(result['counts']['output_rows'],2)
        token=hs['x-cleartable-credit-token']
        self.assertEqual(self.request('/api/x402/complete/'+qid,BODY,{'x-x402-payment-id':qid})[0],409)
        self.rpc.by_address[address].append(Payment('B'*64,address,25*10**30,POOL[-1]))
        self.app.last_refresh.clear()
        status,_,credit=self.request('/v1/credit',headers={'Authorization':'Bearer '+token})
        self.assertEqual(status,200);self.assertEqual(credit['remaining_calls'],2500)
        status,_,call=self.request('/v1/clean',BODY,{'Authorization':'Bearer '+token,'Idempotency-Key':'new_request_0001'})
        self.assertEqual(status,200);self.assertEqual(call['credit']['remaining_calls'],2499)
        # Public payment hashes are not credit capabilities.
        self.assertEqual(self.request('/v1/clean',BODY,{'Authorization':'Bearer '+'B'*64,'Idempotency-Key':'new_request_0002'})[0],401)

    def test_unavailable_rpc_never_requests_money(self):
        self.rpc.fail=True
        status,hs,result=self.request('/v1/clean',BODY)
        self.assertEqual(status,503)
        self.assertNotIn('x-payment-address',hs)
        with self.ledger.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM quotes').fetchone()[0],0)

    def test_quote_rate_limit_precedes_external_rpc(self):
        self.rpc.fail=True
        for _ in range(20):self.assertEqual(self.request('/v1/clean',BODY)[0],503)
        self.assertEqual(self.request('/v1/clean',BODY)[0],429)
        self.assertEqual(self.rpc.calls,20)


if __name__=='__main__':unittest.main()
