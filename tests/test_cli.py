from __future__ import annotations

import csv
import io
import json

from conftest import GIB, make_invoice

from efatura_tr.cli import main


def run(capsys, *args) -> tuple[int, str, str]:
    code = main([str(a) for a in args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_summary(capsys):
    code, out, _ = run(capsys, GIB / "TEVKIFAT.xml")
    assert code == 0
    assert out.startswith("SRM2012000086985 · 2012-08-04 · TICARIFATURA/TEVKIFAT · TRY")
    assert "Tevkifat 606 %90  -3,240.00" in out
    assert "Payable           20,360.00 TRY" in out


def test_summary_of_clean_invoice(capsys, tmp_path):
    path = tmp_path / "f.xml"
    path.write_text(make_invoice(), encoding="utf-8")
    code, out, _ = run(capsys, path)
    assert code == 0
    assert "Dizüstü bilgisayar" in out
    assert "2 Adet" in out
    assert out.rstrip().endswith("No problems found.")


def test_json(capsys):
    code, out, _ = run(capsys, GIB / "TEVKIFAT.xml", GIB / "OTV.xml", "--json")
    data = json.loads(out)
    assert code == 0
    assert [d["number"] for d in data] == ["SRM2012000086985", "SRM2012000045142"]
    assert data[0]["totals"]["payable"] == "20360"
    assert data[0]["issues"][0]["code"] == "supplier.vkn"


def test_csv_has_vat_columns_per_rate(capsys):
    code, out, _ = run(capsys, GIB / "TicariFaturaOrnegi.xml", GIB / "HASTANE.xml", "--csv")
    rows = list(csv.DictReader(io.StringIO(out)))
    assert code == 0
    assert rows[0]["number"] == "GIB2009000000011"
    assert rows[0]["vat_base_18"] == "25216.50"
    assert rows[0]["vat_18"] == "4538.97"
    assert rows[0]["vat_8"] == ""
    assert rows[1]["vat_8"] == "11.28"
    assert rows[1]["billing_reference"] == "55099162"


def test_excel_csv(capsys, tmp_path):
    target = tmp_path / "out.csv"
    code, _, _ = run(capsys, GIB / "TEVKIFAT.xml", "--excel", "-o", target)
    raw = target.read_bytes()
    assert code == 0
    assert raw.startswith(b"\xef\xbb\xbf")
    header, row = raw.decode("utf-8-sig").splitlines()
    assert header.startswith("source;number;")
    assert ";20360;" in row and ";3240;" in row


def test_excel_uses_decimal_comma(capsys):
    _, out, _ = run(capsys, GIB / "TicariFaturaOrnegi.xml", "--lines", "--excel")
    rows = list(csv.DictReader(io.StringIO(out.lstrip("﻿")), delimiter=";"))
    assert rows[0]["unit_price"] == "825,5"
    assert rows[0]["discount"] == "495,3"


def test_lines_csv(capsys):
    code, out, _ = run(capsys, GIB / "TEVKIFAT.xml", "--lines")
    (row,) = list(csv.DictReader(io.StringIO(out)))
    assert code == 0
    assert row["item"] == "İş gücü hizmeti"
    assert row["amount"] == "20000"


def test_check_exit_codes(capsys, tmp_path):
    good = tmp_path / "good.xml"
    good.write_text(make_invoice(), encoding="utf-8")
    code, out, _ = run(capsys, good, "--check")
    assert (code, out) == (0, "ABC2024000000001: ok\n")
    bad = tmp_path / "bad.xml"
    bad.write_text(make_invoice(number="BAD"), encoding="utf-8")
    code, out, _ = run(capsys, good, bad, "--check")
    assert code == 1
    assert "BAD: error: invoice number 'BAD'" in out


def test_unreadable_file_is_reported_and_others_still_run(capsys, tmp_path):
    (tmp_path / "broken.xml").write_text("<Invoice", encoding="utf-8")
    (tmp_path / "ok.xml").write_text(make_invoice(), encoding="utf-8")
    code, out, err = run(capsys, tmp_path, "--check")
    assert code == 2
    assert "broken.xml: " in err and "not valid XML" in err
    assert "ABC2024000000001: ok" in out


def test_attachments(capsys, tmp_path):
    code, _, err = run(capsys, GIB / "1_TEMEL_FATURA.xml", "--attachments", tmp_path, "--check")
    saved = tmp_path / "TST2013000000766.xslt"
    assert code == 0
    assert saved.read_bytes().startswith(b"<?xml")
    assert "saved" in err
