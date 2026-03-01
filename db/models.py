from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime, Text,
    ForeignKey, UniqueConstraint, create_engine
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

Base = declarative_base()


# ─── WHOOP ────────────────────────────────────────────────────────────────────

class WhoopCycle(Base):
    __tablename__ = "whoop_cycles"
    id = Column(Integer, primary_key=True)  # Whoop cycle ID
    user_id = Column(Integer)
    start = Column(DateTime(timezone=True))
    end = Column(DateTime(timezone=True))
    timezone_offset = Column(String(10))
    score_state = Column(String(20))
    strain = Column(Float)
    kilojoule = Column(Float)
    average_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class WhoopSleep(Base):
    __tablename__ = "whoop_sleeps"
    id = Column(String, primary_key=True)  # UUID
    cycle_id = Column(Integer)
    user_id = Column(Integer)
    start = Column(DateTime(timezone=True))
    end = Column(DateTime(timezone=True))
    nap = Column(Boolean, default=False)
    score_state = Column(String(20))
    # Stage summary
    total_in_bed_time_milli = Column(Integer)
    total_awake_time_milli = Column(Integer)
    total_light_sleep_time_milli = Column(Integer)
    total_slow_wave_sleep_time_milli = Column(Integer)
    total_rem_sleep_time_milli = Column(Integer)
    sleep_cycle_count = Column(Integer)
    disturbance_count = Column(Integer)
    # Scores
    respiratory_rate = Column(Float)
    sleep_performance_percentage = Column(Float)
    sleep_consistency_percentage = Column(Float)
    sleep_efficiency_percentage = Column(Float)
    # Sleep needed
    baseline_milli = Column(Integer)
    need_from_sleep_debt_milli = Column(Integer)
    need_from_recent_strain_milli = Column(Integer)
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class WhoopRecovery(Base):
    __tablename__ = "whoop_recoveries"
    cycle_id = Column(Integer, primary_key=True)
    sleep_id = Column(String)
    user_id = Column(Integer)
    score_state = Column(String(20))
    user_calibrating = Column(Boolean)
    recovery_score = Column(Float)
    resting_heart_rate = Column(Float)
    hrv_rmssd_milli = Column(Float)
    spo2_percentage = Column(Float)
    skin_temp_celsius = Column(Float)
    created_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True))
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class WhoopWorkout(Base):
    __tablename__ = "whoop_workouts"
    id = Column(String, primary_key=True)  # UUID
    user_id = Column(Integer)
    start = Column(DateTime(timezone=True))
    end = Column(DateTime(timezone=True))
    sport_name = Column(String(100))
    sport_id = Column(Integer)
    score_state = Column(String(20))
    strain = Column(Float)
    average_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    kilojoule = Column(Float)
    distance_meter = Column(Float)
    altitude_gain_meter = Column(Float)
    zone_durations = Column(JSONB)
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ─── OURA ─────────────────────────────────────────────────────────────────────

class OuraSleep(Base):
    __tablename__ = "oura_sleeps"
    id = Column(String, primary_key=True)
    day = Column(String(10))  # YYYY-MM-DD
    bedtime_start = Column(DateTime(timezone=True))
    bedtime_end = Column(DateTime(timezone=True))
    # Durations (seconds)
    total_sleep_duration = Column(Integer)
    awake_time = Column(Integer)
    light_sleep_duration = Column(Integer)
    deep_sleep_duration = Column(Integer)
    rem_sleep_duration = Column(Integer)
    time_in_bed = Column(Integer)
    # Scores
    score = Column(Integer)
    efficiency = Column(Integer)
    latency = Column(Integer)
    restfulness = Column(Integer)
    # Vitals
    average_hrv = Column(Float)
    lowest_heart_rate = Column(Integer)
    average_heart_rate = Column(Float)
    average_breath = Column(Float)
    # Contributors (sub-scores)
    contributors = Column(JSONB)
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class OuraReadiness(Base):
    __tablename__ = "oura_readiness"
    id = Column(String, primary_key=True)
    day = Column(String(10))
    score = Column(Integer)
    temperature_deviation = Column(Float)
    temperature_trend_deviation = Column(Float)
    contributors = Column(JSONB)
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class OuraActivity(Base):
    __tablename__ = "oura_activity"
    id = Column(String, primary_key=True)
    day = Column(String(10))
    score = Column(Integer)
    active_calories = Column(Integer)
    total_calories = Column(Integer)
    steps = Column(Integer)
    equivalent_walking_distance = Column(Integer)
    high_activity_time = Column(Integer)
    medium_activity_time = Column(Integer)
    low_activity_time = Column(Integer)
    sedentary_time = Column(Integer)
    resting_time = Column(Integer)
    contributors = Column(JSONB)
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class OuraWorkout(Base):
    __tablename__ = "oura_workouts"
    id = Column(String, primary_key=True)
    day = Column(String(10))
    activity = Column(String(100))
    start_datetime = Column(DateTime(timezone=True))
    end_datetime = Column(DateTime(timezone=True))
    calories = Column(Float)
    distance = Column(Float)
    intensity = Column(String(20))
    source = Column(String(50))
    average_heart_rate = Column(Integer)
    max_heart_rate = Column(Integer)
    ingested_at = Column(DateTime(timezone=True), default=datetime.utcnow)


class Event(Base):
    """
    Personal event log — Ashray's self-reported behaviors.
    Parsed by AI (Zoe or Ollama) from natural language, not hardcoded rules.

    Schema is intentionally open-ended:
    - tags: arbitrary list, AI-generated, no fixed vocabulary
    - context: freeform JSON for anything that doesn't fit standard fields
      e.g. {"mood": "stressed", "intensity": "high", "with": "friends"}
    """
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    logged_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    raw_text = Column(Text, nullable=False)
    category = Column(String(50))        # broad bucket: caffeine/alcohol/exercise/food/sleep/mood/supplement/other
    tags = Column(JSONB, default=list)   # open-ended AI-generated tags
    quantity = Column(Float)
    unit = Column(String(30))
    context = Column(JSONB, default=dict)  # anything extra: intensity, mood, duration, location, etc.
    source = Column(String(20), default="whatsapp")
    parsed_by = Column(String(20), default="ollama")  # ollama / zoe / manual


def init_db(database_url: str):
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    return engine
