"""
Life OS — Health Data Fetcher
Outputs structured health data for AI analysis.

Called by Zoe (the OpenClaw agent) when Ashray asks for health insights.
Zoe runs this, reads the output, and provides the analysis directly.

Usage:
  python analysis/health.py                          # last 14 days, all sections
  python analysis/health.py --days 30                # 30-day window
  python analysis/health.py --section sleep          # sleep only
  python analysis/health.py --section recovery       # HRV + recovery
  python analysis/health.py --section workouts       # workouts only
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import argparse
import json
from datetime import date, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app_config as config


def query(days: int = 14, section: str = "all") -> dict:
    since = (date.today() - timedelta(days=days)).isoformat()
    engine = create_engine(config.DATABASE_URL)
    result = {"meta": {"days": days, "section": section, "since": since, "as_of": date.today().isoformat()}}

    with Session(engine) as session:

        if section in ("all", "sleep", "recovery"):
            rows = session.execute(text("""
                SELECT
                    ws.start::date as date,
                    ROUND(((ws.total_light_sleep_time_milli + ws.total_slow_wave_sleep_time_milli
                           + ws.total_rem_sleep_time_milli) / 3600000.0)::numeric, 2) as whoop_total_sleep_hrs,
                    ROUND((ws.total_in_bed_time_milli / 3600000.0)::numeric, 2) as time_in_bed_hrs,
                    ROUND((ws.total_slow_wave_sleep_time_milli / 3600000.0)::numeric, 2) as whoop_sws_hrs,
                    ROUND((ws.total_rem_sleep_time_milli / 3600000.0)::numeric, 2) as whoop_rem_hrs,
                    ws.disturbance_count,
                    ROUND(ws.sleep_performance_percentage::numeric, 1) as whoop_sleep_performance,
                    ROUND(ws.sleep_efficiency_percentage::numeric, 1) as whoop_sleep_efficiency,
                    ROUND(ws.respiratory_rate::numeric, 2) as whoop_resp_rate,
                    ROUND(wr.recovery_score::numeric, 1) as whoop_recovery_score,
                    ROUND(wr.resting_heart_rate::numeric, 1) as whoop_rhr,
                    ROUND(wr.hrv_rmssd_milli::numeric, 2) as whoop_hrv_ms,
                    ROUND(wr.spo2_percentage::numeric, 2) as whoop_spo2,
                    ROUND(wr.skin_temp_celsius::numeric, 2) as whoop_skin_temp_c
                FROM whoop_sleeps ws
                LEFT JOIN whoop_recoveries wr ON ws.cycle_id = wr.cycle_id
                WHERE ws.nap = false AND ws.start::date >= :since
                ORDER BY ws.start DESC
            """), {"since": since}).mappings().fetchall()
            result["whoop_sleep_recovery"] = [dict(r) for r in rows]

        if section in ("all", "sleep", "recovery"):
            rows = session.execute(text("""
                SELECT
                    os.day,
                    ROUND((os.total_sleep_duration / 3600.0)::numeric, 2) as oura_total_sleep_hrs,
                    ROUND((os.deep_sleep_duration / 3600.0)::numeric, 2) as oura_deep_hrs,
                    ROUND((os.rem_sleep_duration / 3600.0)::numeric, 2) as oura_rem_hrs,
                    ROUND((os.light_sleep_duration / 3600.0)::numeric, 2) as oura_light_hrs,
                    ROUND((os.awake_time / 3600.0)::numeric, 2) as oura_awake_hrs,
                    os.score as oura_sleep_score,
                    os.efficiency as oura_efficiency,
                    ROUND(os.average_hrv::numeric, 2) as oura_hrv_ms,
                    os.lowest_heart_rate as oura_rhr,
                    ROUND(os.average_breath::numeric, 2) as oura_resp_rate,
                    or2.score as oura_readiness_score,
                    ROUND(or2.temperature_deviation::numeric, 3) as temp_deviation_c,
                    os.contributors as sleep_contributors,
                    or2.contributors as readiness_contributors
                FROM oura_sleeps os
                LEFT JOIN oura_readiness or2 ON os.day = or2.day
                WHERE os.day >= :since
                ORDER BY os.day DESC
            """), {"since": since}).mappings().fetchall()
            result["oura_sleep_readiness"] = [dict(r) for r in rows]

        if section in ("all", "workouts"):
            rows = session.execute(text("""
                SELECT
                    start::date as date, sport_name,
                    ROUND(strain::numeric, 2) as strain,
                    average_heart_rate as avg_hr, max_heart_rate as max_hr,
                    ROUND((distance_meter / 1000.0)::numeric, 2) as distance_km,
                    ROUND(kilojoule::numeric, 1) as kilojoules,
                    zone_durations
                FROM whoop_workouts
                WHERE start::date >= :since
                ORDER BY start DESC
            """), {"since": since}).mappings().fetchall()
            result["whoop_workouts"] = [dict(r) for r in rows]

            rows = session.execute(text("""
                SELECT
                    day, activity, start_datetime, end_datetime,
                    ROUND(calories::numeric, 1) as calories,
                    ROUND(distance::numeric, 0) as distance_m,
                    intensity, average_heart_rate as avg_hr, max_heart_rate as max_hr
                FROM oura_workouts
                WHERE day >= :since
                ORDER BY day DESC
            """), {"since": since}).mappings().fetchall()
            result["oura_workouts"] = [dict(r) for r in rows]

        if section in ("all",):
            rows = session.execute(text("""
                SELECT
                    day, score as activity_score, steps, active_calories,
                    ROUND((high_activity_time / 60.0)::numeric, 1) as high_intensity_min,
                    ROUND((medium_activity_time / 60.0)::numeric, 1) as medium_intensity_min,
                    ROUND((sedentary_time / 3600.0)::numeric, 2) as sedentary_hrs
                FROM oura_activity
                WHERE day >= :since
                ORDER BY day DESC
            """), {"since": since}).mappings().fetchall()
            result["oura_activity"] = [dict(r) for r in rows]

    return json.loads(json.dumps(result, default=str))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Life OS — Health Data Fetcher")
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--section", default="all",
                        choices=["all", "sleep", "recovery", "workouts"])
    args = parser.parse_args()

    data = query(days=args.days, section=args.section)
    print(json.dumps(data, indent=2, default=str))
