"""Project API keys.

Keys are 256-bit random tokens, so a fast SHA-256 hash is enough: there is nothing to
brute-force (unlike passwords, which need a slow hash). Only the hash and a short
display prefix are stored; the full key is shown once, at creation.
"""

import hashlib
import secrets

KEY_PREFIX = "ask_"
DISPLAY_PREFIX_LEN = len(KEY_PREFIX) + 8


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def display_prefix(key: str) -> str:
    return key[:DISPLAY_PREFIX_LEN]
