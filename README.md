# Masters Pool Scorer

Standalone Masters pool scorer with:

- live ESPN ingestion
- deterministic snapshot ledger
- replay tooling for payout disputes
- Masters-inspired web UI
- side games (eagles, aces, birdie streaks)
- Vercel + Neon deployment path (no local daemon required in production)

## Scoring rules implemented

- 8 picks per participant (3+2+2+1 tiers)
- each day (Thu-Sun), **all 8 daily scores** count
- event total is sum of Thu/Fri/Sat/Sun team scores
- lowest event total wins
- missed cut or WD = golfer's cumulative score-to-date is reused for each unplayed day
- eagle bonus = **$10 each**
- ace bonus = **$20 each**
- birdie streak bonus:
  - qualifying hole = birdie/eagle/ace
  - starts at 3 consecutive qualifying holes
  - $10 at 3rd, +$10 each additional consecutive hole
  - resets on any non-qualifying hole
- tiebreaker = closest prediction to winner's final score to par

## Quick start

```bash
cd /Users/glazed/masters-pool
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp data/pool_config.example.json data/pool_config.json
python scripts/poll_once.py
python run.py
```

Web UI: [http://localhost:5055](http://localhost:5055)

## Runtime scripts

- `python scripts/poll_once.py` -> one ingest and score pass
- `python scripts/poll_loop.py` -> continuous polling (5 min live, 30 min idle by config)
- `python scripts/replay.py --at 2026-04-10T18:30:00+00:00` -> recompute standings from ledger at timestamp
- `python scripts/map_players.py` -> print ESPN player ID mapping for current Masters field

## Config

Edit `data/pool_config.json`:

- `event_id` (Masters is `401811941` for 2026)
- participants and picks
- `predictedWinningToPar`
- poll cadence
- humor mode (`off`, `dry`, `chaos`)

## Production deployment (Vercel + Neon)

This app supports two storage backends:

- local file storage (default, for local dev)
- Neon Postgres (enabled when `MASTERS_POOL_DATABASE_URL` is set)

### Required env vars

- `MASTERS_POOL_DATABASE_URL` -> Neon connection string (`sslmode=require`)
- `MASTERS_POOL_CRON_SECRET` -> long random secret used to authorize cron polling

### Vercel behavior

- Vercel serves Flask app from `api/index.py`
- `vercel.json` config runs cron every 5 minutes: `GET /api/cron/poll`
- cron endpoint requires `Authorization: Bearer <MASTERS_POOL_CRON_SECRET>`

### Important isolation note

Use a **dedicated Neon project/database** and a **dedicated GitHub repo** for this app.
Do not reuse Nexus resources.

### Minimal deployment checklist (separate resources only)

1. Create a new Neon project and database (name it `masters-pool-public` or similar).
2. Run `sql/neon_init.sql` once against that Neon database.
3. Create a new GitHub repo not related to Nexus.
4. Import this folder into that new repo.
5. In Vercel, create a new project from that repo.
6. Set env vars in Vercel:
   - `MASTERS_POOL_DATABASE_URL`
   - `MASTERS_POOL_CRON_SECRET`
7. Deploy. Vercel cron will call `/api/cron/poll` every 5 minutes.

## Notes

- ESPN endpoints are undocumented but currently stable.
- In local mode, ledger entries are JSONL files in `data/ledger/`.
- In Neon mode, ledger entries are persisted in `pool_ledger` table.
- Replay uses the latest snapshot at or before the target timestamp.
