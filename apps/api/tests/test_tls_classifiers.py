"""Gate A follow-up A5: classifier-level coverage for TLS_WEAK_CIPHER and
TLS_WEAK_KEY_EXCHANGE, independent of any live server. rc4.badssl.com turned
out to be a dead fixture (docs/ACCURACY_REPORT.md) — no server anywhere
would ever again give TLS_WEAK_CIPHER a positive live test, which left it
with zero real coverage. These test the pure classification functions
directly with fixed, known suite names instead: deterministic, no network,
no dependence on any one server's continued (mis)configuration.
"""

from __future__ import annotations

import pytest

from app.scanner.tls import (
    _key_exchange_type_from_cipher,
    classify_weak_cipher,
    classify_weak_key_exchange,
)

# --- TLS_WEAK_CIPHER: RC4, 3DES, NULL, EXPORT, or CBC-only ---

KNOWN_WEAK_CIPHER_NAMES = (
    "RC4-SHA",  # RC4
    "RC4-MD5",  # RC4
    "DES-CBC3-SHA",  # 3DES (OpenSSL names it with a literal "CBC3")
    "ECDHE-RSA-DES-CBC3-SHA",  # 3DES, ECDHE key exchange otherwise fine
    "NULL-SHA",  # null encryption
    "NULL-MD5",  # null encryption
    "EXP-RC4-MD5",  # export-grade
    "EXP-DES-CBC-SHA",  # export-grade
    "AES128-SHA",  # CBC-only, no AEAD
    "AES256-SHA256",  # CBC-only, no AEAD
    "ECDHE-RSA-AES128-SHA",  # CBC-only, despite a modern ECDHE key exchange
)

KNOWN_GOOD_CIPHER_NAMES = (
    "ECDHE-RSA-AES128-GCM-SHA256",  # AEAD/GCM
    "ECDHE-ECDSA-AES256-GCM-SHA384",  # AEAD/GCM
    "ECDHE-RSA-CHACHA20-POLY1305",  # AEAD/ChaCha20-Poly1305
    "TLS_AES_128_GCM_SHA256",  # TLS 1.3
    "TLS_AES_256_GCM_SHA384",  # TLS 1.3
    "TLS_CHACHA20_POLY1305_SHA256",  # TLS 1.3
    "DHE-RSA-AES128-GCM-SHA256",  # AEAD/GCM, DHE key exchange
)


@pytest.mark.parametrize("cipher_name", KNOWN_WEAK_CIPHER_NAMES)
def test_classify_weak_cipher_flags_known_weak_suites(cipher_name: str) -> None:
    assert classify_weak_cipher(cipher_name) is True


@pytest.mark.parametrize("cipher_name", KNOWN_GOOD_CIPHER_NAMES)
def test_classify_weak_cipher_allows_known_good_suites(cipher_name: str) -> None:
    assert classify_weak_cipher(cipher_name) is False


def test_classify_weak_cipher_is_case_insensitive() -> None:
    assert classify_weak_cipher("rc4-sha") is True
    assert classify_weak_cipher("ecdhe-rsa-aes128-gcm-sha256") is False


# --- TLS_WEAK_KEY_EXCHANGE: DHE < 2048 bits, or ECDHE curve < 256 bits ---


@pytest.mark.parametrize(
    ("key_exchange_type", "bits"),
    [
        ("DHE", 512),
        ("DHE", 1024),
        ("DHE", 2047),
        ("ECDHE", 128),
        ("ECDHE", 192),
        ("ECDHE", 255),
    ],
)
def test_classify_weak_key_exchange_flags_known_weak_parameters(
    key_exchange_type: str, bits: int
) -> None:
    assert classify_weak_key_exchange(key_exchange_type, bits) is True


@pytest.mark.parametrize(
    ("key_exchange_type", "bits"),
    [
        ("DHE", 2048),
        ("DHE", 3072),
        ("ECDHE", 256),
        ("ECDHE", 384),
        ("ECDHE", 521),
    ],
)
def test_classify_weak_key_exchange_allows_known_good_parameters(
    key_exchange_type: str, bits: int
) -> None:
    assert classify_weak_key_exchange(key_exchange_type, bits) is False


def test_classify_weak_key_exchange_never_fires_when_bits_unknown() -> None:
    # Rule 7 (CLAUDE.md): never guess. This stack's TLS library exposes no
    # negotiated-group getter, so bits is always None in live scans — the
    # finding must never fire from an unknown value, DHE or ECDHE alike.
    assert classify_weak_key_exchange("DHE", None) is False
    assert classify_weak_key_exchange("ECDHE", None) is False


def test_classify_weak_key_exchange_returns_false_for_unknown_type() -> None:
    assert classify_weak_key_exchange(None, 512) is False


# --- key exchange type derivation from the negotiated cipher-suite name ---


@pytest.mark.parametrize(
    ("cipher_name", "expected_type"),
    [
        ("ECDHE-RSA-AES128-GCM-SHA256", "ECDHE"),
        ("ECDHE-ECDSA-AES256-GCM-SHA384", "ECDHE"),
        ("DHE-RSA-AES128-GCM-SHA256", "DHE"),
        ("DHE-RSA-AES256-SHA", "DHE"),
        ("AES128-SHA", None),  # plain RSA key exchange, no (EC)DHE at all
        ("TLS_AES_256_GCM_SHA384", None),  # TLS 1.3 names don't encode it
    ],
)
def test_key_exchange_type_from_cipher(cipher_name: str, expected_type: str | None) -> None:
    assert _key_exchange_type_from_cipher(cipher_name) == expected_type
