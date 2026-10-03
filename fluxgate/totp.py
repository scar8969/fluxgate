"""TOTP (RFC 6238) — pure stdlib, no dependencies.

Used for optional 2FA on login. Secret is base32; codes are 6 digits,
30-second windows with a ±1 window tolerance.
"""
import base64
import hashlib
import hmac
import struct
import time

STEP = 30
DIGITS = 6


def generate_secret(nbytes=20):
    """Random base32 secret (no padding)."""
    return base64.b32encode(__import__("os").urandom(nbytes)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** DIGITS)).zfill(DIGITS)


def verify(secret_b32: str, code: str, window: int = 1) -> bool:
    """Verify a 6-digit code against the current (and ±window) time steps."""
    if not secret_b32 or not code or len(code) != DIGITS:
        return False
    try:
        int(code)
    except ValueError:
        return False
    counter = int(time.time()) // STEP
    for delta in range(-window, window + 1):
        if hmac.compare_digest(_hotp(secret_b32, counter + delta), code):
            return True
    return False


def provisioning_uri(secret_b32: str, account: str, issuer: str = "FluxGate") -> str:
    """otpauth:// URI for authenticator apps."""
    import urllib.parse
    label = urllib.parse.quote(f"{issuer}:{account}")
    params = urllib.parse.urlencode({
        "secret": secret_b32, "issuer": issuer, "algorithm": "SHA1",
        "digits": DIGITS, "period": STEP,
    })
    return f"otpauth://totp/{label}?{params}"
