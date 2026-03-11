from hashlib import sha256
from hmac import compare_digest


def hash_device_secret(secret: str, pepper: str) -> str:
    return sha256(f"{secret}{pepper}".encode("utf-8")).hexdigest()


def verify_device_secret(raw_secret: str, stored_hash: str, pepper: str) -> bool:
    expected = hash_device_secret(raw_secret, pepper)
    return compare_digest(expected, stored_hash)
