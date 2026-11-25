from __future__ import annotations

import io
import zipfile
from decimal import Decimal

import pytest
from conftest import GIB, make_invoice

import efatura_tr
from efatura_tr import InvoiceError, UnsafeXMLError


def test_read_text_bytes_and_file_object():
    xml = make_invoice()
    from_text = efatura_tr.read(xml)
    from_bytes = efatura_tr.read(xml.encode("utf-8"))
    from_file = efatura_tr.read(io.BytesIO(xml.encode("utf-8")))
    assert from_text == from_bytes == from_file
    assert from_text.number == "ABC2024000000001"


def test_read_path_string_and_pathlib():
    path = GIB / "TEVKIFAT.xml"
    assert efatura_tr.read(str(path)).number == efatura_tr.read(path).number


def test_zip_archive(tmp_path):
    archive = tmp_path / "faturalar.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("a/ABC2024000000001.xml", make_invoice())
        z.writestr("ABC2024000000002.xml", make_invoice(number="ABC2024000000002"))
        z.writestr("readme.txt", "not an invoice")
    invoices = efatura_tr.read_all(archive)
    assert sorted(i.number for i in invoices) == ["ABC2024000000001", "ABC2024000000002"]
    assert any(i.source.endswith("faturalar.zip!a/ABC2024000000001.xml") for i in invoices)


def test_zip_inside_zip_and_zip_bytes(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("f.xml", make_invoice())
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("inner.zip", inner.getvalue())
    (inv,) = efatura_tr.read_all(outer.getvalue())
    assert inv.source == "<bytes>!inner.zip!f.xml"


def test_folder_is_searched_recursively(tmp_path):
    (tmp_path / "2024" / "03").mkdir(parents=True)
    (tmp_path / "2024" / "03" / "a.xml").write_text(make_invoice(), encoding="utf-8")
    (tmp_path / "b.XML").write_text(make_invoice(number="ABC2024000000002"), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignore me", encoding="utf-8")
    assert len(efatura_tr.read_all(tmp_path)) == 2


def test_list_of_sources():
    invoices = efatura_tr.read_all([GIB / "TEVKIFAT.xml", make_invoice()])
    assert [i.type for i in invoices] == ["TEVKIFAT", "SATIS"]


def test_iter_invoices_is_lazy():
    it = efatura_tr.iter_invoices([make_invoice(), "<not xml"])
    assert next(it).number == "ABC2024000000001"
    with pytest.raises(InvoiceError):
        next(it)


BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
 <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
]>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&lol3;</Invoice>"""

XXE = """<?xml version="1.0"?>
<!-- a comment first -->
<!DOCTYPE Invoice [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2">&xxe;</Invoice>"""


@pytest.mark.parametrize("payload", [BILLION_LAUGHS, XXE])
def test_doctype_is_refused(payload):
    with pytest.raises(UnsafeXMLError):
        efatura_tr.read(payload)
    with pytest.raises(UnsafeXMLError):
        efatura_tr.read(payload.encode("utf-16"))


def test_utf16_and_bom_and_turkish_codepage():
    xml = make_invoice()
    utf16 = xml.replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16")
    assert efatura_tr.read(utf16).supplier.name == "Deneme Satıcı A.Ş."
    assert efatura_tr.read(b"\xef\xbb\xbf" + xml.encode("utf-8")).number
    latin5 = xml.replace('encoding="UTF-8"', 'encoding="ISO-8859-9"').encode("iso-8859-9")
    assert efatura_tr.read(latin5).customer.address.subdivision == "Çankaya"


def test_not_xml_and_no_invoice():
    with pytest.raises(InvoiceError, match="not valid XML"):
        efatura_tr.read(b"<Invoice>")
    with pytest.raises(InvoiceError, match="no UBL Invoice"):
        efatura_tr.read("<root/>")


def test_read_refuses_several_invoices():
    with pytest.raises(InvoiceError, match="found 2 invoices"):
        efatura_tr.read([make_invoice(), make_invoice()])


def test_bad_zip(tmp_path):
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"PK\x03\x04 broken")
    with pytest.raises(InvoiceError, match="not a valid ZIP"):
        efatura_tr.read_all(bad)


def test_missing_totals_and_bad_numbers():
    xml = make_invoice()
    start = xml.index("<cac:LegalMonetaryTotal>")
    end = xml.index("</cac:LegalMonetaryTotal>") + len("</cac:LegalMonetaryTotal>")
    with pytest.raises(InvoiceError, match="LegalMonetaryTotal is missing"):
        efatura_tr.read(xml[:start] + xml[end:])
    broken = xml.replace(">2</cbc:InvoicedQuantity>", ">iki</cbc:InvoicedQuantity>")
    with pytest.raises(InvoiceError, match="ABC2024000000001: .*'iki' is not a number"):
        efatura_tr.read(broken)


@pytest.mark.parametrize(
    ("written", "value"),
    [("1,234.56", "1234.56"), ("1,234", "1234"), ("12,50", "12.50"), (" 7 ", "7")],
)
def test_number_formats(written, value):
    xml = make_invoice().replace(">1000</cbc:PriceAmount>", f">{written}</cbc:PriceAmount>")
    assert efatura_tr.read(xml).lines[0].unit_price == Decimal(value)
