import secrets


def generate_key() -> str:
    """Return a 256-bit URL-safe API key."""
    return secrets.token_urlsafe(32)
