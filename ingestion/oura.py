"""
Oura data ingestion pipeline.
Pulls sleep, readiness, activity, and workouts from the Oura v2 API
and upserts into Postgres.
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
    records = fetch_range(client, "/daily_sleep", start_date, end_date)
    print(f"  Oura sleep: {len(records)} records")
    for r in records:
        contributors = r.get("contributors", {})
        stmt = pg_insert(OuraSleep).values(
            id=r["id"],
            day=r["day"],
            bedtime_start=r.get("bedtime_start"),
            bedtime_end=r.get("bedtime_end"),
            total_sleep_duration=r.get("total_sleep_duration"),
            awake_time=r.get("awake_time"),
            light_sleep_duration=r.get("light_sleep_duration"),
            deep_sleep_duration=r.get("deep_sleep_duration"),
            rem_sleep_duration=r.get("rem_sleep_duration"),
            time_in_bed=r.get("time_in_bed"),
            score=r.get("score"),
            efficiency=contributors.get("efficiency"),
            latency=contributors.get("latency"),
            restfulness=contributors.get("restfulness"),
            average_hrv=r.get("average_hrv"),
            lowest_heart_rate=r.get("lowest_heart_rate"),
            average_heart_rate=r.get("average_heart_rate"),
            average_breath=r.get("average_breath"),
            contributors=contributors,
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"score": r.get("score"), "contributors": contributors}
        )
        session.execute(stmt)
    session.commit()


def ingest_readiness(client: httpx.Client, session: Session, start_date: str, end_date: str):
    records = fetch_range(client, "/daily_readiness", start_date, end_date)
    print(f"  Oura readiness: {len(records)} records")
    for r in records:
        contributors = r.get("contributors", {})
        stmt = pg_insert(OuraReadiness).values(
            id=r["id"],
            day=r["day"],
            score=r.get("score"),
            temperature_deviation=r.get("temperature_deviation"),
            temperature_trend_deviation=r.get("temperature_trend_deviation"),
            contributors=contributors,
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"score": r.get("score"), "contributors": contributors}
        )
        session.execute(stmt)
    session.commit()


def ingest_activity(client: httpx.Client, session: Session, start_date: str, end_date: str):
    records = fetch_range(client, "/daily_activity", start_date, end_date)
    print(f"  Oura activity: {len(records)} records")
    for r in records:
        contributors = r.get("contributors", {})
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
            set_={"score": r.get("score"), "steps": r.get("steps")}
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


def run(start_date: Optional[str] = None, end_date: Optional[str] = None):
    today = date.today().isoformat()
    if not end_date:
        end_date = today
    if not start_date:
        # Default: last 30 days
        start_date = (date.today() - timedelta(days=30)).isoformat()

    engine = init_db(config.DATABASE_URL)
    with Session(engine) as session:
        client = get_client()
        print(f"Ingesting Oura data ({start_date} → {end_date})...")
        ingest_sleep(client, session, start_date, end_date)
        ingest_readiness(client, session, start_date, end_date)
        ingest_activity(client, session, start_date, end_date)
        ingest_workouts(client, session, start_date, end_date)
    print("✅ Oura ingestion complete.")


if __name__ == "__main__":
    # Usage: python oura.py [start_date] [end_date]  (YYYY-MM-DD)
    start = sys.argv[1] if len(sys.argv) > 1 else None
    end = sys.argv[2] if len(sys.argv) > 2 else None
    run(start, end)
