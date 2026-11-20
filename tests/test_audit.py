import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import crm_csv_audit as a  # noqa: E402

SAMPLE = os.path.join(os.path.dirname(__file__), "..", "sample", "contacts_example.csv")
TODAY = date(2026, 11, 20)


def row(**kw):
    base = {"Record ID": "1", "First Name": "A", "Last Name": "B", "Email": "a@example.com",
            "Phone Number": "+55 21 99999-0001", "Company name": "Co", "Lifecycle Stage": "lead",
            "Create Date": "2024-01-31"}
    base.update({k.replace("_", " "): v for k, v in kw.items()})
    return base


def kinds(result):
    return result["counts"]


def test_clean_row_has_no_issues():
    assert a.audit([row()], today=TODAY)["issues"] == []


def test_duplicate_email_ignores_case_and_spaces():
    r = a.audit([row(Record_ID="1", Email="X@Example.com"), row(Record_ID="2", Email=" x@example.com ")], today=TODAY)
    assert kinds(r)["duplicate_email"] == 1


def test_invalid_and_missing_email():
    r = a.audit([row(Record_ID="1", Email="nope@x"), row(Record_ID="2", Email="")], today=TODAY)
    assert kinds(r)["invalid_email"] == 1 and kinds(r)["missing_email"] == 1


def test_duplicate_id():
    r = a.audit([row(Email="a@example.com"), row(Email="b@example.com")], today=TODAY)
    assert kinds(r)["duplicate_id"] == 1


def test_phone_length_and_sharing():
    r = a.audit([row(Record_ID="1", Email="a@e.com", Phone_Number="123"),
                 row(Record_ID="2", Email="b@e.com", Phone_Number="(212) 555-0103"),
                 row(Record_ID="3", Email="c@e.com", Phone_Number="212-555-0103")], today=TODAY)
    assert kinds(r)["invalid_phone"] == 1 and kinds(r)["shared_phone"] == 1


def test_company_variants_by_suffix():
    r = a.audit([row(Record_ID="1", Email="a@e.com", Company_name="Blue Harbor LLC"),
                 row(Record_ID="2", Email="b@e.com", Company_name="Blue Harbor")], today=TODAY)
    assert kinds(r)["company_variants"] == 1


def test_date_checks():
    assert a.parse_date("13/05/2024") == date(2024, 5, 13)
    assert a.parse_date("nonsense") is None
    assert a.ambiguous_date("03/04/2024") and not a.ambiguous_date("13/04/2024")
    assert not a.ambiguous_date("03/03/2024")
    r = a.audit([row(Create_Date="2030-01-01")], today=TODAY)
    assert kinds(r)["future_date"] == 1


def test_unknown_stage_and_missing_name():
    r = a.audit([row(Lifecycle_Stage="prospect", First_Name="", Last_Name="")], today=TODAY)
    assert kinds(r)["unknown_stage"] == 1 and kinds(r)["missing_name"] == 1


def test_sample_file_counts_are_stable():
    r = a.audit(a.read_csv(SAMPLE), today=TODAY)
    assert r["rows"] == 10
    assert kinds(r)["duplicate_email"] == 1
    assert kinds(r)["company_variants"] == 4
    assert len(r["issues"]) == 16


def test_cli_json_and_strict(capsys):
    code = a.main([SAMPLE, "--json", "--strict"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1 and out["rows"] == 10


def test_cli_wrong_columns_returns_2(tmp_path, capsys):
    f = tmp_path / "x.csv"
    f.write_text("a,b\n1,2\n")
    assert a.main([str(f)]) == 2
    assert "Use --map" in capsys.readouterr().err


def test_cli_map_renames_column(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("Record ID,First Name,Last Name,E-mail,Phone Number,Company name,Lifecycle Stage,Create Date\n"
                 "1,A,B,a@example.com,+55 21 99999-0001,Co,lead,2024-01-31\n")
    assert a.main([str(f), "--map", "email=E-mail", "--strict"]) == 0


def test_markdown_report_mentions_constraint_advice():
    r = a.audit([row()], today=TODAY)
    assert "UNIQUE (lower(email)) is safe" in a.to_markdown(r, "x.csv")
