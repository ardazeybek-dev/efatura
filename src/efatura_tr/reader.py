"""Read invoices from files, folders, ZIP archives, bytes or XML text.

The XML is parsed with the standard library. Because invoices arrive from
outside, anything that declares a DOCTYPE is refused before parsing: UBL never
needs one, and entity declarations are how XML bombs and XXE attacks work.
"""

from __future__ import annotations

import io
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO, Union

from .errors import InvoiceError, UnsafeXMLError
from .model import Invoice
from .parse import INVOICE_TAG, parse_invoice

Source = Union[str, "os.PathLike[str]", bytes, IO[bytes]]

MAX_XML_BYTES = 200 * 1024 * 1024
"""Largest XML document read, archive members included (embedded PDFs make invoices big)."""
MAX_ZIP_MEMBERS = 10_000

# Whitespace, XML declaration, processing instructions and comments may come
# before the root element. Anything else starting with "<!" is a DOCTYPE.
_PROLOG = re.compile(rb"\s+|<\?.*?\?>|<!--.*?-->", re.S)
_PROLOG_STR = re.compile(r"\s+|<\?.*?\?>|<!--.*?-->", re.S)


def _reject_doctype(data: bytes) -> None:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16")
        pos = 0
        while m := _PROLOG_STR.match(text, pos):
            pos = m.end()
        if text.startswith("<!", pos):
            raise UnsafeXMLError("the XML declares a DOCTYPE, which invoices never need")
        return
    pos = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    while m := _PROLOG.match(data, pos):
        pos = m.end()
    if data.startswith(b"<!", pos):
        raise UnsafeXMLError("the XML declares a DOCTYPE, which invoices never need")


def parse_xml(data: bytes, source: str | None = None) -> list[Invoice]:
    """Every invoice in one XML document: a bare ``<Invoice>`` or a GIB envelope holding several."""
    if len(data) > MAX_XML_BYTES:
        raise InvoiceError(f"{source or 'XML'} is larger than {MAX_XML_BYTES} bytes")
    _reject_doctype(data)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise InvoiceError(f"{source or 'input'} is not valid XML: {exc}") from None
    elements = [root] if root.tag == INVOICE_TAG else list(root.iter(INVOICE_TAG))
    return [parse_invoice(el, source) for el in elements]


def _read_zip(file: str | IO[bytes], name: str) -> Iterator[Invoice]:
    try:
        archive = zipfile.ZipFile(file)
    except zipfile.BadZipFile:
        raise InvoiceError(f"{name} is not a valid ZIP file") from None
    with archive:
        members = [i for i in archive.infolist() if not i.is_dir()]
        if len(members) > MAX_ZIP_MEMBERS:
            raise InvoiceError(f"{name} has more than {MAX_ZIP_MEMBERS} files")
        for info in sorted(members, key=lambda i: i.filename):
            lower = info.filename.lower()
            label = f"{name}!{info.filename}"
            if lower.endswith(".zip"):
                if info.file_size > MAX_XML_BYTES:
                    raise InvoiceError(f"{label} is larger than {MAX_XML_BYTES} bytes")
                yield from _read_zip(io.BytesIO(archive.read(info)), label)
            elif lower.endswith(".xml"):
                if info.file_size > MAX_XML_BYTES:
                    raise InvoiceError(f"{label} is larger than {MAX_XML_BYTES} bytes")
                with archive.open(info) as fh:
                    data = fh.read(MAX_XML_BYTES + 1)
                yield from parse_xml(data, label)


def _iter_path(path: Path) -> Iterator[Invoice]:
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file() and child.suffix.lower() in (".xml", ".zip"):
                yield from _iter_path(child)
        return
    name = str(path)
    with open(path, "rb") as fh:
        head = fh.read(4)
        fh.seek(0)
        if head.startswith(b"PK\x03\x04"):
            yield from _read_zip(fh, name)
            return
        data = fh.read(MAX_XML_BYTES + 1)
    yield from parse_xml(data, name)


def iter_invoices(source: Source | Iterable[Source]) -> Iterator[Invoice]:
    """Yield every invoice found in ``source``, lazily.

    ``source`` is a path to an ``.xml`` file, a ``.zip`` archive or a folder
    (searched recursively), raw ``bytes``, XML text, a binary file object, or a
    list of any of these.
    """
    if isinstance(source, (list, tuple)):
        for item in source:
            yield from iter_invoices(item)
        return
    if isinstance(source, bytes):
        if source.startswith(b"PK\x03\x04"):
            yield from _read_zip(io.BytesIO(source), "<bytes>")
        else:
            yield from parse_xml(source)
        return
    if isinstance(source, str) and source.lstrip("﻿ \t\r\n").startswith("<"):
        yield from parse_xml(_restate(source))
        return
    if hasattr(source, "read"):
        data = source.read()
        yield from iter_invoices(data if isinstance(data, bytes) else data.encode("utf-8"))
        return
    yield from _iter_path(Path(source))


def _restate(text: str) -> bytes:
    """XML text as UTF-8 bytes, with any encoding declaration restated as UTF-8."""
    text = re.sub(r"^﻿?\s*<\?xml[^>]*\?>", '<?xml version="1.0" encoding="UTF-8"?>', text, count=1)
    return text.encode("utf-8")


def read_all(source: Source | Iterable[Source]) -> list[Invoice]:
    """Every invoice in ``source``, see :func:`iter_invoices`."""
    return list(iter_invoices(source))


def read(source: Source) -> Invoice:
    """Read exactly one invoice. Raises :class:`InvoiceError` if there are none or several."""
    invoices = read_all(source)
    if not invoices:
        raise InvoiceError("no UBL Invoice found")
    if len(invoices) > 1:
        raise InvoiceError(f"found {len(invoices)} invoices, use read_all()")
    return invoices[0]
