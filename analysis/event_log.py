"""
Life OS — Event Logger

Stores structured life events in Postgres. Parsing is handled by Zoe
(the OpenClaw agent) who receives messages first, extracts structure,
and calls log_event() with pre-parsed data.

For CLI/script use, a simple rule-based fallback parser handles basic cases.

Usage:
  # From Zoe (pre-parsed):
  from analysis.event_log import log_event
  log_event("had 2 espressos", category="caffeine", tags=["espresso","double-shot"],
            quantity=2, unit="shot", context={"mood": "wired"})

  # CLI (fallback parser):
  python analysis/event_log.py "had 2 beers last night"
  python analysis/event_log.py --list --days 7
  python analysis/event_log.py --list --category alcohol
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import re
import json
import argparse
import zoneinfo
from datetime import datetime, timezone, timedelta

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app_config as config
from db.models import Event, init_db

USER_TZ = "America/New_York"


# ─── TIME PARSING ─────────────────────────────────────────────────────────────

def resolve_time(time_ref: str | None, now: datetime) -> datetime:
    """Convert a natural language time reference to UTC datetime (ET-based)."""
    if not time_ref:
        return now

    local_tz = zoneinfo.ZoneInfo(USER_TZ)
    now_local = now.astimezone(local_tz)

    def local_at(hour, minute=0, day_offset=0) -> datetime:
        d = now_local + timedelta(days=day_offset)
        return d.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(timezone.utc)

    ref = time_ref.lower()

    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', ref)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        if m.group(3) == "pm" and hour != 12:
            hour += 12
        elif m.group(3) == "am" and hour == 12:
            hour = 0
        return local_at(hour, minute)

    if "noon" in ref:           return local_at(12)
    if "midnight" in ref:       return local_at(0)
    if "this morning" in ref:   return local_at(8)
    if "this afternoon" in ref: return local_at(14)
    if "this evening" in ref or "tonight" in ref: return local_at(19)
    if "last night" in ref:     return local_at(22, day_offset=-1)
    if "yesterday" in ref:      return local_at(12, day_offset=-1)
    if "earlier" in ref:        return now - timedelta(hours=2)

    return now


# ─── FALLBACK RULE PARSER (CLI only) ─────────────────────────────────────────

def _rule_parse(text: str) -> dict:
    """Simple rule-based fallback for CLI use. Zoe handles real parsing."""
    lower = text.lower()

    def match(words):
        return any(re.search(r'\b' + w + r's?\b', lower) for w in words)

    category = "other"
    for cat, words in [
        ("caffeine",   ["coffee", "espresso", "latte", "cappuccino", "matcha", "tea", "caffeine"]),
        ("alcohol",    ["beer", "wine", "whiskey", "vodka", "tequila", "gin", "rum", "drink", "alcohol"]),
        ("exercise",   ["run", "gym", "tennis", "workout", "walk", "swim", "bike", "yoga", "hiit", "lift", "hike"]),
        ("food",       ["ate", "meal", "lunch", "dinner", "breakfast", "snack", "fasted"]),
        ("sleep",      ["nap", "sleep", "bed", "melatonin"]),
        ("supplement", ["vitamin", "supplement", "creatine", "protein", "zinc", "magnesium"]),
        ("mood",       ["stressed", "anxious", "tired", "energized", "happy", "rough day"]),
    ]:
        if match(words):
            category = cat
            break

    # Extract time ref
    time_patterns = [
        r'\bat \d{1,2}(?::\d{2})?\s*(?:am|pm)\b',
        r'\baround \d{1,2}(?::\d{2})?\s*(?:am|pm)\b',
        r'\b(?:noon|midnight|this morning|this afternoon|this evening|tonight|last night|yesterday|earlier|just now)\b',
    ]
    time_ref = None
    for p in time_patterns:
        m = re.search(p, lower)
        if m:
            time_ref = m.group()
            break

    # Quantity
    qty_map = {"one": 1, "a ": 1, "an ": 1, "two": 2, "three": 3, "four": 4, "half": 0.5, "double": 2}
    quantity = None
    for word, val in qty_map.items():
        if word in lower:
            quantity = val
            break
    if quantity is None:
        m = re.search(r'\b(\d+\.?\d*)\b', lower)
        if m:
            quantity = float(m.group(1))

    tags = [category]
    tag_map = {
        "coffee": ["coffee", "drip"], "espresso": ["espresso"], "latte": ["latte", "milky"],
        "matcha": ["matcha"], "tea": ["tea"], "beer": ["beer"], "wine": ["wine"],
        "spirits": ["whiskey", "vodka", "tequila", "gin", "rum", "shot"],
        "tennis": ["tennis"], "running": ["run", "ran"], "walking": ["walk"],
        "gym": ["gym", "lift", "weight"], "cycling": ["bike", "cycl"],
        "morning": ["this morning"], "evening": ["tonight", "this evening"],
        "pre_sleep": ["before bed", "before sleep"], "last_night": ["last night"],
    }
    for tag, keywords in tag_map.items():
        if any(re.search(r'\b' + re.escape(k) + r's?\b', lower) for k in keywords):
            if tag not in tags:
                tags.append(tag)

    return {"category": category, "tags": tags, "quantity": quantity,
            "unit": None, "time_ref": time_ref, "context": {}}


# ─── MAIN LOGGER ──────────────────────────────────────────────────────────────

def log_event(
    raw_text: str,
    category: str = None,
    tags: list = None,
    quantity: float = None,
    unit: str = None,
    context: dict = None,
    occurred_at: datetime = None,
    source: str = "whatsapp",
    parsed_by: str = "zoe",
) -> dict:
    """
    Store a life log event.

    When called from Zoe (the agent), pass pre-parsed fields directly.
    When called from CLI, fields are parsed from raw_text via rule fallback.
    """
    now = datetime.now(timezone.utc)

    # If no structured fields provided, use rule parser (CLI path)
    if category is None and tags is None:
        parsed = _rule_parse(raw_text)
        category = parsed["category"]
        tags = parsed["tags"]
        quantity = quantity or parsed["quantity"]
        unit = unit or parsed["unit"]
        context = context or parsed["context"]
        if occurred_at is None:
            occurred_at = resolve_time(parsed.get("time_ref"), now)
        parsed_by = "rules"

    if occurred_at is None:
        occurred_at = now

    engine = init_db(config.DATABASE_URL)
    with Session(engine) as session:
        event = Event(
            occurred_at=occurred_at,
            raw_text=raw_text,
            category=category or "other",
            tags=tags or [],
            quantity=quantity,
            unit=unit,
            context=context or {},
            source=source,
            parsed_by=parsed_by,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        return {
            "id": event.id,
            "occurred_at": event.occurred_at.isoformat(),
            "category": event.category,
            "tags": event.tags,
            "quantity": event.quantity,
            "unit": event.unit,
            "context": event.context,
            "raw_text": event.raw_text,
            "parsed_by": event.parsed_by,
        }


def format_confirmation(event: dict) -> str:
    cat_emoji = {
        "caffeine": "☕", "alcohol": "🍺", "exercise": "🏃",
        "food": "🍽️", "sleep": "😴", "supplement": "💊",
        "mood": "🧠", "stress": "😤", "social": "🎉", "other": "📝",
    }
    emoji = cat_emoji.get(event["category"], "📝")
    tags = ", ".join(event["tags"]) if event["tags"] else "—"
    ctx = ""
    if event.get("context"):
        ctx = " · " + ", ".join(f"{k}: {v}" for k, v in event["context"].items() if v)
    return f"{emoji} Logged · {tags}{ctx}"


def get_events(days: int = 7, category: str = None) -> list:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    engine = create_engine(config.DATABASE_URL)
    with Session(engine) as session:
        q = "SELECT * FROM events WHERE occurred_at >= :since"
        params: dict = {"since": since}
        if category:
            q += " AND category = :cat"
            params["cat"] = category
        q += " ORDER BY occurred_at DESC"
        rows = session.execute(text(q), params).mappings().fetchall()
        return [dict(r) for r in rows]


# ─── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Life OS Event Logger")
    parser.add_argument("text", nargs="?", help="Event text to log")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--category", default=None)
    args = parser.parse_args()

    if args.list:
        events = get_events(days=args.days, category=args.category)
        if not events:
            print("No events found.")
        for e in events:
            ts = str(e["occurred_at"])[:16]
            print(f"{ts} | {e['category']:12} | {e['tags']} | {e['raw_text']}")
    elif args.text:
        result = log_event(args.text, source="manual")
        print(format_confirmation(result))
    else:
        parser.print_help()
