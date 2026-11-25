"""Every official sample from GIB's UBL-TR 1.2.1 and e-Fatura packages.

The samples are not all correct. The expected problems below were checked by
hand against the XML: they are real mistakes in GIB's own examples, and any new
problem showing up here is a false positive to fix.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import GIB

import efatura_tr

SAMPLES = sorted(p.name for p in GIB.glob("*.xml"))

# Placeholder VKN/TCKN like 1111111111 fail the checksum in almost every
# sample, so ID checksum warnings are left out of this table.
EXPECTED = {
    "1_TEMEL_FATURA.xml": {"currency.rate", "code.currency"},  # TRL, the pre-2005 lira
    "1_TEMEL_FATURA_ZARF.xml": {"currency.rate", "code.currency"},
    "ISTISNA-1.xml": {"customer.id", "currency.rate", "totals.tax_exclusive", "supplier.vkn"},
    "ISTISNA-2.xml": {"currency.rate", "line.amount", "totals.lines"},
    "OTV.xml": {"customer.vkn", "totals.tax_inclusive"},
    "TemelFaturaOrnegi.xml": {"number.format", "customer.tckn"},
    "YTB_TevkifatIade_EArsiv.xml": {"tax.amount"},
    "YTB_TevkifatIade_Efatura.xml": {"tax.amount"},
}


def _codes(invoice, *, with_checksums: bool) -> set[str]:
    out = set()
    for issue in invoice.check():
        is_checksum = issue.code.endswith((".vkn", ".tckn")) and "checksum" in issue.message
        if with_checksums or not is_checksum:
            out.add(issue.code)
    return out


def test_all_samples_are_present():
    assert len(SAMPLES) == 30


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_reads(name):
    invoice = efatura_tr.read(GIB / name)
    assert invoice.number and invoice.uuid and invoice.issue_date
    assert invoice.lines
    assert invoice.totals.payable > 0
    assert invoice.supplier.name and invoice.customer.name
    assert invoice.source.endswith(name)


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_problems_are_the_known_ones(name):
    invoice = efatura_tr.read(GIB / name)
    assert _codes(invoice, with_checksums=False) == EXPECTED.get(name, set())


@pytest.mark.parametrize("name", SAMPLES)
def test_sample_to_dict_is_json_ready(name):
    import json

    data = efatura_tr.read(GIB / name).to_dict()
    assert json.loads(json.dumps(data))["number"] == data["number"]


def test_tevkifat():
    inv = efatura_tr.read(GIB / "TEVKIFAT.xml")
    assert (inv.number, inv.type, inv.profile) == ("SRM2012000086985", "TEVKIFAT", "TICARIFATURA")
    assert inv.uuid == "F47AC10B-58CC-4372-A567-0E02B2C3D479"
    assert inv.issue_date == date(2012, 8, 4)
    assert inv.vat_total == Decimal("3600")
    assert inv.tax_total == Decimal("360")  # KDV left after withholding
    assert inv.withholding_total == Decimal("3240")
    (w,) = inv.withholdings
    assert (w.code, w.percent, w.amount) == ("606", Decimal("90"), Decimal("3240"))
    assert inv.totals.tax_inclusive == Decimal("23600")
    assert inv.totals.payable == Decimal("20360")
    assert inv.supplier.vkn == "0890890895"
    assert inv.supplier.tax_office == "Ziyapaşa"
    assert inv.supplier.address.subdivision == "Seyhan"
    assert inv.supplier.address.city == "Adana"
    assert inv.supplier.address.district == "Ziyapaşa Mah."


def test_ticari_fatura_lines_and_discounts():
    inv = efatura_tr.read(GIB / "TicariFaturaOrnegi.xml")
    assert len(inv.lines) == 8
    first = inv.lines[0]
    assert first.name == "Masa Üstü Bilgisayar"
    assert (first.quantity, first.unit_code, first.unit_name) == (Decimal("12"), "NIU", "Adet")
    assert first.unit_price == Decimal("825.5")
    assert first.amount == Decimal("9410.7")
    (discount,) = first.allowances
    assert (discount.is_charge, discount.amount, discount.rate) == (
        False,
        Decimal("495.3"),
        Decimal("0.05"),
    )
    assert first.vat_rate == Decimal("18")
    assert first.vat_amount == Decimal("1693.93")
    assert inv.totals.allowance_total == Decimal("786.90")
    assert inv.vat_breakdown == {Decimal("18"): (Decimal("25216.50"), Decimal("4538.97"))}


def test_envelope_holds_the_same_invoice():
    bare = efatura_tr.read(GIB / "1_TEMEL_FATURA.xml")
    wrapped = efatura_tr.read(GIB / "1_TEMEL_FATURA_ZARF.xml")
    assert bare.to_dict() | {"source": None} == wrapped.to_dict() | {"source": None}


def test_embedded_xslt():
    inv = efatura_tr.read(GIB / "1_TEMEL_FATURA.xml")
    xslt = inv.xslt
    assert xslt is not None
    assert xslt.filename == "TST2013000000766.xslt"
    assert b"<xsl:stylesheet" in xslt.data[:200]


def test_return_invoice_references_original():
    inv = efatura_tr.read(GIB / "IadeFaturasiOrnegi.xml")
    assert inv.type == "IADE"
    (ref,) = inv.billing_references
    assert (ref.id, ref.issue_date) == ("GIB2009000000011", date(2009, 1, 5))


def test_export_invoice_has_end_buyer():
    inv = efatura_tr.read(GIB / "IHRACAT.xml")
    assert inv.profile == "IHRACAT"
    assert inv.buyer is not None and inv.buyer.name == "Farthing Purchasing Consortium"
    # The customer of an export invoice is the customs administration.
    assert inv.customer.name.startswith("Gümrük ve Ticaret Bakanlığı")
    assert "\n" not in inv.customer.name
    (vat,) = inv.taxes
    assert vat.exemption_code == "301"


def test_otv_per_unit_tax():
    inv = efatura_tr.read(GIB / "OTV.xml")
    otv, kdv = inv.taxes
    assert (otv.code, otv.per_unit_amount, otv.amount) == (
        "0071",
        Decimal("1.9985"),
        Decimal("1842.62"),
    )
    assert kdv.taxable_amount == Decimal("8234.29")  # ÖTV is part of the KDV base


def test_person_names_and_tckn():
    inv = efatura_tr.read(GIB / "OZELMATRAH.xml")
    assert inv.customer.tckn == "39586528950"
    assert inv.customer.vkn is None
    assert inv.customer.tax_id == "39586528950"


def test_earchive_profile():
    inv = efatura_tr.read(GIB / "YTB_Satis_EArsiv.xml")
    assert inv.is_earchive


def test_hks_commission_is_taken_off_payable():
    inv = efatura_tr.read(GIB / "HKS-Ornek2.xml")
    assert inv.type == "KOMISYONCU"
    assert inv.totals.payable == Decimal("1079780.00")
    assert not [i for i in inv.check() if i.code.startswith("totals.")]
