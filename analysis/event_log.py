"""
Personal event logger — parses natural language log entries from Ashray
and stores structured events in the DB.

Called by Zoe when a WhatsApp/Telegram message looks like a life log entry.

Examples of input:
  "I just drank a coffee"
  "just had 2 beers"
  "played tennis for an hour"
  "drank a milky latte"
  "took a melatonin"
  "had a big meal"
  "went for a 5km run"

Parsing logic lives here. Zoe calls log_event(text, source) after detecting
the message is a log entry (not a question or command).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import re
import argparse
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

import app_config as config
from db.models import Event, init_db


# ─── CATEGORY RULES ──────────────────────────────────────────────────────────
# Order matters — first match wins

CATEGORY_RULES = [
    ("caffeine", [
        "coffee", "espresso", "latte", "cappuccino", "americano",
        "cold brew", "energy drink", "red bull", "monster", "pre-workout",
        "caffeine", "matcha", "tea",
    ]),
    ("alcohol", [
        "beer", "wine", "whiskey", "whisky", "vodka", "tequila", "gin",
        "rum", "sake", "cocktail", "drink", "drinks", "shot", "shots",
        "alcohol", "drunk", "booze", "drinking",
    ]),
    ("exercise", [
        "tennis", "gym", "run", "running", "ran", "walk", "walked", "walking",
        "bike", "biked", "cycling", "swim", "swam", "swimming", "yoga",
        "lift", "lifting", "workout", "hiit", "basketball", "soccer",
        "football", "golf", "hike", "hiking", "played", "training",
        "trail", "weights", "crossfit",
    ]),
    ("food", [
        "ate", "eaten", "meal", "lunch", "dinner", "breakfast", "snack",
        "pizza", "burger", "sushi", "salad", "chicken", "pasta", "rice",
        "fasted", "fasting", "cheat meal",
    ]),
    ("sleep", [
        "nap", "napped", "slept", "sleep", "bed", "melatonin", "magnesium",
        "sleeping pill", "ambien",
    ]),
    ("supplement", [
        "vitamin", "supplement", "creatine", "protein", "omega",
        "zinc", "magnesium", "ashwagandha", "melatonin",
    ]),
    ("stress", [
        "stressed", "anxious", "anxiety", "panic", "overwhelmed",
        "rough day", "bad day", "tough day",
    ]),
    ("social", [
        "party", "out late", "stayed up", "friends", "social",
    ]),
]

# Tag extraction — broader than categories
TAG_KEYWORDS = {
    # Caffeine types
    "coffee": ["coffee", "drip", "pour over", "black coffee"],
    "espresso": ["espresso", "double shot", "single shot"],
    "latte": ["latte", "milky", "flat white", "cortado"],
    "matcha": ["matcha"],
    "tea": ["tea", "green tea", "black tea"],
    "energy_drink": ["red bull", "monster", "energy drink", "bang"],
    # Alcohol types
    "beer": ["beer", "lager", "ipa", "ale", "pint"],
    "wine": ["wine", "red wine", "white wine", "rosé", "champagne"],
    "spirits": ["whiskey", "whisky", "vodka", "tequila", "gin", "rum", "shot"],
    "cocktail": ["cocktail", "mixed drink", "margarita", "mojito"],
    # Exercise
    "tennis": ["tennis"],
    "running": ["run", "running", "ran", "jog", "jogging"],
    "walking": ["walk", "walked", "walking"],
    "gym": ["gym", "lift", "weights", "lifting", "strength"],
    "cycling": ["bike", "biked", "cycling", "cycle"],
    "swimming": ["swim", "swam", "swimming"],
    "yoga": ["yoga"],
    "hiit": ["hiit", "crossfit"],
    # Food
    "large_meal": ["big meal", "large meal", "heavy meal", "feast", "overate"],
    "fasted": ["fasted", "fasting", "skipped meal", "no breakfast"],
    # Timing
    "morning": ["morning", "woke up", "after waking"],
    "evening": ["evening", "tonight", "after dinner", "night"],
    "pre_sleep": ["before bed", "before sleep", "bedtime"],
    "pre_workout": ["pre-workout", "before workout", "before gym"],
    "post_workout": ["after workout", "after gym", "post workout"],
}

TIME_PATTERNS = [
    # Specific times: "at 3pm", "at 14:30", "around 9am"
    (r'\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', "specific"),
    (r'\baround\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', "specific"),
    # Named times
    (r'\bnoon\b', "noon"),
    (r'\bmidnight\b', "midnight"),
    (r'\bthis morning\b', "morning"),
    (r'\bthis evening\b', "evening"),
    (r'\btonight\b', "evening"),
    (r'\blast night\b', "last_night"),
    (r'\bearlier today\b', "earlier"),
    (r'\bjust now\b', "now"),
    (r'\bjust\b', "now"),
]

USER_TZ = "America/Los_Angeles"

def parse_time_reference(text: str, now: datetime) -> datetime:
    """
    Extract a time reference from text and return the correct datetime.
    All named times (noon, morning, etc.) are interpreted in the user's local timezone.
    Defaults to now if no time reference found.
    """
    import zoneinfo
    lower = text.lower()
    local_tz = zoneinfo.ZoneInfo(USER_TZ)
    now_local = now.astimezone(local_tz)

    def local_at(hour, minute=0) -> datetime:
        return now_local.replace(hour=hour, minute=minute, second=0, microsecond=0).astimezone(timezone.utc)

    # Specific time: "at 3pm", "at 14:30"
    m = re.search(r'\b(?:at|around)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b', lower)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2)) if m.group(2) else 0
        meridiem = m.group(3)
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return local_at(hour, minute)

    if re.search(r'\bnoon\b', lower):
        return local_at(12, 0)
    if re.search(r'\bmidnight\b', lower):
        return local_at(0, 0)
    if re.search(r'\bthis morning\b', lower):
        return local_at(8, 0)
    if re.search(r'\b(this evening|tonight)\b', lower):
        return local_at(19, 0)
    if re.search(r'\blast night\b', lower):
        yesterday_local = now_local - timedelta(days=1)
        return yesterday_local.replace(hour=22, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    if re.search(r'\bearlier\b', lower):
        return now - timedelta(hours=2)

    return now  # default: right now

QUANTITY_PATTERNS = [
    (r'\b(a|an|one)\b', 1.0),
    (r'\b(two|2)\b', 2.0),
    (r'\b(three|3)\b', 3.0),
    (r'\b(four|4)\b', 4.0),
    (r'\b(half)\b', 0.5),
    (r'\b(double)\b', 2.0),
    (r'\b(triple)\b', 3.0),
    (r'\b(\d+\.?\d*)\b', None),  # numeric — captured as float
]

UNIT_PATTERNS = [
    (r'\bcup[s]?\b', "cup"),
    (r'\bglass(?:es)?\b', "glass"),
    (r'\bbottle[s]?\b', "bottle"),
    (r'\bpint[s]?\b', "pint"),
    (r'\bshot[s]?\b', "shot"),
    (r'\bdrink[s]?\b', "drink"),
    (r'\bhour[s]?\b', "hour"),
    (r'\bminute[s]?\b', "minute"),
    (r'\bkm[s]?\b', "km"),
    (r'\bmile[s]?\b', "mile"),
    (r'\bgram[s]?\b', "gram"),
    (r'\bmg\b', "mg"),
]


def parse_event(text: str) -> dict:
    """
    Parse a natural language log entry into structured fields.
    Returns dict with: category, tags, quantity, unit, notes
    """
    lower = text.lower()

    # Category
    def kw_match(text: str, keyword: str) -> bool:
        """Match keyword with optional plural s/es and word boundaries."""
        pattern = r'\b' + re.escape(keyword) + r's?\b'
        return bool(re.search(pattern, text))

    category = "other"
    for cat, keywords in CATEGORY_RULES:
        if any(kw_match(lower, kw) for kw in keywords):
            category = cat
            break

    # Tags — use word boundaries to avoid substring false positives ("drank" ≠ "ran")
    tags = set()
    tags.add(category)
    for tag, keywords in TAG_KEYWORDS.items():
        if any(kw_match(lower, kw) for kw in keywords):
            tags.add(tag)

    # Quantity
    quantity = None
    for pattern, value in QUANTITY_PATTERNS:
        m = re.search(pattern, lower)
        if m:
            if value is not None:
                quantity = value
            else:
                try:
                    quantity = float(m.group(1))
                except ValueError:
                    pass
            break

    # Unit
    unit = None
    for pattern, u in UNIT_PATTERNS:
        if re.search(pattern, lower):
            unit = u
            break

    return {
        "category": category,
        "tags": sorted(tags),
        "quantity": quantity,
        "unit": unit,
    }


def log_event(text: str, source: str = "whatsapp",
              occurred_at: datetime = None) -> dict:
    """
    Parse and store a life log event. Returns the stored record.
    """
    now = datetime.now(timezone.utc)
    if occurred_at is None:
        occurred_at = parse_time_reference(text, now)

    parsed = parse_event(text)
    engine = init_db(config.DATABASE_URL)

    with Session(engine) as session:
        event = Event(
            occurred_at=occurred_at,
            raw_text=text,
            category=parsed["category"],
            tags=parsed["tags"],
            quantity=parsed["quantity"],
            unit=parsed["unit"],
            source=source,
        )
        session.add(event)
        session.commit()
        session.refresh(event)
        result = {
            "id": event.id,
            "occurred_at": event.occurred_at.isoformat(),
            "category": event.category,
            "tags": event.tags,
            "quantity": event.quantity,
            "unit": event.unit,
            "raw_text": event.raw_text,
        }

    return result


def get_events(days: int = 7, category: str = None) -> list:
    """Fetch recent events, optionally filtered by category."""
    from datetime import timedelta
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    engine = create_engine(config.DATABASE_URL)
    with Session(engine) as session:
        q = "SELECT * FROM events WHERE occurred_at >= :since"
        params = {"since": since}
        if category:
            q += " AND category = :cat"
            params["cat"] = category
        q += " ORDER BY occurred_at DESC"
        rows = session.execute(text(q), params).mappings().fetchall()
        return [dict(r) for r in rows]


def format_confirmation(event: dict) -> str:
    """Format a friendly confirmation message."""
    cat_emoji = {
        "caffeine": "☕",
        "alcohol": "🍺",
        "exercise": "🏃",
        "food": "🍽️",
        "sleep": "😴",
        "supplement": "💊",
        "stress": "😤",
        "social": "🎉",
        "other": "📝",
    }
    emoji = cat_emoji.get(event["category"], "📝")
    qty = f"{event['quantity']:.0f} " if event["quantity"] else ""
    unit = f"{event['unit']} " if event["unit"] else ""
    tags = ", ".join(t for t in event["tags"] if t != event["category"])

    msg = f"{emoji} Logged: {event['raw_text']}"
    if tags:
        msg += f"\nTags: {tags}"
    return msg


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("text", nargs="?", help="Event text to log")
    parser.add_argument("--list", action="store_true", help="List recent events")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--category", default=None)
    args = parser.parse_args()

    if args.list:
        events = get_events(days=args.days, category=args.category)
        for e in events:
            print(f"{e['occurred_at'][:16]} | {e['category']:12} | {e['raw_text']}")
    elif args.text:
        result = log_event(args.text)
        print(format_confirmation(result))
    else:
        parser.print_help()
