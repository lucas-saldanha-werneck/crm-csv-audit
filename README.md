# crm-csv-audit

A small Python script that reads a CRM contact export (CSV) and lists what will cause trouble when you load it into a Postgres table. It finds duplicate contacts, bad emails and phones, unreadable dates, and one company spelled several ways. It ends with a short list of constraints that are safe to add and constraints that are not.

Independent demo, not affiliated with A La C.A.R.T.E. Solutions (ALC).

I wrote it after reading a job post about moving a CRM into an internal Postgres platform. Before a migration like that, someone has to find out how dirty the export is. This script does that first pass.

## Run it

Python 3.12 or newer (older versions were not tried). No packages to install.

```
python3 crm_csv_audit.py sample/contacts_example.csv
python3 crm_csv_audit.py export.csv --json
python3 crm_csv_audit.py export.csv --strict          # exit code 1 if any issue is found
python3 crm_csv_audit.py export.csv --map email="E-mail"   # your column has another name
```

Default column names are `Record ID`, `First Name`, `Last Name`, `Email`, `Phone Number`, `Company name`, `Lifecycle Stage` and `Create Date`. If one is missing the script stops with exit code 2 and tells you to use `--map`.

`sample/contacts_example.csv` is invented example data. All names are made up and all emails use `example.com`.

## What it checks

- Missing or repeated record ids.
- Missing or malformed emails, and duplicate emails once case and spaces are ignored.
- Phones with fewer than 8 or more than 15 digits, and the same phone on two rows.
- Company names that differ only by a suffix such as Inc, LLC, Ltd or Co.
- Lifecycle stages outside the usual HubSpot-style list (this list is my assumption).
- Dates that cannot be read, dates in the future, and dates like `03/04/2024` that are valid both day-first and month-first.
- Rows with no first and no last name.

## Tests

```
pip install pytest
python -m pytest -q
```

The same command runs in GitHub Actions (`.github/workflows/test.yml`). Tests run offline.

## What was tested

- 13 automated tests pass locally on Python 3.15 and are set up to run on 3.12 in CI. They cover each check above, the command line flags, the exit codes, and the counts on the sample file.
- The script was run end to end on the invented sample file, which has 10 rows and produces 16 issues.

## What was not tested

- No real CRM export. The column names come from my memory of the usual export format and may not match yours.
- Large files. The script reads the whole file into memory, and I did not measure how it behaves with hundreds of thousands of rows.
- Non-UTF-8 files and exports with a different delimiter.
- Phone numbers are only checked by digit count. It does not know about country rules.
- It only reads files. It does not connect to any CRM or database, and it does not suggest merges or write SQL.
