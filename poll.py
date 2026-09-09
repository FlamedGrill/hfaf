#!/usr/bin/env python3
"""Scheduled polling utility.

Queries a source endpoint, keeps the entries that are low enough and high
enough above the horizon to plausibly be seen from the ground, and sends a
push notification (via ntfy.sh) for anything new. A small state file
suppresses repeats within a cooldown window. Standard library only, so it
runs on a bare runner with no install step.
"""

import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------
RADIUS = 8              # outer search radius (appended to the source URL)
THRESHOLD = 10000       # ignore entries whose value exceeds this
MIN_ELEVATION_DEG = 10  # how high above the horizon it must appear to count
                        # as "probably visible". Higher = only nearer/higher
                        # things; lower it (e.g. 5) if alerts are too rare.
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

FEET_PER_NM = 6076.12
COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass(deg):
    """Turn a bearing in degrees into an 8-point compass label."""
    return COMPASS[round(deg / 45.0) % 8]


def elevation_deg(alt_ft, dst_nm):
    """Angle above the horizon, in degrees, of something at alt_ft and dst_nm."""
    if dst_nm <= 0:
        return 90.0
    return math.degrees(math.atan(alt_ft / (dst_nm * FEET_PER_NM)))


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


def visible(item):
    """True if the entry is low enough and high enough above the horizon."""
    val = item.get("alt_baro")
    if val is None or val == "ground":
        return False
    try:
        alt_ft = float(val)
    except (TypeError, ValueError):
        return False
    if alt_ft > THRESHOLD:
        return False
    # If we know the distance, require a minimum angle above the horizon so
    # far-but-low traffic sitting on the skyline is filtered out. If distance
    # is unknown, don't exclude it on that basis.
    dst = item.get("dst")
    if isinstance(dst, (int, float)):
        if elevation_deg(alt_ft, float(dst)) < MIN_ELEVATION_DEG:
            return False
    return True


def format_message(item):
    label = (item.get("flight") or "").strip() or item.get("hex", "?")
    parts = [label]

    val = item.get("alt_baro")
    if isinstance(val, (int, float)):
        parts.append(f"{int(round(val)):,}ft")

    # Where to look: distance plus the compass bearing from the viewing point.
    dst = item.get("dst")
    if isinstance(dst, (int, float)):
        seg = f"{dst:.1f}nm"
        bearing = item.get("dir")
        if isinstance(bearing, (int, float)):
            seg += f" {compass(bearing)}"
        parts.append(seg)

    # Where it's going: its track over the ground.
    track = item.get("track")
    if isinstance(track, (int, float)):
        parts.append(f"heading {compass(track)}")

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
        if not visible(item):
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
