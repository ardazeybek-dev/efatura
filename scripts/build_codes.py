"""Generate ``src/efatura_tr/_codelists.py`` from GIB's official code list.

Source: ``UBL-TR_Codelist.xml`` from the e-Fatura package published by the
Revenue Administration (https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/e-FaturaPaketi.zip,
``schematron/UBL-TR_Codelist.xml``). A copy is kept next to this script.

    python scripts/build_codes.py          # rewrite the module
    python scripts/build_codes.py --check  # fail if the module is out of date (CI)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "scripts" / "UBL-TR_Codelist.xml"
TARGET = ROOT / "src" / "efatura_tr" / "_codelists.py"

# Schematron variable name -> Python constant name.
LISTS = {
    "ProfileIDType": "PROFILE_IDS",
    "ProfileIDTypeEarchive": "PROFILE_IDS_EARCHIVE",
    "InvoiceTypeCodeList": "INVOICE_TYPE_CODES",
    "TaxType": "TAX_TYPE_CODES",
    "WithholdingTaxType": "WITHHOLDING_TAX_TYPE_CODES",
    "TaxExemptionReasonCodeType": "TAX_EXEMPTION_REASON_CODES",
    "YatirimTesvikTaxExemptionReasonCodeType": "TAX_EXEMPTION_REASON_CODES_YATIRIM_TESVIK",
    "istisnaTaxExemptionReasonCodeType": "TAX_EXEMPTION_REASON_CODES_ISTISNA",
    "ozelMatrahTaxExemptionReasonCodeType": "TAX_EXEMPTION_REASON_CODES_OZEL_MATRAH",
    "ihracExemptionReasonCodeType": "TAX_EXEMPTION_REASON_CODES_IHRAC",
    "CurrencyCodeList": "CURRENCY_CODES",
    "UnitCodeList": "UNIT_CODES",
    "PaymentMeansCodeTypeList": "PAYMENT_MEANS_CODES",
    "PartyIdentificationIDType": "PARTY_ID_SCHEMES",
}


def read_lists(text: str) -> dict[str, list[str]]:
    found = dict(re.findall(r'<sch:let\s+name="(\w+)"\s+value\s*="([^"]*)"', text))
    out = {}
    for name, const in LISTS.items():
        if name not in found:
            raise SystemExit(f"{name} is missing from {SOURCE.name}")
        out[const] = [v for v in found[name].strip("'").split(",") if v]
    return out


def render(lists: dict[str, list[str]]) -> str:
    lines = [
        '"""Code lists from GIB\'s UBL-TR_Codelist.xml (generated, do not edit).',
        "",
        "Regenerate with ``python scripts/build_codes.py``.",
        '"""',
        "",
    ]
    for const, values in lists.items():
        lines.append(f"{const}: frozenset[str] = frozenset(")
        lines.append("    {")
        row = ""
        for value in values:
            item = f'"{value}",'
            if row and len(row) + 1 + len(item) > 92:
                lines.append(f"        {row}")
                row = ""
            row = f"{row} {item}" if row else item
        if row:
            lines.append(f"        {row}")
        lines.append("    }")
        lines.append(")")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    module = render(read_lists(SOURCE.read_text(encoding="utf-8")))
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != module:
            print(f"{TARGET.relative_to(ROOT)} is out of date, run scripts/build_codes.py")
            return 1
        print("code lists are up to date")
        return 0
    TARGET.write_text(module, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
