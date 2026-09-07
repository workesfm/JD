# CSV / XLSX cleanup sample

All included records are synthetic. They demonstrate functionality and are not customer work or revenue.

From this directory, with Python 3.10 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python clean_tables.py sample/batch-a.csv sample/batch-b.csv --config sample/config.json --out my-output
```

On Windows use `.venv\Scripts\python.exe` instead of `.venv/bin/python`.

Open `my-output/report.html` or `my-output/cleaned.xlsx`. The expected result is 12 input records: 5 accepted, 1 duplicate and 6 exceptions. Accepted totals are USD 110.30 and CNY 88.00. The two conflicting records for ID 0002 are both held for review.

The output also contains CSV files and a JSON summary with source-file and configuration hashes. The program does not overwrite an existing output directory or modify input files. It sends no data over the network while processing.

Set exact column aliases, supported currencies and date formats in the configuration. Do not use ambiguous date conventions. The example uses record_id as a global unique key; a different business identity rule requires customization. XLSX identifiers must be stored as text, and multi-sheet workbooks need an explicit xlsx_sheet configuration.

The implementation supports up to five flat inputs, 10 MiB per input and 50,000 total nonblank records. It accepts ordinary decimal monetary values with at most two fractional digits and absolute value below 10^12. It does not perform OCR, evaluate formulas, convert currencies or make accounting decisions. Totals cover accepted records only; exceptions need review before any claim that the entire dataset reconciles.

Exact duplicates are set aside with their source references. Conflicting IDs and IDs with any invalid sibling record are fully quarantined. Formula-looking text is kept inert in XLSX; unsafe CSV text receives a leading apostrophe. Extra columns outside the configured five-field output schema stay in the original source files and are not part of the clean table.

For validation:

```bash
.venv/bin/python -m unittest discover -p 'test_*.py' -v
```

See VALIDATION.json for the observed sample and capacity check. Client delivery still requires validation against the client's agreed sample and rules.
