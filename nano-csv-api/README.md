# ClearTable Nano CSV API — pilot

Runs a real CSV cleanup operation behind a NanoGPT-style HTTP 402 quote, status
and completion flow. The initial price is **0.01 XNO** per request, at most
1,000 data rows and 100,000 UTF-8 CSV bytes. Trimming and exact duplicate removal
are explicit options; required values and malformed rows are reported.

The experimental pilot is reachable at:
https://xow1hv-ip-47-239-116-165.tunnelmole.net

The buyer [confirmed the real paid acceptance checks](https://github.com/workesfm/JD/issues/1#issuecomment-5575696956). The hostname above was restored on 2026-09-09 after the previous tunnel disconnected. This is a temporary public hostname for pilot testing; it may change after a connection restart. Existing credit survives hostname changes. Updates are posted in the same issue thread. No availability SLA is offered for the pilot.

## Request and payment flow

POST `/api/x402/v1/clean` with `Content-Type: application/json` and `x-x402: nano`:

```json
{"csv":"name,email\n Alice ,a@example.test\nAlice,a@example.test\nBob,\nCara,c@example.test\n","required_columns":["name","email"],"trim":true,"deduplicate":true}
```

The 402 response supplies `x-payment-address`, `x-payment-amount` (in XNO),
`x-payment-id`, and `x-payment-network: nano:mainnet`. The NanoGPT-style
`payment.accepted[]` option uses `scheme: nano`, its legacy `nano-mainnet`
network name, and an **integer raw amount**. One XNO is 10^30 raw; this call costs
10^28 raw. Use only the address in the actual quote.

The caller sends the quoted amount using its own wallet. This application has
no transaction signing, send, receive, withdrawal, or node `process` RPC.

Poll `payment.statusUrl` until `readyToComplete` is true. POST the **byte-identical
body** to `payment.completeUrl` with `x-x402-payment-id` set to the payment ID.
The result contains `cleaned_csv`, row counts, duplicate row numbers, and
exception reasons. A completion consumes its quote once; another request body
or another attempt to consume the quote is rejected. If a completed response
was lost in transit, POST the same body and payment-ID header to
`/api/x402/receipt/<payment ID>` to retrieve that paid result and its credit
credential; this endpoint performs no new debit.

Unfunded quotes expire after 24 hours. Confirmed late deposits remain redeemable
against the original request body at the fixed quoted price.

## Prepaid credit

Completion returns a private `x-cleartable-credit-token`. Keep it out of logs,
public posts, and repository files. A public send-block hash is not an API key.

Additional confirmed deposits to the same quoted address add credit to the same
account. A deposit of 25 XNO adds 2,500 calls at the initial price. Each block is
credited once, including across process restarts and concurrent requests.

Use `Authorization: Bearer <credit token>` and a unique `Idempotency-Key` of
16–100 letters, digits, underscores or hyphens when posting another cleanup to
`/v1/clean`. Repeating that key with the same body retrieves the same result
without another debit; changing the body under the same key is rejected.
GET `/v1/credit` at the origin root with that token refreshes confirmed deposits
and returns credit and usage. For the current hostname this is
`https://xow1hv-ip-47-239-116-165.tunnelmole.net/v1/credit`.
Do not append `/v1/credit` beneath `/api/x402/`. Confirmed incoming amounts, consumed usage and unused prepayment are
recorded separately.

## Payment verification and state

The primary RPC enumerates confirmed receivable blocks for the assigned address.
Both configured public RPC services must verify each new payment. The application
recomputes the send block and previous block hashes, derives the actual amount
from the balance decrease, checks the destination, and requires confirmation.
RPC outages fail closed and do not cause an unpaid result to be served.

SQLite transactions and uniqueness constraints protect payment imports,
completion consumption and credit debits. Customer CSV bodies are processed in
memory and are not written to the ledger. The ledger contains request hashes,
payment records and credit/usage state. Back it up as private operational data.

The runtime holds a pre-generated public receiving-address pool and a credit
authentication secret; it does not hold the Nano seed. The account owner retains
the seed separately. Incoming Nano can remain receivable until the owner performs
a receive operation; it is not reported as a completed withdrawal or transfer.

## Running and validation

Python 3.11+; the HTTP server and ledger use the standard library. Bind the origin
server to loopback and put it behind an explicitly configured HTTPS ingress.
Set `CLEARTABLE_NANO_PRIVATE_DIR` to a protected directory outside the source tree.
Its `config.json` contains `public_origin`, `port`, `rpc_url`,
`verification_rpc_url`, and `credit_token_secret`; `address-pool.json` contains the
public receiving addresses. Keep the directory mode 0700 and secret files 0600.

```sh
python3 -m unittest -v test_core.py test_http.py
python3 -u server.py
```

The tests use valueless simulated payments. They cover row conservation, invalid
input, body binding, payment reuse, restart persistence, concurrent completion,
concurrent credit depletion, credit top-ups, the published Nano amount units,
failure before asking for payment, and rate limiting before RPC access. A state
hash fixture was computed independently with `nanocurrency` 2.5.0.

Reference protocol: https://pursekeeper.dev/examples/buy-from-nanogpt.md
Nano block format: https://docs.nano.org/integration-guides/the-basics/
