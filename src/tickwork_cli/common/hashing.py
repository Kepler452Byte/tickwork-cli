import hashlib


def digest(content: bytes | None) -> str:
    return "missing" if content is None else hashlib.sha256(content).hexdigest()
