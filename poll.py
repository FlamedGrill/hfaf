#!/usr/bin/env python3
"""Scheduled polling utility.

Queries a source endpoint, keeps the entries whose value is at or below a
threshold, and sends a push notification (via ntfy.sh) for anything new. A
small state file suppresses repeats within a cooldown window. Standard library
only, so it runs on a bare runner with no install step.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------
RADIUS = 8              # appended to the source URL
THRESHOLD = 10000       # ignore entries whose value exceeds this
COOLDOWN_MINUTES = 20   # don't repeat the same id within this window

# --------------------------------------------------------------------------
# Fixed config
# --------------------------------------------------------------------------
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
NTFY_BASE = "https://ntfy.sh"
HTTP_TIMEOUT = 20
# A browser-like User-Agent: the source sits behind a CDN that rejects
# requests from datacentre IPs carrying an unusual agent string.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch_items(base):
    """Return the list of entries from the source, or None on any error."""
    url = f"{base}/{RADIUS}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError) as exc:
        print(f"WARN: source query failed: {exc}", file=sys.stderr)
        return None
    return data.get("ac") or []


def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError):
        return {}
    return data.get("seen", {})


def save_state(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump({"seen": seen}, fh, indent=2, sort_keys=True)
        fh.write("\n")


def prune(seen, now):
    """Drop entries older than the cooldown so the state file stays small."""
    cutoff = now - (COOLDOWN_MINUTES * 60)
    return {k: v for k, v in seen.items() if v >= cutoff}


def matches(item):
    """True if the entry is present and at or below the threshold."""
    val = item.get("alt_baro")
    if val is None or val == "ground":
        return False
    try:
        return float(val) <= THRESHOLD
    except (TypeError, ValueError):
        return False


def format_message(item):
    label = (item.get("flight") or "").strip() or item.get("hex", "?")
    parts = [label]
    val = item.get("alt_baro")
    if isinstance(val, (int, float)):
        parts.append(f"{int(round(val)):,}ft")
    dist = item.get("dst")
    if isinstance(dist, (int, float)):
        parts.append(f"{dist:.1f}nm")
    return " · ".join(parts)


def notify(topic, message):
    """POST a message to the ntfy topic. Returns True on success."""
    req = urllib.request.Request(
        f"{NTFY_BASE}/{topic}",
        data=message.encode("utf-8"),
        headers={"User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
        print(f"WARN: notify failed: {exc}", file=sys.stderr)
        return False
    return True


def main():
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    base = os.environ.get("SOURCE_URL", "").strip()
    if not topic or not base:
        print("ERROR: NTFY_TOPIC and SOURCE_URL must both be set.", file=sys.stderr)
        return 1

    now = int(time.time())
    seen = prune(load_state(), now)

    items = fetch_items(base)
    if items is None:
        # Transient failure — persist any pruning and exit cleanly.
        save_state(seen)
        return 0

    cooldown = COOLDOWN_MINUTES * 60
    count = 0

    for item in items:
        if not matches(item):
            continue
        key = item.get("hex")
        if not key:
            continue
        last = seen.get(key)
        if last is not None and (now - last) < cooldown:
            continue
        message = format_message(item)
        if notify(topic, message):
            print(f"HIT: {message}")
            seen[key] = now
            count += 1

    if count == 0:
        print(f"No new matches ({len(items)} scanned).")

    save_state(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
