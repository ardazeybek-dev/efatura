"""Turn a UBL-TR ``Invoice`` element into the typed model."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal, InvalidOperation

from .errors import InvoiceError
from .model import (
    Address,
    AllowanceCharge,
    Attachment,
    DocumentReference,
    Invoice,
    Line,
    Party,
    Payment,
    Tax,
    Totals,
)
from .names import tax_name

INVOICE_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}
INVOICE_TAG = f"{{{INVOICE_NS}}}Invoice"

_THOUSANDS = re.compile(r"\d{1,3}(,\d{3})+(\.\d+)?")


def _text(el: ET.Element | None, path: str | None = None) -> str | None:
    if el is not None and path is not None:
        el = el.find(path, NS)
    if el is None or el.text is None:
        return None
    value = el.text.strip()
    return value or None


def _texts(el: ET.Element, path: str) -> tuple[str, ...]:
    return tuple(t for t in (_text(e) for e in el.findall(path, NS)) if t)


def _decimal(el: ET.Element | None, path: str | None = None) -> Decimal | None:
    raw = _text(el, path)
    if raw is None:
        return None
    value = raw.replace(" ", "")
    if "," in value and ("." in value or _THOUSANDS.fullmatch(value)):
        value = value.replace(",", "")  # 1,234.56 is allowed by the GIB schematron
    else:
        value = value.replace(",", ".")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise InvoiceError(f"{path or 'amount'}: {raw!r} is not a number") from None
    if not number.is_finite():
        raise InvoiceError(f"{path or 'amount'}: {raw!r} is not a number")
    return number


def _required(el: ET.Element, path: str) -> Decimal:
    value = _decimal(el, path)
    if value is None:
        raise InvoiceError(f"{path.replace('cbc:', '').replace('cac:', '')} is missing")
    return value


def _date(el: ET.Element | None, path: str) -> date | None:
    raw = _text(el, path)
    if raw is None:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        raise InvoiceError(f"{path}: {raw!r} is not a date") from None


def _address(el: ET.Element | None) -> Address:
    if el is None:
        return Address()
    return Address(
        street=_text(el, "cbc:StreetName"),
        building_number=_text(el, "cbc:BuildingNumber"),
        district=_text(el, "cbc:District"),
        subdivision=_text(el, "cbc:CitySubdivisionName"),
        city=_text(el, "cbc:CityName"),
        postal_zone=_text(el, "cbc:PostalZone"),
        country=_text(el, "cac:Country/cbc:Name"),
    )


def _party(el: ET.Element | None) -> Party | None:
    if el is None:
        return None
    identifiers: dict[str, str] = {}
    for id_el in el.findall("cac:PartyIdentification/cbc:ID", NS):
        value = _text(id_el)
        if value:
            identifiers.setdefault((id_el.get("schemeID") or "").strip().upper(), value)
    name = _text(el, "cac:PartyName/cbc:Name")
    if name is None:
        person = el.find("cac:Person", NS)
        if person is not None:
            parts = [_text(person, f"cbc:{p}") for p in ("FirstName", "MiddleName", "FamilyName")]
            name = " ".join(p for p in parts if p) or None
    return Party(
        name=" ".join(name.split()) if name else None,
        vkn=identifiers.get("VKN"),
        tckn=identifiers.get("TCKN"),
        tax_office=_text(el, "cac:PartyTaxScheme/cac:TaxScheme/cbc:Name"),
        address=_address(el.find("cac:PostalAddress", NS)),
        email=_text(el, "cac:Contact/cbc:ElectronicMail"),
        phone=_text(el, "cac:Contact/cbc:Telephone"),
        website=_text(el, "cbc:WebsiteURI"),
        identifiers=identifiers,
    )


def _taxes(el: ET.Element, container: str, withholding: bool) -> tuple[Decimal | None, tuple]:
    """Sum of ``container/TaxAmount`` and every ``TaxSubtotal`` below it."""
    total: Decimal | None = None
    subtotals: list[Tax] = []
    for block in el.findall(container, NS):
        amount = _decimal(block, "cbc:TaxAmount")
        if amount is not None:
            total = (total or Decimal(0)) + amount
        for sub in block.findall("cac:TaxSubtotal", NS):
            category = sub.find("cac:TaxCategory", NS)
            code = _text(category, "cac:TaxScheme/cbc:TaxTypeCode")
            name = _text(category, "cac:TaxScheme/cbc:Name")
            subtotals.append(
                Tax(
                    code=code,
                    amount=_decimal(sub, "cbc:TaxAmount") or Decimal(0),
                    taxable_amount=_decimal(sub, "cbc:TaxableAmount"),
                    percent=_decimal(sub, "cbc:Percent"),
                    name=name or (None if withholding else tax_name(code)),
                    exemption_code=_text(category, "cbc:TaxExemptionReasonCode"),
                    exemption_reason=_text(category, "cbc:TaxExemptionReason"),
                    per_unit_amount=_decimal(sub, "cbc:PerUnitAmount"),
                )
            )
    return total, tuple(subtotals)


def _allowances(el: ET.Element) -> tuple[AllowanceCharge, ...]:
    out = []
    for ac in el.findall("cac:AllowanceCharge", NS):
        out.append(
            AllowanceCharge(
                is_charge=(_text(ac, "cbc:ChargeIndicator") or "").lower() == "true",
                amount=_decimal(ac, "cbc:Amount") or Decimal(0),
                base_amount=_decimal(ac, "cbc:BaseAmount"),
                rate=_decimal(ac, "cbc:MultiplierFactorNumeric"),
                reason=_text(ac, "cbc:AllowanceChargeReason"),
            )
        )
    return tuple(out)


def _line(el: ET.Element) -> Line:
    quantity_el = el.find("cbc:InvoicedQuantity", NS)
    tax_amount, taxes = _taxes(el, "cac:TaxTotal", withholding=False)
    _, withholdings = _taxes(el, "cac:WithholdingTaxTotal", withholding=True)
    item = el.find("cac:Item", NS)
    return Line(
        id=_text(el, "cbc:ID") or "",
        name=_text(item, "cbc:Name"),
        quantity=_decimal(quantity_el),
        unit_code=(quantity_el.get("unitCode") or None) if quantity_el is not None else None,
        unit_price=_decimal(el, "cac:Price/cbc:PriceAmount"),
        amount=_required(el, "cbc:LineExtensionAmount"),
        allowances=_allowances(el),
        taxes=taxes,
        withholdings=withholdings,
        tax_amount=tax_amount,
        description=_text(item, "cbc:Description"),
        seller_item_id=_text(item, "cac:SellersItemIdentification/cbc:ID"),
        buyer_item_id=_text(item, "cac:BuyersItemIdentification/cbc:ID"),
        notes=_texts(el, "cbc:Note"),
    )


def _reference(el: ET.Element | None) -> DocumentReference | None:
    if el is None:
        return None
    ref_id = _text(el, "cbc:ID")
    if ref_id is None:
        return None
    return DocumentReference(
        id=ref_id,
        issue_date=_date(el, "cbc:IssueDate"),
        document_type=_text(el, "cbc:DocumentTypeCode") or _text(el, "cbc:DocumentType"),
    )


def _references(el: ET.Element, path: str) -> tuple[DocumentReference, ...]:
    refs = (_reference(r) for r in el.findall(path, NS))
    return tuple(r for r in refs if r is not None)


def _payments(el: ET.Element) -> tuple[Payment, ...]:
    out = []
    for pm in el.findall("cac:PaymentMeans", NS):
        account = pm.find("cac:PayeeFinancialAccount", NS)
        out.append(
            Payment(
                means_code=_text(pm, "cbc:PaymentMeansCode"),
                due_date=_date(pm, "cbc:PaymentDueDate"),
                account=_text(account, "cbc:ID"),
                account_currency=_text(account, "cbc:CurrencyCode"),
                bank=_text(
                    account, "cac:FinancialInstitutionBranch/cac:FinancialInstitution/cbc:Name"
                ),
                branch=_text(account, "cac:FinancialInstitutionBranch/cbc:Name"),
                note=_text(account, "cbc:PaymentNote"),
            )
        )
    return tuple(out)


def _attachments(el: ET.Element) -> tuple[Attachment, ...]:
    out = []
    for ref in el.findall("cac:AdditionalDocumentReference", NS):
        obj = ref.find("cac:Attachment/cbc:EmbeddedDocumentBinaryObject", NS)
        if obj is None or not (obj.text or "").strip():
            continue
        out.append(
            Attachment(
                id=_text(ref, "cbc:ID"),
                filename=obj.get("filename"),
                mime_type=obj.get("mimeCode"),
                document_type=_text(ref, "cbc:DocumentType"),
                data_base64="".join(obj.text.split()),
            )
        )
    return tuple(out)


def parse_invoice(el: ET.Element, source: str | None = None) -> Invoice:
    """Build an :class:`Invoice` from a parsed ``<Invoice>`` element."""
    if el.tag != INVOICE_TAG:
        raise InvoiceError(f"expected a UBL Invoice element, got {el.tag}")
    try:
        return _parse(el, source)
    except InvoiceError as exc:
        where = _text(el, "cbc:ID") or source
        raise InvoiceError(f"{where}: {exc}" if where else str(exc)) from None


def _parse(el: ET.Element, source: str | None) -> Invoice:
    monetary = el.find("cac:LegalMonetaryTotal", NS)
    if monetary is None:
        raise InvoiceError("LegalMonetaryTotal is missing")
    tax_total, taxes = _taxes(el, "cac:TaxTotal", withholding=False)
    withholding_total, withholdings = _taxes(el, "cac:WithholdingTaxTotal", withholding=True)
    line_count = _decimal(el, "cbc:LineCountNumeric")
    copy = _text(el, "cbc:CopyIndicator")
    supplier = _party(el.find("cac:AccountingSupplierParty/cac:Party", NS)) or Party()
    customer = _party(el.find("cac:AccountingCustomerParty/cac:Party", NS)) or Party()
    return Invoice(
        number=_text(el, "cbc:ID"),
        uuid=_text(el, "cbc:UUID"),
        issue_date=_date(el, "cbc:IssueDate"),
        issue_time=_text(el, "cbc:IssueTime"),
        profile=_text(el, "cbc:ProfileID"),
        type=_text(el, "cbc:InvoiceTypeCode"),
        currency=_text(el, "cbc:DocumentCurrencyCode") or "TRY",
        exchange_rate=_decimal(el, "cac:PricingExchangeRate/cbc:CalculationRate"),
        supplier=supplier,
        customer=customer,
        buyer=_party(el.find("cac:BuyerCustomerParty/cac:Party", NS)),
        lines=tuple(_line(line) for line in el.findall("cac:InvoiceLine", NS)),
        tax_total=tax_total,
        taxes=taxes,
        withholding_total=withholding_total,
        withholdings=withholdings,
        totals=Totals(
            line_extension=_required(monetary, "cbc:LineExtensionAmount"),
            tax_exclusive=_required(monetary, "cbc:TaxExclusiveAmount"),
            tax_inclusive=_required(monetary, "cbc:TaxInclusiveAmount"),
            payable=_required(monetary, "cbc:PayableAmount"),
            allowance_total=_decimal(monetary, "cbc:AllowanceTotalAmount"),
            charge_total=_decimal(monetary, "cbc:ChargeTotalAmount"),
            prepaid=_decimal(monetary, "cbc:PrepaidAmount"),
            payable_rounding=_decimal(monetary, "cbc:PayableRoundingAmount"),
        ),
        allowances=_allowances(el),
        notes=_texts(el, "cbc:Note"),
        billing_references=_references(el, "cac:BillingReference/cac:InvoiceDocumentReference"),
        despatch_references=_references(el, "cac:DespatchDocumentReference"),
        order_reference=_reference(el.find("cac:OrderReference", NS)),
        payments=_payments(el),
        payment_terms=_text(el, "cac:PaymentTerms/cbc:Note"),
        attachments=_attachments(el),
        customization_id=_text(el, "cbc:CustomizationID"),
        copy_indicator=None if copy is None else copy.lower() == "true",
        line_count=int(line_count) if line_count is not None else None,
        source=source,
    )
