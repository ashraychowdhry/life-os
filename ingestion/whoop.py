"""
Whoop data ingestion pipeline.
Pulls cycles, sleep, recovery, and workouts from the Whoop API
and upserts into Postgres.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import json
import time
from datetime import datetime, timezone
from typing import Optional
import httpx
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

import app_config as config
from db.models import WhoopCycle, WhoopSleep, WhoopRecovery, WhoopWorkout, init_db

TOKEN_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".whoop_token.json")


def load_token() -> dict:
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError("No Whoop token found. Run scripts/whoop_auth.py first.")
    with open(TOKEN_FILE) as f:
        return json.load(f)


def refresh_token_if_needed(token_data: dict) -> dict:
    """Refresh access token using refresh_token if expired."""
    # Simple check: try refresh if we have a refresh token
    if "refresh_token" not in token_data:
        return token_data

    resp = httpx.post(config.WHOOP_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": token_data["refresh_token"],
            "client_id": config.WHOOP_CLIENT_ID,
            "client_secret": config.WHOOP_CLIENT_SECRET,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    if resp.status_code == 200:
        new_token = resp.json()
        with open(TOKEN_FILE, "w") as f:
            json.dump(new_token, f, indent=2)
        return new_token
    return token_data


def get_client(version: str = "v2") -> httpx.Client:
    token_data = load_token()
    token_data = refresh_token_if_needed(token_data)
    base = config.WHOOP_BASE_URL if version == "v2" else config.WHOOP_BASE_URL_V1
    return httpx.Client(
        headers={"Authorization": f"Bearer {token_data['access_token']}"},
        base_url=base,
        timeout=30,
    )


def paginate(client: httpx.Client, endpoint: str, params: dict = {}) -> list:
    """Fetch all pages from a paginated Whoop endpoint."""
    records = []
    next_token = None
    while True:
        p = {**params, "limit": 25}
        if next_token:
            p["nextToken"] = next_token
        resp = client.get(endpoint, params=p)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))
        next_token = data.get("next_token")
        if not next_token:
            break
    return records


def ingest_cycles(client: httpx.Client, session: Session, since: Optional[str] = None):
    params = {}
    if since:
        params["start"] = since
    records = paginate(client, "/cycle", params)
    print(f"  Whoop cycles: {len(records)} records")
    for r in records:
        score = r.get("score") or {}
        stmt = pg_insert(WhoopCycle).values(
            id=r["id"],
            user_id=r["user_id"],
            start=r["start"],
            end=r.get("end"),
            timezone_offset=r.get("timezone_offset"),
            score_state=r.get("score_state"),
            strain=score.get("strain"),
            kilojoule=score.get("kilojoule"),
            average_heart_rate=score.get("average_heart_rate"),
            max_heart_rate=score.get("max_heart_rate"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"updated_at": r["updated_at"], "score_state": r.get("score_state"),
                  "strain": score.get("strain"), "end": r.get("end")}
        )
        session.execute(stmt)
    session.commit()


def ingest_sleeps(client: httpx.Client, session: Session, since: Optional[str] = None):
    params = {}
    if since:
        params["start"] = since
    records = paginate(client, "/activity/sleep", params)
    print(f"  Whoop sleeps: {len(records)} records")
    for r in records:
        score = r.get("score") or {}
        stages = score.get("stage_summary") or {}
        needed = score.get("sleep_needed") or {}
        stmt = pg_insert(WhoopSleep).values(
            id=r["id"],
            cycle_id=r.get("cycle_id"),
            user_id=r["user_id"],
            start=r["start"],
            end=r.get("end"),
            nap=r.get("nap", False),
            score_state=r.get("score_state"),
            total_in_bed_time_milli=stages.get("total_in_bed_time_milli"),
            total_awake_time_milli=stages.get("total_awake_time_milli"),
            total_light_sleep_time_milli=stages.get("total_light_sleep_time_milli"),
            total_slow_wave_sleep_time_milli=stages.get("total_slow_wave_sleep_time_milli"),
            total_rem_sleep_time_milli=stages.get("total_rem_sleep_time_milli"),
            sleep_cycle_count=stages.get("sleep_cycle_count"),
            disturbance_count=stages.get("disturbance_count"),
            respiratory_rate=score.get("respiratory_rate"),
            sleep_performance_percentage=score.get("sleep_performance_percentage"),
            sleep_consistency_percentage=score.get("sleep_consistency_percentage"),
            sleep_efficiency_percentage=score.get("sleep_efficiency_percentage"),
            baseline_milli=needed.get("baseline_milli"),
            need_from_sleep_debt_milli=needed.get("need_from_sleep_debt_milli"),
            need_from_recent_strain_milli=needed.get("need_from_recent_strain_milli"),
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"score_state": r.get("score_state"),
                  "sleep_performance_percentage": score.get("sleep_performance_percentage")}
        )
        session.execute(stmt)
    session.commit()


def ingest_recoveries(client: httpx.Client, session: Session, since: Optional[str] = None):
    params = {}
    if since:
        params["start"] = since
    records = paginate(client, "/recovery", params)
    print(f"  Whoop recoveries: {len(records)} records")
    for r in records:
        score = r.get("score") or {}
        stmt = pg_insert(WhoopRecovery).values(
            cycle_id=r["cycle_id"],
            sleep_id=r.get("sleep_id"),
            user_id=r["user_id"],
            score_state=r.get("score_state"),
            user_calibrating=score.get("user_calibrating"),
            recovery_score=score.get("recovery_score"),
            resting_heart_rate=score.get("resting_heart_rate"),
            hrv_rmssd_milli=score.get("hrv_rmssd_milli"),
            spo2_percentage=score.get("spo2_percentage"),
            skin_temp_celsius=score.get("skin_temp_celsius"),
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        ).on_conflict_do_update(
            index_elements=["cycle_id"],
            set_={"recovery_score": score.get("recovery_score"),
                  "score_state": r.get("score_state")}
        )
        session.execute(stmt)
    session.commit()


def ingest_workouts(client: httpx.Client, session: Session, since: Optional[str] = None):
    params = {}
    if since:
        params["start"] = since
    records = paginate(client, "/activity/workout", params)
    print(f"  Whoop workouts: {len(records)} records")
    for r in records:
        score = r.get("score") or {}
        stmt = pg_insert(WhoopWorkout).values(
            id=r["id"],
            user_id=r["user_id"],
            start=r["start"],
            end=r.get("end"),
            sport_name=r.get("sport_name"),
            sport_id=r.get("sport_id"),
            score_state=r.get("score_state"),
            strain=score.get("strain"),
            average_heart_rate=score.get("average_heart_rate"),
            max_heart_rate=score.get("max_heart_rate"),
            kilojoule=score.get("kilojoule"),
            distance_meter=score.get("distance_meter"),
            altitude_gain_meter=score.get("altitude_gain_meter"),
            zone_durations=score.get("zone_durations"),
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={"score_state": r.get("score_state"), "strain": score.get("strain")}
        )
        session.execute(stmt)
    session.commit()


def run(since: Optional[str] = None):
    engine = init_db(config.DATABASE_URL)
    with Session(engine) as session:
        client_v1 = get_client("v1")
        client_v2 = get_client("v2")
        print("Ingesting Whoop data...")
        ingest_cycles(client_v1, session, since)
        ingest_sleeps(client_v2, session, since)
        ingest_recoveries(client_v2, session, since)
        ingest_workouts(client_v2, session, since)
    print("✅ Whoop ingestion complete.")


if __name__ == "__main__":
    # Optionally pass a start date: python whoop.py 2024-01-01T00:00:00Z
    since = sys.argv[1] if len(sys.argv) > 1 else None
    run(since)
