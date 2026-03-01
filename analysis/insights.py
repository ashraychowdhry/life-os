"""
Life OS — Insights Engine

Runs periodically (weekly by default) to surface correlations between
self-reported events and biometric data from Whoop + Oura.

Questions it answers:
- Does alcohol the night before lower HRV the next morning?
- What's the average recovery score after exercise days vs rest days?
- Does caffeine timing correlate with sleep performance?
- Which tags correlate most with high/low readiness?

Uses Ollama (local LLM) to generate narrative insights from the query results.
Can also be triggered on-demand.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import argparse
import zoneinfo
import requests
from datetime import datetime, timezone, timedelta, date

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app_config as config
from notifications.whatsapp import send

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b"
USER_TZ = "America/New_York"


# ─── DATA QUERIES ─────────────────────────────────────────────────────────────

def get_event_health_correlations(session: Session, days: int = 90) -> dict:
    """
    For each event category, compute avg next-morning biometrics.
    Joins events → next day's Whoop recovery + Oura readiness.
    """
    since = (date.today() - timedelta(days=days)).isoformat()

    rows = session.execute(text("""
        SELECT
            e.category,
            e.tags,
            e.occurred_at::date as event_date,
            -- Next morning Whoop recovery
            wr.recovery_score as whoop_recovery,
            wr.hrv_rmssd_milli as whoop_hrv,
            wr.resting_heart_rate as whoop_rhr,
            -- Same night Whoop sleep
            ws.sleep_performance_percentage as whoop_sleep_perf,
            ws.total_rem_sleep_time_milli / 3600000.0 as whoop_rem_hrs,
            -- Oura next day
            or2.score as oura_readiness,
            os.score as oura_sleep_score,
            os.average_hrv as oura_hrv,
            os.lowest_heart_rate as oura_rhr
        FROM events e
        -- Join Whoop recovery for the NEXT day after event
        LEFT JOIN whoop_recoveries wr ON wr.cycle_id = (
            SELECT wc.id FROM whoop_cycles wc
            WHERE wc.start::date = e.occurred_at::date + INTERVAL '1 day'
            LIMIT 1
        )
        LEFT JOIN whoop_sleeps ws ON ws.cycle_id = wr.cycle_id AND ws.nap = false
        -- Join Oura for the next day
        LEFT JOIN oura_readiness or2 ON or2.day = (e.occurred_at::date + INTERVAL '1 day')::text
        LEFT JOIN oura_sleeps os ON os.day = (e.occurred_at::date + INTERVAL '1 day')::text
        WHERE e.occurred_at::date >= :since
        ORDER BY e.occurred_at DESC
    """), {"since": since}).mappings().fetchall()

    return [dict(r) for r in rows]


def get_category_averages(session: Session, days: int = 90) -> dict:
    """Average next-day metrics grouped by event category."""
    since = (date.today() - timedelta(days=days)).isoformat()

    rows = session.execute(text("""
        SELECT
            e.category,
            COUNT(*) as event_count,
            ROUND(AVG(wr.recovery_score)::numeric, 1) as avg_whoop_recovery,
            ROUND(AVG(wr.hrv_rmssd_milli)::numeric, 1) as avg_whoop_hrv,
            ROUND(AVG(or2.score)::numeric, 1) as avg_oura_readiness,
            ROUND(AVG(os.score)::numeric, 1) as avg_oura_sleep
        FROM events e
        LEFT JOIN whoop_recoveries wr ON wr.cycle_id = (
            SELECT wc.id FROM whoop_cycles wc
            WHERE wc.start::date = e.occurred_at::date + INTERVAL '1 day'
            LIMIT 1
        )
        LEFT JOIN oura_readiness or2 ON or2.day = (e.occurred_at::date + INTERVAL '1 day')::text
        LEFT JOIN oura_sleeps os ON os.day = (e.occurred_at::date + INTERVAL '1 day')::text
        WHERE e.occurred_at::date >= :since
        GROUP BY e.category
        HAVING COUNT(*) >= 2
        ORDER BY COUNT(*) DESC
    """), {"since": since}).mappings().fetchall()

    return [dict(r) for r in rows]


def get_baseline(session: Session, days: int = 90) -> dict:
    """Overall average biometrics (for comparison)."""
    since = (date.today() - timedelta(days=days)).isoformat()
    row = session.execute(text("""
        SELECT
            ROUND(AVG(recovery_score)::numeric, 1) as avg_recovery,
            ROUND(AVG(hrv_rmssd_milli)::numeric, 1) as avg_hrv,
            ROUND(AVG(resting_heart_rate)::numeric, 1) as avg_rhr
        FROM whoop_recoveries wr
        JOIN whoop_cycles wc ON wc.id = wr.cycle_id
        WHERE wc.start::date >= :since
    """), {"since": since}).mappings().fetchone()
    return dict(row) if row else {}


def get_recent_events_summary(session: Session, days: int = 7) -> list:
    """Recent raw events for weekly summary context."""
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = session.execute(text("""
        SELECT occurred_at AT TIME ZONE 'America/New_York' as occurred_et,
               category, tags, quantity, unit, raw_text, context
        FROM events
        WHERE occurred_at::date >= :since
        ORDER BY occurred_at DESC
    """), {"since": since}).mappings().fetchall()
    return [dict(r) for r in rows]


# ─── OLLAMA INSIGHTS ──────────────────────────────────────────────────────────

def generate_insights(data: dict) -> str:
    """
    Ask Ollama to generate narrative insights from the correlation data.
    Runs on the weekly job — latency is acceptable here (2-3 min on VM CPU).
    """
    prompt = f"""You are a personal health analyst for Ashray. Analyze this data and generate sharp, specific insights.

BASELINE BIOMETRICS (overall averages):
{json.dumps(data['baseline'], indent=2, default=str)}

NEXT-DAY BIOMETRICS BY EVENT CATEGORY:
(Shows how each type of event correlates with the following day's recovery metrics)
{json.dumps(data['category_averages'], indent=2, default=str)}

RECENT EVENTS (last 7 days):
{json.dumps(data['recent_events'][:20], indent=2, default=str)}

Generate a weekly insight report covering:
1. Most impactful patterns you see (compare category averages to baseline)
2. What Ashray should do more/less of based on the data
3. Any notable patterns from this past week
4. One specific experiment to try next week to learn more

Keep it under 300 words. Be direct and specific with numbers. Skip generic advice.
If there's insufficient event data for correlations, say so honestly and focus on what you can see."""

    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        return f"Ollama unavailable: {e}"


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def run(days: int = 90, notify: bool = True, dry_run: bool = False) -> str:
    engine = create_engine(config.DATABASE_URL)

    with Session(engine) as session:
        data = {
            "baseline": get_baseline(session, days),
            "category_averages": get_category_averages(session, days),
            "recent_events": get_recent_events_summary(session, 7),
        }

    # Check if we have enough event data
    if not data["category_averages"]:
        msg = "📊 *Weekly Insights*\n\nNot enough logged events yet to surface correlations. Keep logging — insights improve with more data."
    else:
        narrative = generate_insights(data)
        msg = f"📊 *Weekly Health Insights*\n\n{narrative}"

    if dry_run:
        print(msg)
        return msg

    if notify:
        send(msg)

    return msg


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="Days of history to analyze")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args()

    run(days=args.days, notify=not args.no_notify, dry_run=args.dry_run)
