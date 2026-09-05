"""Generate a fresh AES-256 key (base64) for PII encryption at rest.

Usage:
    python -m scripts.gen_pii_key

Copy the printed value into ``PII_ENCRYPTION_KEY`` in your ``.env``. Rotating the key requires
re-encrypting stored sensitive columns (decrypt with the old key, encrypt with the new one).
"""

from __future__ import annotations

from app.services.pipeline.pii_crypto import generate_key


def main() -> None:
    print(generate_key())


if __name__ == "__main__":
    main()
