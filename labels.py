"""Task labels (e.g. a project or client name): names and colours, shared by the app and the PDF report."""

import json
import zlib

PALETTE = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#db2777",
           "#0891b2", "#dc2626", "#4f46e5", "#65a30d", "#64748b"]
DARK_CARD = "#232629"


def parse(raw):
    """Labels from the settings value: a JSON list of {"name", "color"}."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return [{"name": d["name"].strip(), "color": d["color"]} for d in data or [] if d["name"].strip()]
    except (ValueError, TypeError, KeyError, AttributeError):
        return []


def dumps(labels):
    return json.dumps(labels)


def color_of(name, labels):
    for label in labels:
        if label["name"] == name:
            return label["color"]
    # A label that was removed from the list keeps a stable colour.
    return PALETTE[zlib.crc32(name.encode()) % len(PALETTE)]


def next_color(labels):
    used = {label["color"] for label in labels}
    return next((c for c in PALETTE if c not in used), PALETTE[len(labels) % len(PALETTE)])


def _mix(color, other, t):
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def chip(color, dark=False):
    """(background, hover, text) colours of a label chip: a soft tint with strong text."""
    if dark:
        return _mix(color, DARK_CARD, 0.5), _mix(color, DARK_CARD, 0.38), _mix(color, "#ffffff", 0.75)
    return _mix(color, "#ffffff", 0.86), _mix(color, "#ffffff", 0.76), _mix(color, "#000000", 0.32)


def items(rows):
    """Task rows as [{"text", "label"}]. Older drafts stored plain strings."""
    out = []
    for row in rows or []:
        if isinstance(row, str):
            row = {"text": row, "label": ""}
        text = (row.get("text") or "").strip()
        if text:
            out.append({"text": text, "label": (row.get("label") or "").strip()})
    return out
