# CSV / Excel cleanup & repeatable automation

Independent data-automation service by **[@workesfm](https://github.com/workesfm)**.

**$175 fixed scope · first delivery targeted within 48 hours after scope and inputs are agreed.**

Merge recurring exports, isolate duplicates and conflicts, and get a clean workbook with a repeatable script. Start with 20–50 synthetic or redacted rows so the rules and acceptance cases are clear.

## What is included

- Up to five flat CSV / XLSX files and 50,000 total records.
- One agreed schema, unique-key rule, date convention and currency/amount format.
- A clean Excel workbook and CSV, duplicate and exception logs, and per-currency totals.
- Python source, configuration, pinned dependencies and a handover guide.
- One in-scope revision and seven days of fixes for deviations from the agreed rules.

USDC settlement on Base can be agreed with the order. Payment details and any fees are specified with the accepted quote. No payment is requested just to discuss a sample.

## Inspect the sample

All included data is synthetic. It is a capability demonstration, not a client case study.

| Input | Accepted | Duplicates set aside | Exceptions |
|---:|---:|---:|---:|
| 12 | 5 | 1 | 6 |

Accepted totals: **USD 110.30** and **CNY 88.00**, calculated separately. Both sides of a conflicting record ID are held for review.

- [Sample workbook](demo-output/cleaned.xlsx)
- [Verification report source](demo-output/report.html)
- [Exact totals and source hashes](demo-output/summary.json)
- [English run instructions](README.en.md) · [中文使用说明](README.zh-CN.md)
- [Implementation](clean_tables.py) · [Tests](test_clean_tables.py)

Nine tests passed. A separate 50,000-record synthetic run exported and reopened its workbook successfully; observed processing time was about 4.2 seconds on the development machine. Actual customer-file performance varies.

## Start a scope review

Open an issue in this repository with **[Data cleanup inquiry]** in the title, or reply to the service-inquiry thread. Include only:

1. File format and approximate record count.
2. Column names and the repeated manual steps.
3. Desired output and deadline.
4. A synthetic or redacted example if useful.

GitHub issues are public. Keep confidential records, account details and credentials out of them. A private handover channel will be agreed before any real customer files are transferred.

The implementation uses AI assistance and executable validation. Ambiguous dates and disputed amounts are flagged for your decision. OCR, complex workbook-template reconstruction, account integrations and accounting judgments need a separate scope. This branch contains the standalone service sample and does not use the scripts in the repository's historical default branch.
