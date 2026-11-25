# efatura-tr

[![CI](https://github.com/ardazeybek-dev/efatura/actions/workflows/ci.yml/badge.svg)](https://github.com/ardazeybek-dev/efatura/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/efatura-tr.svg)](https://pypi.org/project/efatura-tr/)

Read Turkish **e-Fatura** and **e-Arşiv** invoices (UBL-TR 1.2 XML) into typed
Python objects, JSON or CSV, and check that their totals add up.

Every integrator portal lets you download invoices as XML or as a ZIP of XMLs.
Getting from there to a spreadsheet, an accounting import or a database means
reading UBL, which is deep, namespaced and full of Turkish special cases:

* On a **tevkifat** invoice `TaxTotal/TaxAmount` is the KDV *left after*
  withholding, not the sum of its own subtotals, and the payable amount is the
  total minus the withheld part.
* The invoice-level `LineExtensionAmount` is the sum of the line amounts in some
  invoices and the sum *before line discounts* in others. Both conventions
  appear in GIB's own samples.
* **İstisna** and **özel matrah** subtotals show a computed KDV that is not
  charged. **ÖTV** is part of the KDV base. **HKS** commission invoices take
  their deductions off the payable amount.
* Invoices arrive bare, inside GIB's `StandardBusinessDocument` envelope, or in
  ZIP files, sometimes nested.

`efatura-tr` handles all of these with the standard library only (no `lxml`),
and turns each invoice into one dataclass with `Decimal` amounts.

```bash
pip install efatura-tr        # Python 3.10+, no dependencies
```

## Command line

```console
$ efatura-tr TEVKIFAT.xml
SRM2012000086985 · 2012-08-04 · TICARIFATURA/TEVKIFAT · TRY
ETTN     F47AC10B-58CC-4372-A567-0E02B2C3D479
Seller   Örnek İnşaat Hafriyat Nakliyat Demirçelik Madencilik San. ve Tic. Ltd. Şti.  (VKN 0890890895, Ziyapaşa VD)
Buyer    British American Tobacco Exports B.V. Merkezi  (VKN 1870200192, Büyük Mükellefler VD)

  #  Item             Qty  Unit price     Amount  KDV
  1  İş gücü hizmeti    1   20,000.00  20,000.00

  Lines             20,000.00
  KDV %18            3,600.00
  Tevkifat 606 %90  -3,240.00
  Total             23,600.00
  Payable           20,360.00 TRY
```

A folder of downloads (searched recursively, ZIPs included) to one CSV row per
invoice, with a matrah and KDV column for every rate that occurs:

```bash
efatura-tr indirilenler/ --csv -o faturalar.csv
efatura-tr indirilenler/ --excel -o faturalar.csv   # ';' + decimal comma + BOM for Turkish Excel
efatura-tr indirilenler/ --lines -o kalemler.csv    # one row per invoice line
efatura-tr fatura.xml --json                        # everything, as JSON
efatura-tr fatura.xml --attachments gorunum/        # save the embedded XSLT / PDF
efatura-tr gelen/ --check                           # problems only; exit 1 on errors
```

The exit code is `0` on success, `1` when `--check` finds an error and `2` when
a file could not be read (the other files are still processed).

## Python

```python
import efatura_tr

inv = efatura_tr.read("fatura.xml")          # also bytes, XML text or a file object
inv.number, inv.uuid, inv.issue_date          # 'SRM2012000086985', 'F47AC10B-…', date(2012, 8, 4)
inv.profile, inv.type                         # 'TICARIFATURA', 'TEVKIFAT'
inv.supplier.vkn, inv.supplier.tax_office     # '0890890895', 'Ziyapaşa'
inv.customer.address.city                     # 'İstanbul'
inv.totals.payable                            # Decimal('20360')
inv.vat_breakdown                             # {Decimal('18'): (Decimal('20000'), Decimal('3600'))}
inv.withholdings[0].code                      # '606'

for line in inv.lines:
    print(line.name, line.quantity, line.unit_name, line.unit_price, line.amount, line.vat_rate)

for issue in inv.check():
    print(issue)                              # warning: supplier VKN 0890890895 fails the checksum [supplier.vkn]

# Many invoices: a folder, a ZIP, an envelope with several invoices, or a list
for inv in efatura_tr.iter_invoices("indirilenler/"):
    ...

inv.to_dict()                                 # JSON-ready: amounts as strings, dates as ISO
inv.xslt.data                                 # the embedded XSLT, as bytes
```

What is read: invoice number, ETTN, dates, profile and type, currency and
exchange rate, seller, buyer and end buyer (`BuyerCustomerParty`, for export
and tax-free invoices) with VKN/TCKN, tax office, address and every other
identifier (MERSİS, ticaret sicil...), lines with quantity, unit, price,
discounts, taxes and withholdings, invoice taxes with exemption codes and
reasons, all totals, notes, return (IADE) and despatch references, the order
reference, payment means with IBAN, payment terms and embedded attachments.

## Checks

`invoice.check()` returns a list of `Issue(severity, code, message)`, errors
first. There are two kinds:

**GIB rules**, taken from the official schematron, which would get an invoice
rejected: invoice number format (`ABC2024000000001`), ETTN format, VKN must be
10 digits and TCKN 11, IADE invoices must reference the returned invoice, an
istisna invoice with 0 KDV needs an exemption reason code. Codes (profile,
invoice type, tax, tevkifat, exemption, currency, unit) are checked against
GIB's code list, which is kept in [`scripts/UBL-TR_Codelist.xml`](scripts/UBL-TR_Codelist.xml)
and compiled with `scripts/build_codes.py`.

**Arithmetic**, which the schematron does *not* check, reported as warnings:

* quantity × price − discounts + charges = line amount;
* each tax = base × rate, each tevkifat = KDV × rate;
* line taxes add up to the invoice taxes;
* lines → `LineExtensionAmount` → `TaxExclusiveAmount` → `TaxInclusiveAmount`
  → `PayableAmount`, with tevkifat, prepayments and rounding.

One kuruş of rounding per line is tolerated. VKN/TCKN checksums are warnings,
not errors.

The test suite runs the checks over all 30 sample invoices in GIB's
[UBL-TR 1.2.1](https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/UBL-TR1.2.1_Paketi.zip)
and [e-Fatura](https://ebelge.gib.gov.tr/dosyalar/kilavuzlar/e-FaturaPaketi.zip)
packages. Eight of them contain real mistakes, for example a line where
8 × 31,750 is written as 264,000, a KDV of 10% on 2.25 written as 0.90, or a
17-character invoice number. The expected findings for every sample are pinned
in [`tests/test_gib_samples.py`](tests/test_gib_samples.py).

## What it does not do

* **Signatures** are not verified. Use your integrator or GIB for that.
* **XSD and the full schematron** are not run. The checks above are the ones
  that catch real mistakes, not a replacement for GIB's validation.
* **Rendering**: the embedded XSLT is extracted, not applied. The standard
  library has no XSLT; `lxml` can apply it in a few lines.
* Only `Invoice` documents are read. e-İrsaliye (`DespatchAdvice`) and
  application responses are skipped.

## Safety and privacy

Invoices come from outside, so the XML is treated as untrusted. Any document
with a `DOCTYPE` is refused before parsing (UBL never uses one, and it is how
entity-expansion and XXE attacks work), XML and ZIP members are size-limited,
and nothing is fetched over the network.

Real invoices contain tax numbers, national ID numbers and addresses, which are
personal data under KVKK. The repository's `.gitignore` blocks `*.xml`, `*.zip`,
`*.csv` and `*.pdf` outside `tests/fixtures/`, and the only invoices in the
repository are GIB's published samples and synthetic ones built in
`tests/conftest.py`.

## Development

```bash
git clone https://github.com/ardazeybek-dev/efatura.git
cd efatura
python -m venv .venv
.venv/bin/pip install -e ".[dev]"        # Windows: .venv\Scripts\pip
pytest                                    # tests + doctests
ruff check . && ruff format --check .
python scripts/build_codes.py --check     # code lists match the GIB file
```

No environment variables are needed.

```
src/efatura_tr/
  reader.py       files, folders, ZIPs, envelopes; DOCTYPE refusal and size limits
  parse.py        UBL element -> model
  model.py        Invoice, Party, Line, Tax, Totals ... (frozen dataclasses)
  check.py        GIB rules and arithmetic checks
  ids.py          VKN / TCKN checksums
  names.py        Turkish names of common tax and unit codes
  _codelists.py   generated from scripts/UBL-TR_Codelist.xml
  cli.py          the efatura-tr command
scripts/          build_codes.py and GIB's code list
tests/fixtures/gib/   GIB's official sample invoices
```

To update the code lists, replace `scripts/UBL-TR_Codelist.xml` with the file
from the latest e-Fatura package and run `python scripts/build_codes.py`.

## Pitfalls

* Tevkifat invoice flagged as "tax total wrong" → `TaxTotal/TaxAmount` is KDV minus the withheld part → compare it with both the gross and the net sum.
* İstisna/özel matrah invoice "does not add up" → those subtotals carry a computed but uncharged KDV → leave subtotals with an exemption code out of the charged total.
* Invoice-level `LineExtensionAmount` is larger than the sum of lines → it is the pre-discount sum, with line discounts in `AllowanceTotalAmount` → accept both conventions.
* `import efatura` picks up the wrong package on Windows → the unrelated `efatura` package installs `eFatura`, and the filesystem ignores case → this package is imported as `efatura_tr`.

## Türkiye toolkit

Part of a small set of tools for the Turkish data that general-purpose libraries get wrong:

| Package | What it does | Install |
| --- | --- | --- |
| [trkit](https://github.com/ardazeybek-dev/trkit) | Turkish casing (`i` → `İ`), slugify, TCKN, IBAN and plate validation · Python + CLI | `pip install trkit` |
| [trkit-js](https://github.com/ardazeybek-dev/trkit-js) | The same for JavaScript, plus VKN, phone numbers and Zod schemas | `npm install @ardazeybek-dev/trkit` |
| [kvkk](https://github.com/ardazeybek-dev/kvkk) | Finds and masks Turkish personal data in files, logs and dumps | `pip install kvkk` |
| [ekstre](https://github.com/ardazeybek-dev/ekstre) | Turkish bank statement exports (.xlsx, .xls, .csv) into typed transactions | `pip install ekstre` |
| [adres-tr](https://github.com/ardazeybek-dev/adres) | Free-form Turkish addresses into province, district, neighbourhood, street… | `pip install adres-tr` |
| [isgunu](https://github.com/ardazeybek-dev/isgunu) | Public holidays, arife half days and business-day arithmetic · Python + JS | `pip install isgunu` |
| [bordro](https://github.com/ardazeybek-dev/bordro) | Payroll: gross ↔ net with the cumulative income tax · TypeScript | `npm install bordro` |

## License

MIT. The sample invoices in `tests/fixtures/gib/` and the code list in
`scripts/` are published by the Turkish Revenue Administration (Gelir İdaresi
Başkanlığı) at [ebelge.gib.gov.tr](https://ebelge.gib.gov.tr).
