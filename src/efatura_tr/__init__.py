"""Read Turkish e-Fatura / e-Arşiv (UBL-TR 1.2) invoices.

>>> import efatura_tr
>>> inv = efatura_tr.read("tests/fixtures/gib/TEVKIFAT.xml")  # doctest: +SKIP
>>> inv.number, inv.totals.payable                             # doctest: +SKIP
('SRM2012000086985', Decimal('20360'))
"""

from .check import ERROR, WARNING, Issue, check
from .errors import InvoiceError, UnsafeXMLError
from .ids import is_valid_tckn, is_valid_vkn
from .model import (
    VAT,
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
from .names import tax_name, unit_name
from .reader import iter_invoices, parse_xml, read, read_all

__version__ = "0.1.0"

__all__ = [
    "ERROR",
    "VAT",
    "WARNING",
    "Address",
    "AllowanceCharge",
    "Attachment",
    "DocumentReference",
    "Invoice",
    "InvoiceError",
    "Issue",
    "Line",
    "Party",
    "Payment",
    "Tax",
    "Totals",
    "UnsafeXMLError",
    "check",
    "is_valid_tckn",
    "is_valid_vkn",
    "iter_invoices",
    "parse_xml",
    "read",
    "read_all",
    "tax_name",
    "unit_name",
]
