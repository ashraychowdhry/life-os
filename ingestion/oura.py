"""
Oura data ingestion pipeline.
Pulls from Oura v2 API and upserts into Postgres.

Two sleep endpoints:
  - /daily_sleep    → scores + contributors (aggregated per day)
  - /sleep          → individual sleep periods with HRV, RHR, respiratory rate
                      We store the primary "long_sleep" period per night for biometrics,
                      and merge with daily_sleep scores.

Run manually:
  python ingestion/oura.py [start_date] [end_date]  (YYYY-MM-DD)
  Defaults to last 30 days if no args given.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, timedelta
from typing import Optional
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

import app_config as config
from db.models import OuraSleep, OuraReadiness, OuraActivity, OuraWorkout, init_db


def get_client() -> httpx.Client:
    if not config.OURA_PERSONAL_ACCESS_TOKEN:
        raise ValueError("OURA_PERSONAL_ACCESS_TOKEN not set in .env")
    return httpx.Client(
        headers={"Authorization": f"Bearer {config.OURA_PERSONAL_ACCESS_TOKEN}"},
        base_url=config.OURA_BASE_URL,
        timeout=30,
    )


def fetch_range(client: httpx.Client, endpoint: str, start_date: str, end_date: str) -> list:
    resp = client.get(endpoint, params={"start_date": start_date, "end_date": end_date})
    resp.raise_for_status()
    return resp.json().get("data", [])


def ingest_sleep(client: httpx.Client, session: Session, start_date: str, end_date: str):
    """
    Merge /daily_sleep (scores/contributors) with /sleep (biometrics).

    /daily_sleep gives us: score, efficiency sub-scores, contributors
    /sleep gives us: HRV, RHR, respiratory rate, exact stage durations

    Strategy: for each day, find the primary sleep period (type="long_sleep",
    or fallback to whichever has the longest duration). Merge both sources
    into OuraSleep row, upserted by the daily_sleep ID.
    """
    daily = fetch_range(client, "/daily_sleep", start_date, end_date)
    periods = fetch_range(client, "/sleep", start_date, end_date)

    # Index sleep periods by day → pick the primary one (long_sleep > others, then by duration)
    def period_priority(p):
        type_rank = {"long_sleep": 0, "sleep": 1, "late_nap": 2, "rest": 3}
        return (type_rank.get(p.get("type", "sleep"), 9), -(p.get("total_sleep_duration") or 0))

    periods_by_day: dict[str, dict] = {}
    for p in periods:
        day = p["day"]
        if day not in periods_by_day or period_priority(p) < period_priority(periods_by_day[day]):
            periods_by_day[day] = p

    print(f"  Oura sleep: {len(daily)} daily records, {len(periods)} sleep periods")

    for r in daily:
        day = r["day"]
        contributors = r.get("contributors") or {}
        primary = periods_by_day.get(day, {})

        stmt = pg_insert(OuraSleep).values(
            id=r["id"],
            day=day,
            bedtime_start=primary.get("bedtime_start"),
            bedtime_end=primary.get("bedtime_end"),
            total_sleep_duration=primary.get("total_sleep_duration") or r.get("total_sleep_duration"),
            awake_time=primary.get("awake_time"),
            light_sleep_duration=primary.get("light_sleep_duration"),
            deep_sleep_duration=primary.get("deep_sleep_duration"),
            rem_sleep_duration=primary.get("rem_sleep_duration"),
            time_in_bed=primary.get("time_in_bed"),
            score=r.get("score"),
            efficiency=contributors.get("efficiency"),
            latency=contributors.get("latency"),
            restfulness=contributors.get("restfulness"),
            # Biometrics from /sleep periods
            average_hrv=primary.get("average_hrv"),
            lowest_heart_rate=primary.get("lowest_heart_rate"),
            average_heart_rate=primary.get("average_heart_rate") or None,
            average_breath=primary.get("average_breath"),
            contributors=contributors,
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={
                "score": r.get("score"),
                "contributors": contributors,
                "average_hrv": primary.get("average_hrv"),
                "lowest_heart_rate": primary.get("lowest_heart_rate"),
                "average_heart_rate": primary.get("average_heart_rate") or None,
                "average_breath": primary.get("average_breath"),
                "bedtime_start": primary.get("bedtime_start"),
                "bedtime_end": primary.get("bedtime_end"),
                "total_sleep_duration": primary.get("total_sleep_duration") or r.get("total_sleep_duration"),
                "awake_time": primary.get("awake_time"),
                "light_sleep_duration": primary.get("light_sleep_duration"),
                "deep_sleep_duration": primary.get("deep_sleep_duration"),
                "rem_sleep_duration": primary.get("rem_sleep_duration"),
                "time_in_bed": primary.get("time_in_bed"),
            }
        )
        session.execute(stmt)
    session.commit()


def ingest_readiness(client: httpx.Client, session: Session, start_date: str, end_date: str):
    records = fetch_range(client, "/daily_readiness", start_date, end_date)
    print(f"  Oura readiness: {len(records)} records")
    for r in records:
        contributors = r.get("contributors") or {}
        stmt = pg_insert(OuraReadiness).values(
            id=r["id"],
            day=r["day"],
            score=r.get("score"),
            temperature_deviation=r.get("temperature_deviation"),
            temperature_trend_deviation=r.get("temperature_trend_deviation"),
            contributors=contributors,
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"score": r.get("score"), "contributors": contributors,
                  "temperature_deviation": r.get("temperature_deviation")}
        )
        session.execute(stmt)
    session.commit()


def ingest_activity(client: httpx.Client, session: Session, start_date: str, end_date: str):
    records = fetch_range(client, "/daily_activity", start_date, end_date)
    print(f"  Oura activity: {len(records)} records")
    for r in records:
        contributors = r.get("contributors") or {}
        stmt = pg_insert(OuraActivity).values(
            id=r["id"],
            day=r["day"],
            score=r.get("score"),
            active_calories=r.get("active_calories"),
            total_calories=r.get("total_calories"),
            steps=r.get("steps"),
            equivalent_walking_distance=r.get("equivalent_walking_distance"),
            high_activity_time=r.get("high_activity_time"),
            medium_activity_time=r.get("medium_activity_time"),
            low_activity_time=r.get("low_activity_time"),
            sedentary_time=r.get("sedentary_time"),
            resting_time=r.get("resting_time"),
            contributors=contributors,
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"score": r.get("score"), "steps": r.get("steps"),
                  "active_calories": r.get("active_calories")}
        )
        session.execute(stmt)
    session.commit()


def ingest_workouts(client: httpx.Client, session: Session, start_date: str, end_date: str):
    records = fetch_range(client, "/workout", start_date, end_date)
    print(f"  Oura workouts: {len(records)} records")
    for r in records:
        stmt = pg_insert(OuraWorkout).values(
            id=r["id"],
            day=r["day"],
            activity=r.get("activity"),
            start_datetime=r.get("start_datetime"),
            end_datetime=r.get("end_datetime"),
            calories=r.get("calories"),
            distance=r.get("distance"),
            intensity=r.get("intensity"),
            source=r.get("source"),
            average_heart_rate=r.get("average_heart_rate"),
            max_heart_rate=r.get("max_heart_rate"),
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"calories": r.get("calories"), "distance": r.get("distance")}
        )
        session.execute(stmt)
    session.commit()


def run(start_date: Optional[str] = None, end_date: Optional[str] = None,
        chunk_days: int = 90):
    """
    Run full ingestion. Chunks requests into 90-day windows to avoid
    Oura API timeouts on large date ranges.
    """
    today = date.today()
    end = date.fromisoformat(end_date) if end_date else today
    start = date.fromisoformat(start_date) if start_date else today - timedelta(days=30)

    engine = init_db(config.DATABASE_URL)

    # Chunk into 90-day windows
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        chunks.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)

    print(f"Ingesting Oura data ({start} → {end}) in {len(chunks)} chunk(s)...")

    with Session(engine) as session:
        client = get_client()
        for i, (s, e) in enumerate(chunks, 1):
            print(f"\n  Chunk {i}/{len(chunks)}: {s} → {e}")
            ingest_sleep(client, session, s, e)
            ingest_readiness(client, session, s, e)
            ingest_activity(client, session, s, e)
            ingest_workouts(client, session, s, e)

    print("\n✅ Oura ingestion complete.")


if __name__ == "__main__":
    start = sys.argv[1] if len(sys.argv) > 1 else None
    end = sys.argv[2] if len(sys.argv) > 2 else None
    run(start, end)
