#!/usr/bin/env python3
"""Poll the device library for version changes and fetch content when updated.

Requires three environment variables:
  LIBRARY_BASE_URL  – e.g. https://library.example.com
  LIBRARY_KEY_ID    – UUID of the API key
  LIBRARY_KEY_SECRET – the API key secret (used as HMAC shared secret)

Optional:
  LIBRARY_POLL_INTERVAL – seconds between polls (default: 60)
  LIBRARY_OUTPUT_DIR    – directory to write fetched library JSON (default: ./library-sync)
"""

import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        print(f"error: missing required environment variable {name}", file=sys.stderr)
        sys.exit(1)
    return value


BASE_URL = get_env("LIBRARY_BASE_URL").rstrip("/")
KEY_ID = get_env("LIBRARY_KEY_ID")
KEY_SECRET = get_env("LIBRARY_KEY_SECRET")
POLL_INTERVAL = int(get_env("LIBRARY_POLL_INTERVAL", "60"))
OUTPUT_DIR = Path(get_env("LIBRARY_OUTPUT_DIR", "./library-sync"))


def sign_request(method: str, path: str) -> dict[str, str]:
    """Build HMAC authentication headers for a request."""
    timestamp = str(int(time.time()))
    message = f"{timestamp}.{method}.{path}"
    signature = hmac.new(
        KEY_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()
    return {
        "X-API-Key-Id": KEY_ID,
        "X-Timestamp": timestamp,
        "X-Signature": signature,
    }


def api_get(path: str) -> dict:
    """Make an authenticated GET request and return parsed JSON."""
    url = f"{BASE_URL}{path}"
    headers = sign_request("GET", path)
    headers["Accept"] = "application/json"
    req = Request(url, headers=headers, method="GET")
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_version() -> int:
    """Get the current library version number."""
    data = api_get("/api/v1/library/version/")
    return data["version"]


def fetch_content(version: int) -> dict:
    """Fetch the full library content for a specific version."""
    return api_get(f"/api/v1/library/content/{version}/")


def save_content(version: int, content: dict) -> Path:
    """Write library content to a JSON file and a latest symlink."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    filepath = OUTPUT_DIR / f"library-v{version}.json"
    filepath.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n")

    latest = OUTPUT_DIR / "latest.json"
    latest.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n")

    return filepath


def main() -> None:
    print(f"library-sync: polling {BASE_URL} every {POLL_INTERVAL}s")
    print(f"library-sync: output dir {OUTPUT_DIR.resolve()}")

    known_version = 0

    while True:
        try:
            remote_version = fetch_version()

            if remote_version == 0:
                print("library-sync: no published version yet, waiting...")
            elif remote_version != known_version:
                print(f"library-sync: version changed {known_version} -> {remote_version}, fetching content...")
                content = fetch_content(remote_version)
                path = save_content(remote_version, content)
                vendor_count = len(content.get("vendors", []))
                device_count = sum(
                    len(v.get("devices", []))
                    for v in content.get("vendors", [])
                )
                print(f"library-sync: saved v{remote_version} ({vendor_count} vendors, {device_count} devices) -> {path}")
                known_version = remote_version
        except HTTPError as e:
            print(f"library-sync: HTTP {e.code} from server: {e.reason}", file=sys.stderr)
        except URLError as e:
            print(f"library-sync: connection error: {e.reason}", file=sys.stderr)
        except Exception as e:
            print(f"library-sync: unexpected error: {e}", file=sys.stderr)

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
