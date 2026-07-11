"""Generate a Fernet key for TOKEN_ENCRYPTION_KEY.

Run once and copy the printed value into your ``.env`` file:

    python scripts/generate_key.py

The key encrypts the stored OAuth refresh token at rest. Keep it secret and
stable — rotating it invalidates any already-encrypted tokens.
"""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(Fernet.generate_key().decode())
