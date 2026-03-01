# Life OS

A personal data aggregation and analysis platform. Ingests health data from wearables, stores it in Postgres, and delivers AI-powered insights via WhatsApp and Telegram.

## What it does

- **Pulls data** from Whoop and Oura Ring automatically, twice daily
- **Stores everything** in a local PostgreSQL database
- **Sends a morning summary** to WhatsApp + Telegram at 8 AM ET with recovery scores, sleep breakdown, HRV comparison, and a training recommendation
- **Logs life events** — message "I just drank a coffee" or "played tennis" and it gets tagged, timestamped, and stored for correlation against health data

## Stack

- **Python 3.14** — ingestion, analysis, scheduling
- **PostgreSQL 16** — local database (Homebrew)
- **SQLAlchemy** — ORM + query layer
- **Alembic** — database migrations
- **APScheduler** — cron-style job scheduling (runs as macOS launchd service)
- **OpenClaw** — WhatsApp + Telegram delivery

## Project structure

```
life-os/
├── app_config.py          # all config, loaded from .env
├── scheduler.py           # APScheduler daemon (8 AM + noon ET)
├── db/
│   ├── models.py          # SQLAlchemy ORM models
│   └── migrations/        # Alembic migrations
├── ingestion/
│   ├── whoop.py           # Whoop API v1/v2 ingestion
│   └── oura.py            # Oura API v2 ingestion (daily + sleep periods)
├── analysis/
│   ├── health.py          # queries DB, formats data for AI analysis
│   ├── morning_summary.py # builds + queues daily morning report
│   └── event_log.py       # NLP event parser + logger
├── notifications/
│   └── whatsapp.py        # notification queue (delivered via OpenClaw)
└── scripts/
    └── whoop_auth.py      # one-time Whoop OAuth2 flow
```

## Database tables

| Table | Source | Contents |
|---|---|---|
| `whoop_cycles` | Whoop v1 | Daily strain cycles |
| `whoop_sleeps` | Whoop v2 | Sleep stages, efficiency, respiratory rate |
| `whoop_recoveries` | Whoop v2 | HRV, RHR, SpO2, skin temp, recovery score |
| `whoop_workouts` | Whoop v2 | Workouts with heart rate zones |
| `oura_sleeps` | Oura v2 | Sleep stages + biometrics (merged from `/daily_sleep` + `/sleep`) |
| `oura_readiness` | Oura v2 | Readiness score, temp deviation, contributors |
| `oura_activity` | Oura v2 | Steps, active calories, intensity breakdown |
| `oura_workouts` | Oura v2 | Workout sessions |
| `events` | Self-reported | Life log events (caffeine, alcohol, exercise, food, etc.) |

## Setup

### 1. Install dependencies

```bash
brew install postgresql@16
brew services start postgresql@16
createdb lifeos
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env
# Fill in: WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, OURA_PERSONAL_ACCESS_TOKEN
```

### 3. Whoop OAuth (one-time)

```bash
python scripts/whoop_auth.py
# Opens browser → log in → token saved to .whoop_token.json
```

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Backfill historical data

```bash
python ingestion/oura.py 2022-01-01 2026-01-01
python ingestion/whoop.py
```

### 6. Start scheduler (macOS launchd)

```bash
cp com.lifeos.scheduler.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.lifeos.scheduler.plist
```

## Usage

### Manual ingestion
```bash
python ingestion/whoop.py                        # last 3 days
python ingestion/oura.py 2026-01-01 2026-02-01  # date range
```

### Morning summary (dry run)
```bash
python analysis/morning_summary.py --dry-run
```

### Log a life event
```bash
python analysis/event_log.py "had 2 beers tonight"
python analysis/event_log.py "played tennis at 3pm"
python analysis/event_log.py --list --days 7
```

### Query health data (for AI analysis)
```bash
python analysis/health.py --days 14
python analysis/health.py --section sleep
```

## Event logging

Message the AI assistant on WhatsApp or Telegram with natural language:
- `"I just drank a coffee"` → category: caffeine, tags: coffee
- `"had 2 beers last night"` → category: alcohol, tags: beer, evening
- `"played tennis at 3pm"` → category: exercise, tags: tennis
- `"took melatonin before bed"` → category: sleep, tags: pre_sleep

Time references are parsed automatically in ET: noon, this morning, last night, at 3pm, etc.

## Roadmap

- [ ] Cross-device correlation analysis (does alcohol → lower HRV next day?)
- [ ] Finance pipeline (bank/brokerage/credit card ingestion)
- [ ] Google Maps Timeline correlation
- [ ] Coupon expiry alerts
- [ ] Move to cloud (Supabase/Railway)
