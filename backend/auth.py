"""Simple API key authentication for LLM endpoints."""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer(auto_error=False)

AUTH_CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "auth.json"


def _load_auth_config() -> dict:
    """Load auth config from file."""
    import json
    if AUTH_CONFIG_PATH.exists():
        try:
            with open(AUTH_CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_auth_config(config: dict) -> None:
    """Save auth config to file."""
    import json
    AUTH_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUTH_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def generate_api_key() -> str:
    """Generate a new API key."""
    return f"sk-{secrets.token_hex(32)}"


def hash_key(key: str) -> str:
    """Hash an API key for storage."""
    return hashlib.sha256(key.encode()).hexdigest()


def get_stored_keys() -> list[dict]:
    """Get all stored API keys."""
    config = _load_auth_config()
    return config.get("api_keys", [])


def add_api_key(name: str, key: str) -> dict:
    """Add a new API key."""
    config = _load_auth_config()
    if "api_keys" not in config:
        config["api_keys"] = []

    key_entry = {
        "name": name,
        "key_hash": hash_key(key),
        "key_prefix": key[:8] + "...",
        "active": True,
    }
    config["api_keys"].append(key_entry)
    _save_auth_config(config)
    return key_entry


def validate_api_key(key: str) -> bool:
    """Validate an API key against stored hashes."""
    config = _load_auth_config()
    keys = config.get("api_keys", [])

    if not keys:
        # no keys configured = auth disabled
        return True

    key_hash = hash_key(key)
    for entry in keys:
        if entry.get("active") and entry.get("key_hash") == key_hash:
            return True
    return False


def is_auth_enabled() -> bool:
    """Check if API key auth is enabled."""
    config = _load_auth_config()
    return bool(config.get("api_keys"))


async def verify_api_key(request: Request) -> bool:
    """Verify API key from request headers or query params."""
    if not is_auth_enabled():
        return True

    # check Authorization header
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        key = auth[7:]
        if validate_api_key(key):
            return True

    # check X-API-Key header
    api_key = request.headers.get("X-API-Key", "")
    if api_key and validate_api_key(api_key):
        return True

    # check query param
    api_key = request.query_params.get("api_key", "")
    if api_key and validate_api_key(api_key):
        return True

    raise HTTPException(status_code=401, detail="Invalid or missing API key")
