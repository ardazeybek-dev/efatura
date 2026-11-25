from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import BUYER_TCKN, make_invoice

import efatura_tr
from efatura_tr import ERROR, WARNING


def codes(xml: str) -> set[str]:
    return {i.code for i in efatura_tr.read(xml).check()}


def test_synthetic_invoice_is_clean():
    inv = efatura_tr.read(make_invoice())
    assert inv.check() == []
    assert inv.totals.payable == Decimal("2562.00")
    assert inv.vat_total == Decimal("427.00")


def test_parsed_fields():
    inv = efatura_tr.read(make_invoice())
    assert inv.supplier.identifiers == {"VKN": "9876543217", "MERSISNO": "0987654321700015"}
    assert inv.supplier.email == "fatura@satici.example"
    assert inv.supplier.website == "https://satici.example"
    assert (
        str(inv.supplier.address) == "Caferağa Mah. Örnek Cad. 7, 34710, Kadıköy/İstanbul, Türkiye"
    )
    (pay,) = inv.payments
    assert pay.account == "TR330006100519786457841326"
    assert pay.due_date.isoformat() == "2024-04-13"
    assert inv.notes == ("Deneme faturası",)
    assert inv.lines[1].seller_item_id == "SKU-2"
    assert inv.issue_time == "10:30:00"
    assert inv.copy_indicator is False
    assert inv.line_count == 2


def test_person_customer():
    inv = efatura_tr.read(make_invoice(customer_scheme="TCKN", customer_id=BUYER_TCKN))
    assert inv.customer.name == "Ayşe Örnek"
    assert inv.check() == []


def test_withholding_invoice_is_clean():
    xml = make_invoice(type_code="TEVKIFAT", withholding=("601", "40"))
    inv = efatura_tr.read(xml)
    assert inv.check() == []
    assert inv.withholding_total == Decimal("170.80")
    assert inv.totals.payable == Decimal("2135") + Decimal("427.00") - Decimal("170.80")


def test_document_discount_is_clean():
    inv = efatura_tr.read(make_invoice(doc_allowance="135"))
    assert inv.totals.tax_exclusive == Decimal("2000")
    assert inv.check() == []


def test_foreign_currency_needs_rate():
    assert "currency.rate" in codes(make_invoice(currency="USD"))
    assert "currency.rate" not in codes(make_invoice(currency="USD", rate="32.1"))
    assert efatura_tr.read(make_invoice(currency="EUR", rate="35.5")).exchange_rate == Decimal(
        "35.5"
    )


@pytest.mark.parametrize(
    ("kwargs", "code", "severity"),
    [
        ({"number": "ABC24000001"}, "number.format", ERROR),
        ({"number": "ABC2023000000001"}, "number.year", WARNING),
        ({"uuid": "not-a-uuid"}, "uuid.format", ERROR),
        ({"type_code": "IADE"}, "return.reference", ERROR),
        ({"type_code": "TEVKIFAT"}, "withholding.missing", WARNING),
        ({"type_code": "SATISS"}, "code.type", WARNING),
        ({"profile": "EFATURA"}, "code.profile", WARNING),
        ({"customer_id": "123"}, "customer.vkn", ERROR),
        ({"customer_id": "1111111115"}, "customer.vkn", WARNING),
        ({"customer_scheme": "TCKN", "customer_id": "10000000147"}, "customer.tckn", WARNING),
        ({"customer_scheme": "MUSTERINO", "customer_id": "42"}, "customer.id", ERROR),
        ({"totals": {"PayableAmount": "2500"}}, "totals.payable", WARNING),
        ({"totals": {"LineExtensionAmount": "2100"}}, "totals.lines", WARNING),
        ({"totals": {"TaxExclusiveAmount": "2100"}}, "totals.tax_exclusive", WARNING),
        ({"totals": {"TaxInclusiveAmount": "2600"}}, "totals.tax_inclusive", WARNING),
    ],
)
def test_detected_problems(kwargs, code, severity):
    issues = efatura_tr.read(make_invoice(**kwargs)).check()
    assert code in {i.code for i in issues}
    assert next(i for i in issues if i.code == code).severity == severity


def test_line_amount_mismatch():
    lines = [{"qty": "2", "price": "1000", "name": "Laptop", "amount": "1900"}]
    issues = efatura_tr.read(make_invoice(lines=lines)).check()
    (issue,) = [i for i in issues if i.code == "line.amount"]
    assert issue.message == "line 1: 2 x 1000 = 2,000.00, but the line says 1,900.00"


def test_one_kurus_rounding_is_tolerated():
    assert codes(make_invoice(totals={"PayableAmount": "2562.01"})) == set()
    assert "totals.payable" in codes(make_invoice(totals={"PayableAmount": "2562.03"}))


def test_exemption_without_code():
    assert "exemption.missing" in codes(make_invoice(type_code="ISTISNA", vat="0"))
    assert codes(make_invoice(type_code="ISTISNA", vat="0", exemption=("301", "11/1-a"))) == set()


def test_unknown_exemption_and_unit_codes():
    lines = [{"qty": "1", "price": "10", "name": "x", "unit": "XYZ"}]
    got = codes(make_invoice(lines=lines, vat="0", exemption=("999", "?")))
    assert {"code.unit", "code.exemption"} <= got


def test_return_with_reference_is_clean():
    ref = """<cac:BillingReference><cac:InvoiceDocumentReference>
      <cbc:ID>ABC2024000000000</cbc:ID><cbc:IssueDate>2024-03-01</cbc:IssueDate>
      </cac:InvoiceDocumentReference></cac:BillingReference>"""
    inv = efatura_tr.read(make_invoice(type_code="IADE", extra=ref))
    assert inv.check() == []
    assert inv.billing_references[0].id == "ABC2024000000000"


def test_errors_come_first_and_str():
    issues = efatura_tr.check(efatura_tr.read(make_invoice(number="X", customer_id="1111111115")))
    assert issues[0].severity == ERROR
    assert str(issues[0]).startswith("error: invoice number 'X'")
