"""Checksums of Turkish tax numbers (VKN) and national ID numbers (TCKN)."""

from __future__ import annotations


def is_valid_vkn(value: str | None) -> bool:
    """True if ``value`` is a 10-digit vergi kimlik numarası with a correct check digit.

    >>> is_valid_vkn("1234567891")
    False
    >>> is_valid_vkn("3900892152")  # Gelir İdaresi Başkanlığı
    True
    """
    if not value or len(value) != 10 or not value.isascii() or not value.isdigit():
        return False
    digits = [int(c) for c in value]
    total = 0
    for i in range(9):
        v = (digits[i] + 9 - i) % 10
        total += 9 if v == 9 else (v * 2 ** (9 - i)) % 9
    return (10 - total % 10) % 10 == digits[9]


def is_valid_tckn(value: str | None) -> bool:
    """True if ``value`` is an 11-digit T.C. kimlik numarası with correct check digits.

    >>> is_valid_tckn("10000000146")
    True
    >>> is_valid_tckn("10000000147")
    False
    """
    if not value or len(value) != 11 or not value.isascii() or not value.isdigit():
        return False
    d = [int(c) for c in value]
    if d[0] == 0:
        return False
    tenth = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    return tenth == d[9] and sum(d[:10]) % 10 == d[10]
