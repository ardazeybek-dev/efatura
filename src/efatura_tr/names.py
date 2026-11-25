"""Readable names for the codes that appear most often.

Invoices normally carry the tax name themselves (``TaxScheme/Name``); these
tables are only the fallback when they do not. Codes missing here are still
valid, they are simply shown as the bare code.
"""

from __future__ import annotations

TAX_NAMES: dict[str, str] = {
    "0003": "Gelir Vergisi Stopajı",
    "0011": "Kurumlar Vergisi Stopajı",
    "0015": "KDV",
    "0021": "Banka ve Sigorta Muameleleri Vergisi",
    "0059": "Konaklama Vergisi",
    "0061": "Kaynak Kullanımını Destekleme Fonu",
    "0071": "ÖTV (I) Sayılı Liste",
    "0073": "ÖTV (III) Sayılı Liste",
    "0074": "ÖTV (IV) Sayılı Liste",
    "0075": "ÖTV (V) Sayılı Liste",
    "0076": "ÖTV (VI) Sayılı Liste",
    "0077": "ÖTV (VII) Sayılı Liste",
    "1047": "Damga Vergisi",
    "1048": "5035 Sayılı Kanuna Göre Damga Vergisi",
    "4080": "Özel İletişim Vergisi",
    "4081": "5035 Sayılı Kanuna Göre Özel İletişim Vergisi",
    "8004": "TRT Payı",
    "9015": "KDV Tevkifatı",
    "9077": "ÖTV (II) Sayılı Liste",
}

UNIT_NAMES: dict[str, str] = {
    "C62": "Adet",
    "NIU": "Adet",
    "H87": "Adet",
    "PR": "Çift",
    "SET": "Set",
    "BX": "Kutu",
    "PA": "Paket",
    "KGM": "Kilogram",
    "GRM": "Gram",
    "TNE": "Ton",
    "LTR": "Litre",
    "MLT": "Mililitre",
    "MTR": "Metre",
    "CMT": "Santimetre",
    "KMT": "Kilometre",
    "MTK": "Metrekare",
    "MTQ": "Metreküp",
    "KWH": "Kilovatsaat",
    "MWH": "Megavatsaat",
    "SEC": "Saniye",
    "MIN": "Dakika",
    "HUR": "Saat",
    "DAY": "Gün",
    "WEE": "Hafta",
    "MON": "Ay",
    "ANN": "Yıl",
}


def tax_name(code: str | None) -> str | None:
    """``tax_name("0015")`` -> ``"KDV"``; ``None`` for codes without a common name.

    >>> tax_name("0015")
    'KDV'
    """
    return TAX_NAMES.get(code) if code else None


def unit_name(code: str | None) -> str | None:
    """``unit_name("KGM")`` -> ``"Kilogram"``.

    >>> unit_name("C62")
    'Adet'
    """
    return UNIT_NAMES.get(code) if code else None
