"""Instance registry for the Device Library MCP server.

The library is a single central service (not a fleet), so the registry is
two static entries:

    LOCAL_LIBRARY_URL       URL of the local dev library (default
                            ``http://web:8000`` — Docker DNS for this repo's
                            compose). Empty string suppresses the entry.
    PROD_LIBRARY_URL        URL of the production library. Empty = no
                            production entry.
    LIBRARY_API_KEY         X-API-Key sent to both instances (create one in
                            the library admin UI; a dedicated "mcp-agent" key
                            keeps agent traffic identifiable).
    LIBRARY_API_KEY_PROD    Optional production-specific key override.
    DEFAULT_LIBRARY_INSTANCE  Defaults to ``local`` when LOCAL_LIBRARY_URL is
                            set, else ``production``.

Whether writes work is decided server-side per deployment by the library's
``AGENT_API_ALLOW_WRITES`` setting — the MCP server carries no write flag of
its own, so there is exactly one switch to reason about.
"""

from __future__ import annotations

import os

import httpx

LOCAL_LIBRARY_URL = os.environ.get("LOCAL_LIBRARY_URL", "http://web:8000").rstrip("/")
PROD_LIBRARY_URL = os.environ.get("PROD_LIBRARY_URL", "").rstrip("/")
LIBRARY_API_KEY = os.environ.get("LIBRARY_API_KEY", "").strip()
LIBRARY_API_KEY_PROD = os.environ.get("LIBRARY_API_KEY_PROD", "").strip() or LIBRARY_API_KEY

_INSTANCES: dict[str, dict] = {}
if LOCAL_LIBRARY_URL:
    _INSTANCES["local"] = {
        "url": LOCAL_LIBRARY_URL,
        "key": LIBRARY_API_KEY,
        "description": "Local dev library (docker compose)",
    }
if PROD_LIBRARY_URL:
    _INSTANCES["production"] = {
        "url": PROD_LIBRARY_URL,
        "key": LIBRARY_API_KEY_PROD,
        "description": "Production device library",
    }

DEFAULT_INSTANCE = os.environ.get(
    "DEFAULT_LIBRARY_INSTANCE",
    "local" if "local" in _INSTANCES else ("production" if _INSTANCES else ""),
)


def describe_instances() -> dict:
    return {
        "default": DEFAULT_INSTANCE,
        "instances": [
            {"name": name, "url": inst["url"], "description": inst["description"],
             "has_key": bool(inst["key"])}
            for name, inst in _INSTANCES.items()
        ],
    }


def client_for(instance: str = "") -> httpx.Client:
    name = instance or DEFAULT_INSTANCE
    inst = _INSTANCES.get(name)
    if inst is None:
        known = ", ".join(_INSTANCES) or "none configured"
        raise ValueError(f"Unknown library instance '{name}'. Known: {known}")
    headers = {"X-API-Key": inst["key"]} if inst["key"] else {}
    return httpx.Client(
        base_url=f"{inst['url']}/api/v1/agent",
        headers=headers,
        timeout=30.0,
    )
