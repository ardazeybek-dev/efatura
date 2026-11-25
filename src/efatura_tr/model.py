"""The typed invoice model. Every amount is a :class:`~decimal.Decimal`."""

from __future__ import annotations

import base64
import dataclasses
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from .names import unit_name

VAT = "0015"
"""Tax type code of KDV (katma değer vergisi)."""


@dataclass(frozen=True)
class Address:
    street: str | None = None
    building_number: str | None = None
    district: str | None = None
    """Mahalle / semt (``cbc:District``)."""
    subdivision: str | None = None
    """İlçe (``cbc:CitySubdivisionName``)."""
    city: str | None = None
    """İl (``cbc:CityName``)."""
    postal_zone: str | None = None
    country: str | None = None

    def __str__(self) -> str:
        street = " ".join(p for p in (self.district, self.street, self.building_number) if p)
        town = "/".join(p for p in (self.subdivision, self.city) if p)
        return ", ".join(p for p in (street, self.postal_zone, town, self.country) if p)


@dataclass(frozen=True)
class Party:
    """A seller, buyer or other party on the invoice."""

    name: str | None = None
    """Trade name (``PartyName``) or, for people, first and family name."""
    vkn: str | None = None
    """Vergi kimlik numarası (10 digits), when the party is identified by one."""
    tckn: str | None = None
    """T.C. kimlik numarası (11 digits), when the party is a person."""
    tax_office: str | None = None
    """Vergi dairesi (``PartyTaxScheme/TaxScheme/Name``)."""
    address: Address = field(default_factory=Address)
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    identifiers: dict[str, str] = field(default_factory=dict)
    """Every ``PartyIdentification/ID`` by ``schemeID`` (MERSISNO, TICARETSICILNO, ...)."""

    @property
    def tax_id(self) -> str | None:
        """VKN or TCKN, whichever the party has."""
        return self.vkn or self.tckn


@dataclass(frozen=True)
class Tax:
    """One ``TaxSubtotal``: a tax (or a withholding) at one rate."""

    code: str | None
    """GIB tax type code: ``0015`` for KDV, ``0071`` for ÖTV, ``606`` for a tevkifat type..."""
    amount: Decimal
    taxable_amount: Decimal | None = None
    percent: Decimal | None = None
    name: str | None = None
    """The name written in the invoice, else the usual name of ``code``."""
    exemption_code: str | None = None
    """Vergi istisna/muafiyet sebebi kodu (``TaxExemptionReasonCode``)."""
    exemption_reason: str | None = None
    per_unit_amount: Decimal | None = None


@dataclass(frozen=True)
class AllowanceCharge:
    """An iskonto (``is_charge`` false) or an ek ücret (``is_charge`` true)."""

    is_charge: bool
    amount: Decimal
    base_amount: Decimal | None = None
    rate: Decimal | None = None
    """``MultiplierFactorNumeric`` as written: GIB samples use both 0.1 and 10 for 10%."""
    reason: str | None = None


@dataclass(frozen=True)
class Line:
    id: str
    name: str | None
    quantity: Decimal | None
    unit_code: str | None
    unit_price: Decimal | None
    amount: Decimal
    """``LineExtensionAmount``: the line total after line discounts, before tax."""
    allowances: tuple[AllowanceCharge, ...] = ()
    taxes: tuple[Tax, ...] = ()
    withholdings: tuple[Tax, ...] = ()
    tax_amount: Decimal | None = None
    """The line's own ``TaxTotal/TaxAmount``, when the invoice has one."""
    description: str | None = None
    seller_item_id: str | None = None
    buyer_item_id: str | None = None
    notes: tuple[str, ...] = ()

    @property
    def unit_name(self) -> str | None:
        """Turkish name of ``unit_code`` (``C62`` -> ``Adet``), if it is a common unit."""
        return unit_name(self.unit_code)

    @property
    def vat_rate(self) -> Decimal | None:
        for tax in self.taxes:
            if tax.code == VAT:
                return tax.percent
        return None

    @property
    def vat_amount(self) -> Decimal | None:
        found = [t.amount for t in self.taxes if t.code == VAT]
        return sum(found, Decimal(0)) if found else None


@dataclass(frozen=True)
class Totals:
    """``LegalMonetaryTotal``."""

    line_extension: Decimal
    """Sum of the line amounts."""
    tax_exclusive: Decimal
    """Matrah: after invoice-level discounts and charges, before tax."""
    tax_inclusive: Decimal
    """Matrah plus every tax."""
    payable: Decimal
    """Ödenecek tutar: after tevkifat and prepayments."""
    allowance_total: Decimal | None = None
    charge_total: Decimal | None = None
    prepaid: Decimal | None = None
    payable_rounding: Decimal | None = None


@dataclass(frozen=True)
class DocumentReference:
    id: str
    issue_date: date | None = None
    document_type: str | None = None


@dataclass(frozen=True)
class Payment:
    """``PaymentMeans``."""

    means_code: str | None = None
    due_date: date | None = None
    account: str | None = None
    """Payee account, usually an IBAN."""
    account_currency: str | None = None
    bank: str | None = None
    branch: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Attachment:
    """An ``AdditionalDocumentReference`` that carries an embedded file (XSLT, PDF...)."""

    id: str | None
    filename: str | None
    mime_type: str | None
    document_type: str | None
    data_base64: str = field(repr=False)

    @property
    def data(self) -> bytes:
        return base64.b64decode(self.data_base64)

    @property
    def is_xslt(self) -> bool:
        return (self.document_type or "").upper() == "XSLT" or (
            self.filename or ""
        ).lower().endswith((".xslt", ".xsl"))


@dataclass(frozen=True)
class Invoice:
    number: str | None
    """Fatura numarası (``cbc:ID``), e.g. ``ABC2024000000001``."""
    uuid: str | None
    """ETTN (``cbc:UUID``)."""
    issue_date: date | None
    issue_time: str | None
    profile: str | None
    """``ProfileID``: TEMELFATURA, TICARIFATURA, EARSIVFATURA, IHRACAT, ..."""
    type: str | None
    """``InvoiceTypeCode``: SATIS, IADE, TEVKIFAT, ISTISNA, ..."""
    currency: str
    exchange_rate: Decimal | None
    """``PricingExchangeRate/CalculationRate`` for invoices not in TRY."""
    supplier: Party
    customer: Party
    buyer: Party | None
    """``BuyerCustomerParty``: the real buyer on export and tax-free invoices."""
    lines: tuple[Line, ...]
    tax_total: Decimal | None
    """``TaxTotal/TaxAmount`` as written.

    On tevkifat invoices this is the KDV left after withholding."""
    taxes: tuple[Tax, ...]
    withholding_total: Decimal | None
    withholdings: tuple[Tax, ...]
    totals: Totals
    allowances: tuple[AllowanceCharge, ...] = ()
    notes: tuple[str, ...] = ()
    billing_references: tuple[DocumentReference, ...] = ()
    """The invoices an IADE (return) invoice refers to."""
    despatch_references: tuple[DocumentReference, ...] = ()
    order_reference: DocumentReference | None = None
    payments: tuple[Payment, ...] = ()
    payment_terms: str | None = None
    attachments: tuple[Attachment, ...] = ()
    customization_id: str | None = None
    copy_indicator: bool | None = None
    line_count: int | None = None
    """``LineCountNumeric`` as written; compare with ``len(lines)``."""
    source: str | None = None
    """Where the invoice was read from: a path, or ``archive.zip!member.xml``."""

    @property
    def is_earchive(self) -> bool:
        return self.profile == "EARSIVFATURA"

    @property
    def vat_total(self) -> Decimal:
        """Total KDV before withholding."""
        return sum((t.amount for t in self.taxes if t.code == VAT), Decimal(0))

    @property
    def vat_breakdown(self) -> dict[Decimal, tuple[Decimal, Decimal]]:
        """KDV by rate: ``{20: (matrah, kdv), 10: (...)}``, highest rate first."""
        out: dict[Decimal, tuple[Decimal, Decimal]] = {}
        for t in self.taxes:
            if t.code != VAT:
                continue
            rate = (t.percent if t.percent is not None else Decimal(0)).normalize()
            base, amount = out.get(rate, (Decimal(0), Decimal(0)))
            out[rate] = (base + (t.taxable_amount or Decimal(0)), amount + t.amount)
        return dict(sorted(out.items(), reverse=True))

    @property
    def allowances_affect_base(self) -> bool:
        """True if an invoice-level discount or charge changes the tax base."""
        return any(
            a.amount and not (a.reason or "").upper().startswith("HKS") for a in self.allowances
        )

    @property
    def xslt(self) -> Attachment | None:
        """The embedded XSLT that renders the invoice, if there is one."""
        return next((a for a in self.attachments if a.is_xslt), None)

    def check(self) -> list:
        """Run every check, see :func:`efatura_tr.check`."""
        from .check import check

        return check(self)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready dict: amounts become strings, dates ISO strings, attachments are omitted."""
        return _plain(self)


def _plain(value: Any) -> Any:
    if isinstance(value, Attachment):
        return {
            "id": value.id,
            "filename": value.filename,
            "mime_type": value.mime_type,
            "document_type": value.document_type,
            "size": len(value.data_base64) * 3 // 4,
        }
    if dataclasses.is_dataclass(value):
        out = {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
        if isinstance(value, Line):
            out["unit_name"] = value.unit_name
        return out
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value
