"""Checks that catch the mistakes people actually ship.

Two kinds of checks:

* **GIB rules** the official schematron enforces (invoice number format, ETTN
  format, VKN/TCKN length, code lists, IADE invoices must reference the
  original invoice). An invoice failing these would be rejected by GIB.
* **Arithmetic** the schematron does *not* check: lines add up to the totals,
  each tax equals base times rate, payable equals total minus tevkifat. These
  are reported as warnings.

Rounding differences of up to one kuruş per line are tolerated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from . import _codelists as codes
from .ids import is_valid_tckn, is_valid_vkn
from .model import VAT, Invoice, Party, Tax

ERROR = "error"
WARNING = "warning"

_NUMBER = re.compile(r"[A-Z0-9]{3}20[0-9]{2}[0-9]{9}")
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_RETURN_TYPES = {"IADE", "TEVKIFATIADE", "YTBIADE", "YTBTEVKIFATIADE"}
_WITHHOLDING_TYPES = {"TEVKIFAT", "TEVKIFATIADE", "YTBTEVKIFAT", "YTBTEVKIFATIADE"}
KURUS = Decimal("0.01")


@dataclass(frozen=True)
class Issue:
    severity: str
    """``"error"``: GIB would reject it. ``"warning"``: worth a look."""
    code: str
    """Stable identifier such as ``totals.payable``, for filtering."""
    message: str

    def __str__(self) -> str:
        return f"{self.severity}: {self.message} [{self.code}]"


def _money(value: Decimal) -> str:
    return f"{value.quantize(KURUS, ROUND_HALF_UP):,}"


def _close(a: Decimal, b: Decimal, tolerance: Decimal = KURUS) -> bool:
    return abs(a - b) <= tolerance


def _sum(values) -> Decimal:
    return sum(values, Decimal(0))


def check(invoice: Invoice) -> list[Issue]:
    """Every problem found in ``invoice``, errors first. An empty list means it looks right."""
    issues: list[Issue] = []
    _check_identity(invoice, issues)
    _check_parties(invoice, issues)
    _check_codes(invoice, issues)
    _check_lines(invoice, issues)
    _check_taxes(invoice, issues)
    _check_totals(invoice, issues)
    return sorted(issues, key=lambda i: i.severity != ERROR)


def _check_identity(inv: Invoice, issues: list[Issue]) -> None:
    def add(severity: str, code: str, message: str) -> None:
        issues.append(Issue(severity, code, message))

    if not inv.number:
        add(ERROR, "number.missing", "invoice number (cbc:ID) is missing")
    elif not _NUMBER.fullmatch(inv.number):
        add(ERROR, "number.format", f"invoice number {inv.number!r} is not like ABC2024000000001")
    elif inv.issue_date and inv.number[3:7] != str(inv.issue_date.year):
        add(
            WARNING,
            "number.year",
            f"invoice number {inv.number} has year {inv.number[3:7]} "
            f"but is dated {inv.issue_date.isoformat()}",
        )
    if not inv.uuid:
        add(ERROR, "uuid.missing", "ETTN (cbc:UUID) is missing")
    elif not _UUID.fullmatch(inv.uuid):
        add(ERROR, "uuid.format", f"ETTN {inv.uuid!r} is not a UUID")
    if inv.issue_date is None:
        add(ERROR, "date.missing", "issue date is missing")
    if inv.type in _RETURN_TYPES and not inv.billing_references:
        add(
            ERROR, "return.reference", f"{inv.type} invoice does not reference the returned invoice"
        )
    if inv.type in _WITHHOLDING_TYPES and inv.type not in _RETURN_TYPES and not inv.withholdings:
        add(WARNING, "withholding.missing", f"{inv.type} invoice has no WithholdingTaxTotal")
    if inv.currency != "TRY" and inv.exchange_rate is None:
        add(WARNING, "currency.rate", f"invoice is in {inv.currency} but has no exchange rate")
    if inv.line_count is not None and inv.line_count != len(inv.lines):
        add(
            WARNING,
            "lines.count",
            f"LineCountNumeric says {inv.line_count} but there are {len(inv.lines)} lines",
        )
    if not inv.lines:
        add(ERROR, "lines.missing", "invoice has no lines")


def _check_party(role: str, party: Party, issues: list[Issue]) -> None:
    if party.vkn is None and party.tckn is None:
        issues.append(Issue(ERROR, f"{role}.id", f"{role} has no VKN or TCKN"))
    if party.vkn is not None:
        if len(party.vkn) != 10 or not party.vkn.isdigit():
            issues.append(Issue(ERROR, f"{role}.vkn", f"{role} VKN {party.vkn!r} is not 10 digits"))
        elif not is_valid_vkn(party.vkn):
            issues.append(
                Issue(WARNING, f"{role}.vkn", f"{role} VKN {party.vkn} fails the checksum")
            )
    if party.tckn is not None:
        if len(party.tckn) != 11 or not party.tckn.isdigit():
            issues.append(
                Issue(ERROR, f"{role}.tckn", f"{role} TCKN {party.tckn!r} is not 11 digits")
            )
        elif not is_valid_tckn(party.tckn) and party.tckn != "11111111111":
            # 11111111111 is GIB's placeholder for a final consumer without an ID.
            issues.append(
                Issue(WARNING, f"{role}.tckn", f"{role} TCKN {party.tckn} fails the checksum")
            )
    if party.name is None:
        issues.append(Issue(WARNING, f"{role}.name", f"{role} has no name"))


def _check_parties(inv: Invoice, issues: list[Issue]) -> None:
    _check_party("supplier", inv.supplier, issues)
    _check_party("customer", inv.customer, issues)


def _check_codes(inv: Invoice, issues: list[Issue]) -> None:
    def unknown(code: str, what: str, value: str | None, allowed: frozenset[str]) -> None:
        if value is not None and value not in allowed:
            issues.append(Issue(WARNING, code, f"{what} {value!r} is not in the GIB code list"))

    unknown(
        "code.profile",
        "ProfileID",
        inv.profile,
        codes.PROFILE_IDS | codes.PROFILE_IDS_EARCHIVE,
    )
    unknown("code.type", "InvoiceTypeCode", inv.type, codes.INVOICE_TYPE_CODES)
    unknown("code.currency", "currency", inv.currency, codes.CURRENCY_CODES)
    taxes = list(inv.taxes) + [t for line in inv.lines for t in line.taxes]
    withholdings = list(inv.withholdings) + [t for line in inv.lines for t in line.withholdings]
    for code in sorted({t.code for t in taxes if t.code}):
        unknown("code.tax", "tax type", code, codes.TAX_TYPE_CODES)
    for code in sorted({t.code for t in withholdings if t.code}):
        unknown("code.withholding", "withholding type", code, codes.WITHHOLDING_TAX_TYPE_CODES)
    exemptions = (
        codes.TAX_EXEMPTION_REASON_CODES
        | codes.TAX_EXEMPTION_REASON_CODES_YATIRIM_TESVIK
        | codes.TAX_EXEMPTION_REASON_CODES_ISTISNA
        | codes.TAX_EXEMPTION_REASON_CODES_OZEL_MATRAH
        | codes.TAX_EXEMPTION_REASON_CODES_IHRAC
    )
    for code in sorted({t.exemption_code for t in taxes if t.exemption_code}):
        unknown("code.exemption", "exemption reason", code, exemptions)
    for code in sorted({line.unit_code for line in inv.lines if line.unit_code}):
        unknown("code.unit", "unit", code, codes.UNIT_CODES)


def _check_lines(inv: Invoice, issues: list[Issue]) -> None:
    for line in inv.lines:
        if line.quantity is None or line.unit_price is None:
            continue
        discounts = _sum(a.amount for a in line.allowances if not a.is_charge)
        charges = _sum(a.amount for a in line.allowances if a.is_charge)
        expected = line.quantity * line.unit_price - discounts + charges
        if not _close(expected, line.amount):
            issues.append(
                Issue(
                    WARNING,
                    "line.amount",
                    f"line {line.id}: {line.quantity} x {line.unit_price}"
                    + (f" - {discounts} discount" if discounts else "")
                    + (f" + {charges} charge" if charges else "")
                    + f" = {_money(expected)}, but the line says {_money(line.amount)}",
                )
            )
        _check_tax_math(f"line {line.id}", line.taxes, issues)


def _check_tax_math(where: str, taxes: tuple[Tax, ...], issues: list[Issue]) -> None:
    for tax in taxes:
        if tax.taxable_amount is None or tax.percent is None or tax.per_unit_amount is not None:
            continue
        expected = tax.taxable_amount * tax.percent / 100
        if not _close(expected, tax.amount):
            label = tax.name or tax.code or "tax"
            issues.append(
                Issue(
                    WARNING,
                    "tax.amount",
                    f"{where}: {label} {tax.percent}% of {_money(tax.taxable_amount)} "
                    f"is {_money(expected)}, but the invoice says {_money(tax.amount)}",
                )
            )


def _check_taxes(inv: Invoice, issues: list[Issue]) -> None:
    _check_tax_math("invoice", inv.taxes, issues)
    for tax in inv.withholdings:
        if tax.taxable_amount is None or tax.percent is None:
            continue
        expected = tax.taxable_amount * tax.percent / 100
        if not _close(expected, tax.amount):
            issues.append(
                Issue(
                    WARNING,
                    "withholding.amount",
                    f"tevkifat {tax.code}: {tax.percent}% of {_money(tax.taxable_amount)} "
                    f"is {_money(expected)}, but the invoice says {_money(tax.amount)}",
                )
            )

    tolerance = KURUS * max(1, len(inv.lines))
    gross = _sum(t.amount for t in inv.taxes)
    charged = _charged(inv)
    withheld = inv.withholding_total or Decimal(0)
    if inv.tax_total is not None and not any(
        _close(inv.tax_total, c, tolerance)
        for c in (gross, gross - withheld, charged, charged - withheld)
    ):
        issues.append(
            Issue(
                WARNING,
                "tax.total",
                f"TaxTotal says {_money(inv.tax_total)} "
                f"but its subtotals add up to {_money(gross)}",
            )
        )
    if inv.withholding_total is not None:
        listed = _sum(t.amount for t in inv.withholdings)
        if inv.withholdings and not _close(inv.withholding_total, listed, tolerance):
            issues.append(
                Issue(
                    WARNING,
                    "withholding.total",
                    f"WithholdingTaxTotal says {_money(inv.withholding_total)} "
                    f"but its subtotals add up to {_money(listed)}",
                )
            )

    # Line taxes, where the invoice has them, must add up to the invoice taxes,
    # unless an invoice-level discount or charge moved the tax base.
    if any(line.taxes for line in inv.lines) and not inv.allowances_affect_base:
        by_code: dict[str | None, Decimal] = {}
        for line in inv.lines:
            for tax in line.taxes:
                by_code[tax.code] = by_code.get(tax.code, Decimal(0)) + tax.amount
        for code, line_total in sorted(by_code.items(), key=lambda kv: kv[0] or ""):
            doc_total = _sum(t.amount for t in inv.taxes if t.code == code)
            if not _close(line_total, doc_total, tolerance):
                label = next((t.name for t in inv.taxes if t.code == code and t.name), code)
                issues.append(
                    Issue(
                        WARNING,
                        "tax.lines",
                        f"{label}: lines add up to {_money(line_total)} "
                        f"but the invoice total is {_money(doc_total)}",
                    )
                )

    for tax in inv.taxes:
        if (
            tax.code == VAT
            and tax.amount == 0
            and not tax.exemption_code
            and inv.type in {"ISTISNA", "IHRACKAYITLI", "YTBISTISNA"}
        ):
            issues.append(
                Issue(
                    ERROR,
                    "exemption.missing",
                    f"{inv.type} invoice has 0 KDV without an exemption reason code",
                )
            )


def _charged(inv: Invoice) -> Decimal:
    """Taxes actually charged: an exempt subtotal (istisna, özel matrah) may show a
    computed amount that is not added to the invoice total."""
    return _sum(t.amount for t in inv.taxes if not t.exemption_code)


def _is_hks_deduction(a) -> bool:
    # HKS komisyoncu invoices list commission, freight, rüsum... as allowances
    # that are taken off the payable amount, not off the tax base.
    return not a.is_charge and (a.reason or "").upper().startswith("HKS")


def _check_totals(inv: Invoice, issues: list[Issue]) -> None:
    t = inv.totals
    tolerance = KURUS * max(1, len(inv.lines))

    def add(code: str, message: str) -> None:
        issues.append(Issue(WARNING, code, message))

    # Two conventions exist, both in GIB's own samples: the invoice-level
    # LineExtensionAmount is either the sum of the (net) line amounts, or the
    # sum before line discounts, with those discounts in AllowanceTotalAmount.
    lines = _sum(line.amount for line in inv.lines)
    line_discounts = _sum(a.amount for ln in inv.lines for a in ln.allowances if not a.is_charge)
    line_charges = _sum(a.amount for ln in inv.lines for a in ln.allowances if a.is_charge)
    before_discounts = lines + line_discounts - line_charges
    if inv.lines and not any(
        _close(c, t.line_extension, tolerance) for c in (lines, before_discounts)
    ):
        add(
            "totals.lines",
            f"lines add up to {_money(lines)} "
            f"but LineExtensionAmount is {_money(t.line_extension)}",
        )

    discounts = _sum(
        a.amount for a in inv.allowances if not a.is_charge and not _is_hks_deduction(a)
    )
    charges = _sum(a.amount for a in inv.allowances if a.is_charge)
    expected = t.line_extension - discounts + charges
    candidates = [expected]
    if t.allowance_total is not None or t.charge_total is not None:
        candidates.append(t.line_extension - (t.allowance_total or 0) + (t.charge_total or 0))
    if not any(_close(c, t.tax_exclusive, tolerance) for c in candidates):
        if discounts or charges:
            how = (
                f"LineExtensionAmount {_money(t.line_extension)}"
                + (f" - discounts {_money(discounts)}" if discounts else "")
                + (f" + charges {_money(charges)}" if charges else "")
                + f" = {_money(expected)}"
            )
        else:
            how = f"LineExtensionAmount is {_money(t.line_extension)} with no invoice discounts"
        add("totals.tax_exclusive", f"{how}, but TaxExclusiveAmount is {_money(t.tax_exclusive)}")

    gross = _sum(tax.amount for tax in inv.taxes)
    candidates = [t.tax_exclusive + gross, t.tax_exclusive + _charged(inv)]
    if inv.tax_total is not None:
        candidates.append(t.tax_exclusive + inv.tax_total)
    if not any(_close(c, t.tax_inclusive, tolerance) for c in candidates):
        add(
            "totals.tax_inclusive",
            f"TaxExclusiveAmount {_money(t.tax_exclusive)} + taxes {_money(gross)} "
            f"= {_money(candidates[0])}, but TaxInclusiveAmount is {_money(t.tax_inclusive)}",
        )

    withheld = inv.withholding_total or Decimal(0)
    payable = t.tax_inclusive - withheld - (t.prepaid or 0) + (t.payable_rounding or 0)
    hks = _sum(a.amount for a in inv.allowances if _is_hks_deduction(a))
    if not any(_close(c, t.payable, tolerance) for c in (payable, payable - hks)):
        parts = f"TaxInclusiveAmount {_money(t.tax_inclusive)}"
        if withheld:
            parts += f" - tevkifat {_money(withheld)}"
        if t.prepaid:
            parts += f" - prepaid {_money(t.prepaid)}"
        if t.payable_rounding:
            parts += f" + rounding {_money(t.payable_rounding)}"
        add(
            "totals.payable",
            f"{parts} = {_money(payable)}, but PayableAmount is {_money(t.payable)}",
        )
