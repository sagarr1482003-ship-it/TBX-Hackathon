"""PII encryption-at-rest verification (RBI / DPDP data-at-rest protection).

AES-256-GCM round-trip, tamper detection, wrong-key rejection, idempotency, and row-level
encrypt/decrypt driven by the real seed contract's sensitive-column set. Pure crypto; no database.
"""

from __future__ import annotations

import base64

import pytest

from app.services.ingestion.contract import SEED_CONTRACTS
from app.services.pipeline.masking import sensitive_columns
from app.services.pipeline.pii_crypto import (
    KEY_BYTES,
    PiiCipher,
    PiiCryptoError,
    decrypt_row,
    encrypt_row,
    generate_key,
)


def _cipher() -> PiiCipher:
    return PiiCipher(generate_key())


def test_generated_key_is_aes256() -> None:
    key = generate_key()
    assert len(base64.b64decode(key)) == KEY_BYTES  # 32 bytes = AES-256


def test_round_trip() -> None:
    c = _cipher()
    for value in ["50200013729069", "jhI5nAdyb1qOEjmcB3JvWjC6tTO", "", "unicode ₹ é 中"]:
        assert c.decrypt(c.encrypt(value)) == value


def test_ciphertext_is_not_plaintext() -> None:
    c = _cipher()
    token = c.encrypt("50200013729069")
    assert token is not None
    assert "50200013729069" not in token
    assert token.startswith("enc:v1:")


def test_none_passes_through() -> None:
    c = _cipher()
    assert c.encrypt(None) is None
    assert c.decrypt(None) is None


def test_encrypt_is_idempotent() -> None:
    c = _cipher()
    once = c.encrypt("50200013729069")
    twice = c.encrypt(once)  # already-encrypted token must not be double-encrypted
    assert once == twice
    assert c.decrypt(twice) == "50200013729069"


def test_nonce_makes_ciphertext_non_deterministic() -> None:
    c = _cipher()
    a = c.encrypt("50200013729069")
    b = c.encrypt("50200013729069")
    assert a != b  # fresh nonce each time
    assert c.decrypt(a) == c.decrypt(b) == "50200013729069"


def test_wrong_key_fails() -> None:
    token = PiiCipher(generate_key()).encrypt("50200013729069")
    with pytest.raises(PiiCryptoError):
        PiiCipher(generate_key()).decrypt(token)


def test_tampered_ciphertext_detected() -> None:
    c = _cipher()
    token = c.encrypt("50200013729069")
    assert token is not None
    body = token[len("enc:v1:") :]
    raw = bytearray(base64.b64decode(body))
    raw[-1] ^= 0x01  # flip a bit in the auth tag
    tampered = "enc:v1:" + base64.b64encode(bytes(raw)).decode("ascii")
    with pytest.raises(PiiCryptoError):
        c.decrypt(tampered)


def test_invalid_key_rejected() -> None:
    with pytest.raises(PiiCryptoError):
        PiiCipher("not-base64!!!")
    with pytest.raises(PiiCryptoError):
        PiiCipher(base64.b64encode(b"tooshort").decode("ascii"))


def test_row_encrypt_decrypt_only_touches_sensitive() -> None:
    c = _cipher()
    sensitive = sensitive_columns(SEED_CONTRACTS)  # {account_number, utr_number}
    row = {
        "account_id": "a1",
        "account_number": "50200013729069",
        "utr_number": "jhI5nAdyb1qOEjmcB3JvWjC6tTO",
        "available_balance": "91993.88",
        "bank_code": "HDFC",
    }
    stored = encrypt_row(row, sensitive, c)
    # sensitive columns are ciphertext at rest
    assert stored["account_number"].startswith("enc:v1:")
    assert stored["utr_number"].startswith("enc:v1:")
    assert "50200013729069" not in stored["account_number"]
    # non-sensitive columns untouched
    assert stored["available_balance"] == "91993.88"
    assert stored["bank_code"] == "HDFC"
    # read path recovers the originals
    restored = decrypt_row(stored, sensitive, c)
    assert restored["account_number"] == "50200013729069"
    assert restored["utr_number"] == "jhI5nAdyb1qOEjmcB3JvWjC6tTO"
