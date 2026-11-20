"""crm-csv-audit: check a CRM contact export before moving it into Postgres.

Standard library only. Reads one CSV, prints a Markdown report or JSON.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COMPANY_SUFFIX_RE = re.compile(
    r"\b(inc|llc|ltd|corp|co|gmbh|sa|ltda)\b\.?", re.IGNORECASE
)
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%b %d, %Y")

# Column names follow the usual CRM export style; pass --map to rename.
DEFAULT_COLUMNS = {
    "id": "Record ID",
    "first": "First Name",
    "last": "Last Name",
    "email": "Email",
    "phone": "Phone Number",
    "company": "Company name",
    "stage": "Lifecycle Stage",
    "created": "Create Date",
}
DEFAULT_STAGES = {
    "subscriber", "lead", "marketingqualifiedlead", "salesqualifiedlead",
    "opportunity", "customer", "evangelist", "other",
}


def norm_email(value: str) -> str:
    return value.strip().lower()


def norm_company(value: str) -> str:
    text = COMPANY_SUFFIX_RE.sub("", value.lower())
    return re.sub(r"[^a-z0-9]+", "", text)


def norm_phone(value: str) -> str:
    return re.sub(r"\D", "", value)


def parse_date(value: str) -> date | None:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def ambiguous_date(value: str) -> bool:
    """True when both day-first and month-first readings are valid and differ."""
    m = re.match(r"^(\d{1,2})/(\d{1,2})/\d{4}$", value.strip())
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    return a <= 12 and b <= 12 and a != b


def audit(rows: list[dict], columns: dict | None = None, today: date | None = None) -> dict:
    cols = {**DEFAULT_COLUMNS, **(columns or {})}
    today = today or date.today()
    issues: list[dict] = []

    def add(kind: str, line: int, detail: str) -> None:
        issues.append({"kind": kind, "line": line, "detail": detail})

    by_email = defaultdict(list)
    by_phone = defaultdict(list)
    companies = defaultdict(set)
    seen_ids = defaultdict(list)

    for i, row in enumerate(rows):
        line = i + 2  # header is line 1
        get = lambda key: (row.get(cols[key]) or "").strip()
        rid, email, phone = get("id"), get("email"), get("phone")
        company, stage, created = get("company"), get("stage"), get("created")

        if rid:
            seen_ids[rid].append(line)
        else:
            add("missing_id", line, "no record id")

        if not email:
            add("missing_email", line, "no email: cannot be used as a match key")
        elif not EMAIL_RE.match(email):
            add("invalid_email", line, f"not a valid email: {email!r}")
        else:
            by_email[norm_email(email)].append((line, email))

        digits = norm_phone(phone)
        if phone and not 8 <= len(digits) <= 15:
            add("invalid_phone", line, f"{phone!r} has {len(digits)} digits (expected 8-15)")
        elif digits:
            by_phone[digits].append(line)

        if company:
            companies[norm_company(company)].add(company)

        if stage and stage.replace(" ", "").lower() not in DEFAULT_STAGES:
            add("unknown_stage", line, f"stage {stage!r} is not a standard value")

        if created:
            parsed = parse_date(created)
            if parsed is None:
                add("bad_date", line, f"cannot read date {created!r}")
            elif parsed > today:
                add("future_date", line, f"create date {created!r} is in the future")
            elif ambiguous_date(created):
                add("ambiguous_date", line, f"{created!r} can be day-first or month-first")

        if not (get("first") or get("last")):
            add("missing_name", line, "first and last name are both empty")

    for rid, lines in seen_ids.items():
        if len(lines) > 1:
            add("duplicate_id", lines[0], f"record id {rid} repeats on lines {lines}")
    for key, hits in by_email.items():
        if len(hits) > 1:
            spellings = sorted({e for _, e in hits})
            add("duplicate_email", hits[0][0],
                f"{key} appears on lines {[l for l, _ in hits]} (spellings: {spellings})")
    for digits, lines in by_phone.items():
        if len(lines) > 1:
            add("shared_phone", lines[0], f"phone {digits} shared by lines {lines}")
    for key, names in companies.items():
        if len(names) > 1:
            add("company_variants", 0, f"one company, several spellings: {sorted(names)}")

    counts: dict[str, int] = defaultdict(int)
    for issue in issues:
        counts[issue["kind"]] += 1
    return {"rows": len(rows), "issues": issues, "counts": dict(sorted(counts.items()))}


def suggest_constraints(result: dict) -> list[str]:
    counts = result["counts"]
    out = []
    if counts.get("duplicate_email"):
        out.append("Merge duplicate emails before load, then add UNIQUE (lower(email)).")
    else:
        out.append("No duplicate emails found: UNIQUE (lower(email)) is safe.")
    if counts.get("duplicate_id"):
        out.append("Record ids repeat: do not use them as PRIMARY KEY until fixed.")
    if counts.get("company_variants"):
        out.append("Load companies into their own table and map contacts by id, not by name.")
    if counts.get("ambiguous_date") or counts.get("bad_date"):
        out.append("Confirm the date format with the export owner; store as timestamptz.")
    if counts.get("unknown_stage"):
        out.append("Map unknown lifecycle stages to a lookup table or a CHECK list.")
    return out


def to_markdown(result: dict, source: str) -> str:
    lines = [f"# CRM export audit: {source}", "",
             f"Rows read: {result['rows']}  |  Issues: {len(result['issues'])}", ""]
    if not result["issues"]:
        lines.append("No issues found.")
    else:
        lines += ["| Issue | Count |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in result["counts"].items()]
        lines += ["", "## Details", ""]
        for issue in result["issues"]:
            where = f"line {issue['line']}" if issue["line"] else "file"
            lines.append(f"- **{issue['kind']}** ({where}): {issue['detail']}")
    lines += ["", "## Before you load it", ""]
    lines += [f"- {s}" for s in suggest_constraints(result)]
    return "\n".join(lines) + "\n"


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Audit a CRM contact CSV export.")
    p.add_argument("csv_file")
    p.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    p.add_argument("--map", action="append", default=[], metavar="FIELD=Column Name",
                   help="rename a column, e.g. --map email='E-mail'")
    p.add_argument("--strict", action="store_true", help="exit 1 if any issue is found")
    args = p.parse_args(argv)

    columns = {}
    for item in args.map:
        field, _, name = item.partition("=")
        if field not in DEFAULT_COLUMNS or not name:
            p.error(f"--map expects one of {sorted(DEFAULT_COLUMNS)}=Column Name")
        columns[field] = name

    rows = read_csv(args.csv_file)
    if rows:
        missing = [c for k, c in {**DEFAULT_COLUMNS, **columns}.items() if c not in rows[0]]
        if missing:
            print(f"Columns not found: {missing}. Use --map.", file=sys.stderr)
            return 2
    result = audit(rows, columns)
    out = json.dumps(result, indent=2) if args.json else to_markdown(result, args.csv_file)
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    return 1 if args.strict and result["issues"] else 0


if __name__ == "__main__":
    sys.exit(main())
