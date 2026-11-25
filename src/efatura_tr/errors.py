"""Exceptions raised while reading invoices."""


class InvoiceError(ValueError):
    """The input is not a readable UBL-TR invoice (bad XML, missing totals...)."""


class UnsafeXMLError(InvoiceError):
    """The XML declares a DOCTYPE. Invoices never need one, and it enables entity attacks."""
