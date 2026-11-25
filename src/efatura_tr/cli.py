"""Command line: ``efatura-tr fatura.xml``, ``efatura-tr indirilenler/ --csv -o faturalar.csv``."""

from __future__ import annotations

import argparse
import csv
import io
import json
import mimetypes
import re
import sys
from collections.abc import Iterator
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from . import __version__
from .check import ERROR, Issue
from .errors import InvoiceError
from .model import Invoice, Line
from .reader import iter_invoices

KURUS = Decimal("0.01")


def _expand(paths: list[str]) -> Iterator[Path]:
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in (".xml", ".zip"):
                    yield child
        else:
            yield path


def _money(value: Decimal | None) -> str:
    return "" if value is None else f"{value.quantize(KURUS, ROUND_HALF_UP):,}"


def _num(value: Decimal | None) -> str:
    """A number without trailing zeros or exponent: 12.500 -> 12.5, 2E+1 -> 20."""
    return "" if value is None else format(value.normalize(), "f")


def _issues_label(issues: list[Issue]) -> str:
    errors = sum(1 for i in issues if i.severity == ERROR)
    warnings = len(issues) - errors
    parts = []
    if errors:
        parts.append(f"{errors} error{'s' * (errors != 1)}")
    if warnings:
        parts.append(f"{warnings} warning{'s' * (warnings != 1)}")
    return ", ".join(parts)


# ---------------------------------------------------------------- summary


def _party_line(label: str, party) -> str:
    ids = []
    if party.vkn:
        ids.append(f"VKN {party.vkn}")
    if party.tckn:
        ids.append(f"TCKN {party.tckn}")
    if party.tax_office:
        ids.append(f"{party.tax_office} VD")
    extra = f"  ({', '.join(ids)})" if ids else ""
    return f"{label:<9}{party.name or '-'}{extra}"


def _truncate(text: str | None, width: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def summary(inv: Invoice, issues: list[Issue]) -> str:
    head = " · ".join(
        p
        for p in (
            inv.number or "(no number)",
            inv.issue_date.isoformat() if inv.issue_date else None,
            "/".join(p for p in (inv.profile, inv.type) if p) or None,
            inv.currency + (f" @ {_num(inv.exchange_rate)}" if inv.exchange_rate else ""),
        )
        if p
    )
    out = [head]
    if inv.uuid:
        out.append(f"{'ETTN':<9}{inv.uuid}")
    out.append(_party_line("Seller", inv.supplier))
    out.append(_party_line("Buyer", inv.customer))
    if inv.buyer is not None and inv.buyer.name:
        out.append(_party_line("End buyer", inv.buyer))
    label = "Returns" if "IADE" in (inv.type or "") else "Refers to"
    for ref in inv.billing_references:
        date = f" ({ref.issue_date.isoformat()})" if ref.issue_date else ""
        out.append(f"{label:<9}{ref.id}{date}")

    out.append("")
    rows = [("#", "Item", "Qty", "Unit price", "Amount", "KDV")]
    for line in inv.lines:
        qty = _num(line.quantity)
        unit = line.unit_name or line.unit_code
        if qty and unit:
            qty = f"{qty} {unit}"
        rate = line.vat_rate
        rows.append(
            (
                line.id,
                _truncate(line.name, 34),
                qty,
                _money(line.unit_price),
                _money(line.amount),
                f"%{_num(rate)}" if rate is not None else "",
            )
        )
    widths = [max(len(r[i]) for r in rows) for i in range(6)]
    right = {2, 3, 4, 5}
    for r in rows:
        cells = [
            c.rjust(w) if i in right else c.ljust(w)
            for i, (c, w) in enumerate(zip(r, widths, strict=True))
        ]
        out.append("  " + "  ".join(cells).rstrip())

    t = inv.totals
    totals: list[tuple[str, Decimal | None]] = [("Lines", t.line_extension)]
    if t.allowance_total:
        totals.append(("Discounts", -t.allowance_total))
    if t.charge_total:
        totals.append(("Charges", t.charge_total))
    if t.tax_exclusive != t.line_extension:
        totals.append(("Tax base", t.tax_exclusive))
    for tax in inv.taxes:
        label = tax.name or tax.code or "Tax"
        if tax.percent is not None:
            label += f" %{_num(tax.percent)}"
        if tax.exemption_code:
            label += f" (exempt {tax.exemption_code})"
        totals.append((label, tax.amount))
    for tax in inv.withholdings:
        totals.append((f"Tevkifat {tax.code} %{_num(tax.percent)}", -tax.amount))
    totals.append(("Total", t.tax_inclusive))
    totals.append(("Payable", t.payable))
    label_w = max(len(label) for label, _ in totals)
    amount_w = max(len(_money(v)) for _, v in totals)
    out.append("")
    for label, value in totals:
        suffix = f" {inv.currency}" if label == "Payable" else ""
        out.append(f"  {label:<{label_w}}  {_money(value):>{amount_w}}{suffix}")

    out.append("")
    if issues:
        out.append(f"{_issues_label(issues)}:")
        out.extend(f"  - {i}" for i in issues)
    else:
        out.append("No problems found.")
    return "\n".join(out)


# ---------------------------------------------------------------- csv


INVOICE_COLUMNS = [
    "source",
    "number",
    "uuid",
    "issue_date",
    "profile",
    "type",
    "currency",
    "exchange_rate",
    "supplier_tax_id",
    "supplier_name",
    "customer_tax_id",
    "customer_name",
    "lines",
    "line_extension",
    "allowance_total",
    "tax_exclusive",
    "vat_total",
    "other_taxes",
    "withholding_total",
    "tax_inclusive",
    "payable",
    "billing_reference",
    "issues",
]

LINE_COLUMNS = [
    "source",
    "number",
    "issue_date",
    "supplier_tax_id",
    "customer_tax_id",
    "line",
    "item",
    "seller_item_id",
    "quantity",
    "unit_code",
    "unit_price",
    "discount",
    "amount",
    "vat_rate",
    "vat_amount",
    "withholding_code",
    "withholding_percent",
    "withholding_amount",
    "currency",
]


def _invoice_row(inv: Invoice, issues: list[Issue], rates: list[Decimal]) -> dict:
    breakdown = inv.vat_breakdown
    gross = sum((t.amount for t in inv.taxes), Decimal(0))
    row = {
        "source": inv.source,
        "number": inv.number,
        "uuid": inv.uuid,
        "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "profile": inv.profile,
        "type": inv.type,
        "currency": inv.currency,
        "exchange_rate": inv.exchange_rate,
        "supplier_tax_id": inv.supplier.tax_id,
        "supplier_name": inv.supplier.name,
        "customer_tax_id": inv.customer.tax_id,
        "customer_name": inv.customer.name,
        "lines": len(inv.lines),
        "line_extension": inv.totals.line_extension,
        "allowance_total": inv.totals.allowance_total,
        "tax_exclusive": inv.totals.tax_exclusive,
        "vat_total": inv.vat_total,
        "other_taxes": gross - inv.vat_total,
        "withholding_total": inv.withholding_total,
        "tax_inclusive": inv.totals.tax_inclusive,
        "payable": inv.totals.payable,
        "billing_reference": " ".join(r.id for r in inv.billing_references) or None,
        "issues": _issues_label(issues) or None,
    }
    for rate in rates:
        base, amount = breakdown.get(rate, (None, None))
        row[f"vat_base_{_num(rate)}"] = base
        row[f"vat_{_num(rate)}"] = amount
    return row


def _line_row(inv: Invoice, line: Line) -> dict:
    withholding = line.withholdings[0] if line.withholdings else None
    discount = sum((a.amount for a in line.allowances if not a.is_charge), Decimal(0))
    return {
        "source": inv.source,
        "number": inv.number,
        "issue_date": inv.issue_date.isoformat() if inv.issue_date else None,
        "supplier_tax_id": inv.supplier.tax_id,
        "customer_tax_id": inv.customer.tax_id,
        "line": line.id,
        "item": line.name,
        "seller_item_id": line.seller_item_id,
        "quantity": line.quantity,
        "unit_code": line.unit_code,
        "unit_price": line.unit_price,
        "discount": discount or None,
        "amount": line.amount,
        "vat_rate": line.vat_rate,
        "vat_amount": line.vat_amount,
        "withholding_code": withholding.code if withholding else None,
        "withholding_percent": withholding.percent if withholding else None,
        "withholding_amount": withholding.amount if withholding else None,
        "currency": inv.currency,
    }


def _cell(value, excel: bool) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        text = format(value, "f")  # as written in the invoice: 25216.50 stays 25216.50
        return text.replace(".", ",") if excel else text
    return str(value)


def write_csv(rows: list[dict], columns: list[str], out, excel: bool) -> None:
    writer = csv.writer(out, delimiter=";" if excel else ",", lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_cell(row.get(c), excel) for c in columns])


# ---------------------------------------------------------------- attachments


def _extension(att) -> str:
    if att.filename and "." in att.filename:
        return Path(att.filename).suffix
    if att.is_xslt:
        return ".xslt"
    guessed = mimetypes.guess_extension(att.mime_type or "")
    return guessed or ".bin"


def save_attachments(inv: Invoice, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_.-]", "_", inv.number or inv.uuid or "invoice")
    written = []
    for n, att in enumerate(inv.attachments, 1):
        name = f"{stem}{'' if len(inv.attachments) == 1 else f'-{n}'}{_extension(att)}"
        target = folder / name
        target.write_bytes(att.data)
        written.append(target)
    return written


# ---------------------------------------------------------------- main


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="efatura-tr",
        description="Read Turkish e-Fatura / e-Arşiv (UBL-TR) invoices and check their totals.",
        epilog="Inputs can be .xml files, .zip archives or folders (searched recursively).",
    )
    parser.add_argument("paths", nargs="+", metavar="PATH", help="invoice XML, ZIP or folder")
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="print every invoice as JSON")
    fmt.add_argument("--csv", action="store_true", help="one CSV row per invoice")
    fmt.add_argument("--lines", action="store_true", help="one CSV row per invoice line")
    fmt.add_argument(
        "--check", action="store_true", help="only list problems; exit 1 if there are errors"
    )
    parser.add_argument(
        "--excel",
        action="store_true",
        help="CSV for Turkish Excel: ';' separator, decimal comma, UTF-8 BOM",
    )
    parser.add_argument(
        "--attachments",
        metavar="DIR",
        help="save embedded files (the XSLT view, PDFs) into DIR",
    )
    parser.add_argument("-o", "--output", metavar="FILE", help="write to FILE instead of stdout")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.excel and not (args.csv or args.lines):
        args.csv = True

    invoices: list[tuple[Invoice, list[Issue]]] = []
    failed = False
    for path in _expand(args.paths):
        try:
            for inv in iter_invoices(path):
                invoices.append((inv, inv.check()))
        except (InvoiceError, OSError) as exc:
            print(f"efatura-tr: {path}: {exc}", file=sys.stderr)
            failed = True

    if args.attachments:
        for inv, _ in invoices:
            for written in save_attachments(inv, Path(args.attachments)):
                print(f"saved {written}", file=sys.stderr)

    buffer = io.StringIO()
    if args.json:
        data = [{**inv.to_dict(), "issues": [vars(i) for i in issues]} for inv, issues in invoices]
        json.dump(data, buffer, ensure_ascii=False, indent=2)
        buffer.write("\n")
    elif args.csv:
        rates = sorted({r for inv, _ in invoices for r in inv.vat_breakdown}, reverse=True)
        columns = list(INVOICE_COLUMNS)
        at = columns.index("vat_total")
        for rate in reversed(rates):
            columns[at:at] = [f"vat_base_{_num(rate)}", f"vat_{_num(rate)}"]
        rows = [_invoice_row(inv, issues, rates) for inv, issues in invoices]
        write_csv(rows, columns, buffer, args.excel)
    elif args.lines:
        rows = [_line_row(inv, line) for inv, _ in invoices for line in inv.lines]
        write_csv(rows, LINE_COLUMNS, buffer, args.excel)
    elif args.check:
        for inv, issues in invoices:
            name = inv.number or inv.source
            if not issues:
                buffer.write(f"{name}: ok\n")
            for issue in issues:
                buffer.write(f"{name}: {issue}\n")
    else:
        buffer.write("\n\n".join(summary(inv, issues) for inv, issues in invoices))
        if invoices:
            buffer.write("\n")

    text = buffer.getvalue()
    if args.output:
        encoding = "utf-8-sig" if args.excel else "utf-8"
        Path(args.output).write_text(text, encoding=encoding, newline="")
    else:
        if args.excel:
            text = "﻿" + text
        _write_stdout(text)

    if failed:
        return 2
    if args.check and any(i.severity == ERROR for _, issues in invoices for i in issues):
        return 1
    return 0


def _write_stdout(text: str) -> None:
    stream = sys.stdout
    # Redirected output (> file, | pipe) is UTF-8 everywhere, also on Windows
    # where the default would be the ANSI code page.
    if not stream.isatty() and hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")
    stream.write(text)
    stream.flush()
