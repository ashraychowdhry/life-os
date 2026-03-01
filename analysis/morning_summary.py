"""
Morning health summary — runs at 8 AM, queries last night's data
from Whoop + Oura, and sends a WhatsApp message to Ashray.

Both devices sometimes score overnight data with a delay, so we
pull the most recent available night (not strictly "yesterday").
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

import app_config as config
from notifications.whatsapp import send


def get_last_night(session: Session) -> dict:
    """Fetch most recent night's combined Whoop + Oura data."""
    since = (date.today() - timedelta(days=3)).isoformat()

    # Latest Whoop recovery
    whoop = session.execute(text("""
        SELECT
            ws.start::date as date,
            ROUND(((ws.total_light_sleep_time_milli + ws.total_slow_wave_sleep_time_milli
                   + ws.total_rem_sleep_time_milli) / 3600000.0)::numeric, 1) as sleep_hrs,
            ROUND((ws.total_slow_wave_sleep_time_milli / 3600000.0)::numeric, 1) as sws_hrs,
            ROUND((ws.total_rem_sleep_time_milli / 3600000.0)::numeric, 1) as rem_hrs,
            ROUND(ws.sleep_performance_percentage::numeric, 0) as sleep_perf,
            ROUND(wr.recovery_score::numeric, 0) as recovery,
            ROUND(wr.resting_heart_rate::numeric, 0) as rhr,
            ROUND(wr.hrv_rmssd_milli::numeric, 1) as hrv,
            ROUND(wr.spo2_percentage::numeric, 1) as spo2,
            ROUND(wr.skin_temp_celsius::numeric, 1) as skin_temp
        FROM whoop_sleeps ws
        LEFT JOIN whoop_recoveries wr ON ws.cycle_id = wr.cycle_id
        WHERE ws.nap = false
          AND ws.start::date >= :since
          AND ws.score_state = 'SCORED'
        ORDER BY ws.start DESC
        LIMIT 1
    """), {"since": since}).mappings().fetchone()

    # Latest Oura readiness
    oura = session.execute(text("""
        SELECT
            os.day,
            os.score as sleep_score,
            or2.score as readiness,
            ROUND((os.total_sleep_duration / 3600.0)::numeric, 1) as sleep_hrs,
            ROUND((os.deep_sleep_duration / 3600.0)::numeric, 1) as deep_hrs,
            ROUND((os.rem_sleep_duration / 3600.0)::numeric, 1) as rem_hrs,
            os.efficiency,
            ROUND(os.average_hrv::numeric, 1) as hrv,
            os.lowest_heart_rate as rhr,
            ROUND(os.average_breath::numeric, 1) as resp_rate,
            ROUND(or2.temperature_deviation::numeric, 2) as temp_dev,
            or2.contributors as readiness_contributors
        FROM oura_sleeps os
        LEFT JOIN oura_readiness or2 ON os.day = or2.day
        WHERE os.day >= :since
        ORDER BY os.day DESC
        LIMIT 1
    """), {"since": since}).mappings().fetchone()

    return {
        "whoop": dict(whoop) if whoop else None,
        "oura": dict(oura) if oura else None,
    }


def recovery_emoji(score) -> str:
    if score is None:
        return "⚪"
    score = float(score)
    if score >= 67:
        return "🟢"
    elif score >= 34:
        return "🟡"
    else:
        return "🔴"


def build_message(data: dict) -> str:
    w = data.get("whoop")
    o = data.get("oura")

    lines = [f"☀️ *Good morning, Ashray*\n"]

    if not w and not o:
        return "☀️ Good morning — no sleep data available yet from either device."

    # Recovery scores — the headline
    whoop_rec = w.get("recovery") if w else None
    oura_read = o.get("readiness") if o else None
    em = recovery_emoji(whoop_rec or oura_read)

    lines.append(f"{em} *Recovery*")
    if whoop_rec:
        lines.append(f"  Whoop: {whoop_rec}/100")
    if oura_read:
        lines.append(f"  Oura readiness: {oura_read}/100")

    # Sleep
    lines.append(f"\n🌙 *Sleep*")
    if w:
        lines.append(
            f"  Whoop: {w.get('sleep_hrs')}h total "
            f"(SWS {w.get('sws_hrs')}h · REM {w.get('rem_hrs')}h) "
            f"· perf {w.get('sleep_perf')}%"
        )
    if o:
        def fh(v):
            return f"{v}h" if v is not None else "—"
        lines.append(
            f"  Oura: {fh(o.get('sleep_hrs'))} total "
            f"(deep {fh(o.get('deep_hrs'))} · REM {fh(o.get('rem_hrs'))}) "
            f"· score {o.get('sleep_score') or '—'}"
        )

    # HRV + RHR — cross-device
    lines.append(f"\n❤️ *Vitals*")
    whoop_hrv = w.get("hrv") if w else None
    oura_hrv = o.get("hrv") if o else None
    whoop_rhr = w.get("rhr") if w else None
    oura_rhr = o.get("rhr") if o else None

    if whoop_hrv and oura_hrv:
        delta = abs(float(whoop_hrv) - float(oura_hrv))
        hrv_note = f" ⚠️ {delta:.0f}ms gap between devices" if delta > 15 else ""
        lines.append(f"  HRV: {whoop_hrv}ms (Whoop) · {oura_hrv}ms (Oura){hrv_note}")
    elif whoop_hrv:
        lines.append(f"  HRV: {whoop_hrv}ms (Whoop)")
    elif oura_hrv:
        lines.append(f"  HRV: {oura_hrv}ms (Oura)")

    if whoop_rhr and oura_rhr:
        lines.append(f"  RHR: {whoop_rhr}bpm (Whoop) · {oura_rhr}bpm (Oura)")
    elif whoop_rhr:
        lines.append(f"  RHR: {whoop_rhr}bpm")

    if w and w.get("spo2"):
        lines.append(f"  SpO2: {w.get('spo2')}%")
    if o and o.get("temp_dev") is not None:
        td = float(o.get("temp_dev"))
        temp_flag = " 🌡️ elevated" if td > 0.5 else " 🌡️ low" if td < -0.5 else ""
        lines.append(f"  Temp deviation: {td:+.2f}°C{temp_flag}")

    # Training recommendation
    lines.append(f"\n💪 *Today's training*")
    score = float(whoop_rec or oura_read or 50)
    if score >= 67:
        lines.append("  Green light — good day to push hard or hit a PR.")
    elif score >= 34:
        lines.append("  Moderate day — stick to zone 2 or skill work.")
    else:
        lines.append("  Low recovery — prioritise rest, light movement only.")

    return "\n".join(lines)


def run(dry_run: bool = False) -> str:
    engine = create_engine(config.DATABASE_URL)
    with Session(engine) as session:
        data = get_last_night(session)

    message = build_message(data)

    if dry_run:
        print(message)
        return message

    success = send(message)
    if success:
        print("✅ Morning summary sent.")
    else:
        print("❌ Failed to send morning summary.")
    return message


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    run(dry_run=dry)
