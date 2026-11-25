"""Shared helpers: paths to the official GIB samples and a synthetic invoice builder.

The synthetic parties are made up. Their VKN/TCKN pass the checksum but belong
to nobody we know of.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

GIB = Path(__file__).parent / "fixtures" / "gib"

SELLER_VKN = "9876543217"
BUYER_VKN = "1111111114"
BUYER_TCKN = "10000000146"


def _amount(value) -> str:
    return format(Decimal(str(value)), "f")


def make_invoice(
    *,
    number: str = "ABC2024000000001",
    uuid: str = "3f2b8c1e-4d5a-4b6c-9e7f-0a1b2c3d4e5f",
    issue_date: str = "2024-03-14",
    profile: str = "TICARIFATURA",
    type_code: str = "SATIS",
    currency: str = "TRY",
    rate: str | None = None,
    lines: list[dict] | None = None,
    vat: str = "20",
    withholding: tuple[str, str] | None = None,
    doc_allowance: str | None = None,
    totals: dict | None = None,
    customer_scheme: str = "VKN",
    customer_id: str = BUYER_VKN,
    extra: str = "",
    exemption: tuple[str, str] | None = None,
) -> str:
    """A small, internally consistent UBL-TR invoice. Override pieces to break it."""
    lines = lines or [
        {"qty": "2", "price": "1000", "name": "Dizüstü bilgisayar", "unit": "C62"},
        {"qty": "3", "price": "50", "name": "Mouse", "unit": "C62", "discount": "15"},
    ]
    vat_rate = Decimal(vat)
    line_xml = []
    net_total = Decimal(0)
    vat_total = Decimal(0)
    for n, line in enumerate(lines, 1):
        gross = Decimal(line["qty"]) * Decimal(line["price"])
        discount = Decimal(line.get("discount", "0"))
        net = Decimal(line.get("amount", gross - discount))
        tax = (net * vat_rate / 100).quantize(Decimal("0.01"))
        net_total += net
        vat_total += tax
        allowance = (
            f"""<cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator>
            <cbc:Amount currencyID="{currency}">{_amount(discount)}</cbc:Amount>
            <cbc:BaseAmount currencyID="{currency}">{_amount(gross)}</cbc:BaseAmount>
            </cac:AllowanceCharge>"""
            if discount
            else ""
        )
        line_xml.append(
            f"""<cac:InvoiceLine>
  <cbc:ID>{n}</cbc:ID>
  <cbc:InvoicedQuantity unitCode="{line.get("unit", "C62")}">{line["qty"]}</cbc:InvoicedQuantity>
  <cbc:LineExtensionAmount currencyID="{currency}">{_amount(net)}</cbc:LineExtensionAmount>
  {allowance}
  <cac:TaxTotal>
    <cbc:TaxAmount currencyID="{currency}">{_amount(tax)}</cbc:TaxAmount>
    <cac:TaxSubtotal>
      <cbc:TaxableAmount currencyID="{currency}">{_amount(net)}</cbc:TaxableAmount>
      <cbc:TaxAmount currencyID="{currency}">{_amount(tax)}</cbc:TaxAmount>
      <cbc:Percent>{vat}</cbc:Percent>
      <cac:TaxCategory><cac:TaxScheme><cbc:Name>KDV</cbc:Name>
        <cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>
    </cac:TaxSubtotal>
  </cac:TaxTotal>
  <cac:Item><cbc:Name>{line["name"]}</cbc:Name>
    <cac:SellersItemIdentification><cbc:ID>SKU-{n}</cbc:ID></cac:SellersItemIdentification>
  </cac:Item>
  <cac:Price><cbc:PriceAmount currencyID="{currency}">{line["price"]}</cbc:PriceAmount></cac:Price>
</cac:InvoiceLine>"""
        )

    discount_total = Decimal(doc_allowance or 0)
    tax_base = net_total - discount_total
    if doc_allowance:
        vat_total = (tax_base * vat_rate / 100).quantize(Decimal("0.01"))
    withheld = Decimal(0)
    withholding_xml = ""
    if withholding:
        code, percent = withholding
        withheld = (vat_total * Decimal(percent) / 100).quantize(Decimal("0.01"))
        withholding_xml = f"""<cac:WithholdingTaxTotal>
  <cbc:TaxAmount currencyID="{currency}">{_amount(withheld)}</cbc:TaxAmount>
  <cac:TaxSubtotal>
    <cbc:TaxableAmount currencyID="{currency}">{_amount(vat_total)}</cbc:TaxableAmount>
    <cbc:TaxAmount currencyID="{currency}">{_amount(withheld)}</cbc:TaxAmount>
    <cbc:Percent>{percent}</cbc:Percent>
    <cac:TaxCategory><cac:TaxScheme><cbc:Name>Yapım işleri</cbc:Name>
      <cbc:TaxTypeCode>{code}</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>
  </cac:TaxSubtotal>
</cac:WithholdingTaxTotal>"""
    exemption_xml = (
        f"<cbc:TaxExemptionReasonCode>{exemption[0]}</cbc:TaxExemptionReasonCode>"
        f"<cbc:TaxExemptionReason>{exemption[1]}</cbc:TaxExemptionReason>"
        if exemption
        else ""
    )
    t = {
        "LineExtensionAmount": net_total,
        "TaxExclusiveAmount": tax_base,
        "TaxInclusiveAmount": tax_base + vat_total,
        "AllowanceTotalAmount": discount_total if doc_allowance else None,
        "PayableAmount": tax_base + vat_total - withheld,
    }
    t.update(totals or {})
    totals_xml = "".join(
        f'<cbc:{k} currencyID="{currency}">{_amount(v)}</cbc:{k}>'
        for k, v in t.items()
        if v is not None
    )
    doc_allowance_xml = (
        f"""<cac:AllowanceCharge><cbc:ChargeIndicator>false</cbc:ChargeIndicator>
        <cbc:AllowanceChargeReason>Kampanya</cbc:AllowanceChargeReason>
        <cbc:Amount currencyID="{currency}">{doc_allowance}</cbc:Amount></cac:AllowanceCharge>"""
        if doc_allowance
        else ""
    )
    rate_xml = (
        f"""<cac:PricingExchangeRate><cbc:SourceCurrencyCode>{currency}</cbc:SourceCurrencyCode>
        <cbc:TargetCurrencyCode>TRY</cbc:TargetCurrencyCode>
        <cbc:CalculationRate>{rate}</cbc:CalculationRate></cac:PricingExchangeRate>"""
        if rate
        else ""
    )
    customer_name = (
        "<cac:Person><cbc:FirstName>Ayşe</cbc:FirstName><cbc:FamilyName>Örnek</cbc:FamilyName>"
        "</cac:Person>"
        if customer_scheme == "TCKN"
        else "<cac:PartyName><cbc:Name>Deneme Alıcı Ltd. Şti.</cbc:Name></cac:PartyName>"
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
  xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
  xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
  xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<cbc:UBLVersionID>2.1</cbc:UBLVersionID>
<cbc:CustomizationID>TR1.2</cbc:CustomizationID>
<cbc:ProfileID>{profile}</cbc:ProfileID>
<cbc:ID>{number}</cbc:ID>
<cbc:CopyIndicator>false</cbc:CopyIndicator>
<cbc:UUID>{uuid}</cbc:UUID>
<cbc:IssueDate>{issue_date}</cbc:IssueDate>
<cbc:IssueTime>10:30:00</cbc:IssueTime>
<cbc:InvoiceTypeCode>{type_code}</cbc:InvoiceTypeCode>
<cbc:Note>Deneme faturası</cbc:Note>
<cbc:DocumentCurrencyCode>{currency}</cbc:DocumentCurrencyCode>
<cbc:LineCountNumeric>{len(lines)}</cbc:LineCountNumeric>
{extra}
<cac:AccountingSupplierParty><cac:Party>
  <cbc:WebsiteURI>https://satici.example</cbc:WebsiteURI>
  <cac:PartyIdentification><cbc:ID schemeID="VKN">{SELLER_VKN}</cbc:ID></cac:PartyIdentification>
  <cac:PartyIdentification>
    <cbc:ID schemeID="MERSISNO">0987654321700015</cbc:ID></cac:PartyIdentification>
  <cac:PartyName><cbc:Name>Deneme Satıcı A.Ş.</cbc:Name></cac:PartyName>
  <cac:PostalAddress>
    <cbc:StreetName>Örnek Cad.</cbc:StreetName><cbc:BuildingNumber>7</cbc:BuildingNumber>
    <cbc:District>Caferağa Mah.</cbc:District>
    <cbc:CitySubdivisionName>Kadıköy</cbc:CitySubdivisionName><cbc:CityName>İstanbul</cbc:CityName>
    <cbc:PostalZone>34710</cbc:PostalZone><cac:Country><cbc:Name>Türkiye</cbc:Name></cac:Country>
  </cac:PostalAddress>
  <cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>Kadıköy</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>
  <cac:Contact><cbc:Telephone>0216 000 00 00</cbc:Telephone>
    <cbc:ElectronicMail>fatura@satici.example</cbc:ElectronicMail></cac:Contact>
</cac:Party></cac:AccountingSupplierParty>
<cac:AccountingCustomerParty><cac:Party>
  <cac:PartyIdentification>
    <cbc:ID schemeID="{customer_scheme}">{customer_id}</cbc:ID></cac:PartyIdentification>
  {customer_name}
  <cac:PostalAddress><cbc:CitySubdivisionName>Çankaya</cbc:CitySubdivisionName>
    <cbc:CityName>Ankara</cbc:CityName><cac:Country><cbc:Name>Türkiye</cbc:Name></cac:Country>
  </cac:PostalAddress>
  <cac:PartyTaxScheme><cac:TaxScheme><cbc:Name>Çankaya</cbc:Name></cac:TaxScheme></cac:PartyTaxScheme>
</cac:Party></cac:AccountingCustomerParty>
<cac:PaymentMeans><cbc:PaymentMeansCode>42</cbc:PaymentMeansCode>
  <cbc:PaymentDueDate>2024-04-13</cbc:PaymentDueDate>
  <cac:PayeeFinancialAccount><cbc:ID>TR330006100519786457841326</cbc:ID>
    <cbc:CurrencyCode>TRY</cbc:CurrencyCode></cac:PayeeFinancialAccount>
</cac:PaymentMeans>
{rate_xml}
{doc_allowance_xml}
<cac:TaxTotal>
  <cbc:TaxAmount currencyID="{currency}">{_amount(vat_total - withheld)}</cbc:TaxAmount>
  <cac:TaxSubtotal>
    <cbc:TaxableAmount currencyID="{currency}">{_amount(tax_base)}</cbc:TaxableAmount>
    <cbc:TaxAmount currencyID="{currency}">{_amount(vat_total)}</cbc:TaxAmount>
    <cbc:Percent>{vat}</cbc:Percent>
    <cac:TaxCategory>{exemption_xml}<cac:TaxScheme><cbc:Name>KDV</cbc:Name>
      <cbc:TaxTypeCode>0015</cbc:TaxTypeCode></cac:TaxScheme></cac:TaxCategory>
  </cac:TaxSubtotal>
</cac:TaxTotal>
{withholding_xml}
<cac:LegalMonetaryTotal>{totals_xml}</cac:LegalMonetaryTotal>
{"".join(line_xml)}
</Invoice>
"""


@pytest.fixture
def gib() -> Path:
    return GIB
