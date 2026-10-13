# NBA Player Consistency Model

An automated data pipeline and scoring engine that measures **how reliably** NBA players produce, not just how much. Every morning it pulls the previous day's box scores from the NBA's stats API, loads only new games into a Supabase (PostgreSQL) warehouse, and ranks players by the consistency of their rebounds, assists, points and made threes.

> **About this repository:** this is a public showcase of the pipeline and methodology. The production scoring weights and thresholds live in a private repo. Everything here runs end to end with placeholder values from `config_example.py`.

![Season vs. recent consistency, top 50 scorers](Outputs/Plots/pts_consistency_archetypes_top50_cloud.png)

---

## Architecture

```mermaid
flowchart LR
  A[NBA Stats API<br/>LeagueGameLog] --> B[daily_ingestion.py<br/>fetch + retry]
  B -->|incremental load| C[(Supabase<br/>PostgreSQL)]
  C --> D[consistency_model.py<br/>CV scoring + ranking]
  D --> E[Outputs/<br/>ranked CSVs + plots]
  F[GitHub Actions<br/>daily cron] -.runs.-> B
  F -.runs.-> D
```

| Component | File | Role |
|---|---|---|
| Ingestion | `daily_ingestion.py` | Pulls team and player game logs for the current season, loads only games newer than what's stored |
| Warehouse | Supabase (PostgreSQL) | Tables `raw_player_box_scores` and `raw_team_box_scores`, accessed through SQLAlchemy |
| Scoring engine | `consistency_model.py` | Cleans the data, computes season and rolling consistency, applies eligibility filters, ranks players, plots archetypes |
| Config | `config_example.py` | Thresholds and weights; production values are kept private |
| Scheduler | `.github/workflows/daily_run.yml` | Runs ingestion, then scoring, every morning and commits the new outputs |

---

## Pipeline stages

### 1. Ingestion (`daily_ingestion.py`)

- **Source:** the NBA stats `LeagueGameLog` endpoint via `nba_api`, called once for players and once for teams.
- **Resilience:** browser-style request headers, a 60-second timeout, and up to 3 attempts with increasing back-off (10 s, then 20 s). The stats API is known for throttling, so this matters.
- **Incremental loading:** before writing, the script queries `MAX("GAME_DATE")` for each table with raw SQL through SQLAlchemy, keeps only newer rows, and appends them. Daily runs move days of data, not the whole season.
- **Fail loudly:** any fatal error exits with status `1`, so GitHub Actions marks the run as failed instead of silently succeeding.

### 2. Scoring (`consistency_model.py`)

- **Clean:** parse dates, coerce stat columns to numeric, drop incomplete rows.
- **Measure:** compute the **coefficient of variation** (standard deviation ÷ mean) for each player over the full season and over a rolling window of recent games.
- **Blend:** combine season and recent CV with configurable weights.
- **Filter:** require a minimum number of games and a minimum per-game average for each stat, so low-volume players can't look "consistent" by producing almost nothing.
- **Rank:** lower blended CV = more consistent. Repeated for rebounds, assists, points and made threes.
- **Visualize:** scatter the top 50 players by season CV against recent CV, with median lines splitting them into four archetypes (steady all season, recently steadier, recently more volatile, volatile all season).

### 3. Automation (`daily_run.yml`)

- Cron schedule at 12:00 UTC (early morning US time), plus a manual `workflow_dispatch` trigger for testing.
- Python 3.12 on `ubuntu-latest`; installs `requirements.txt`, runs ingestion, then scoring.
- The database connection string is injected from a GitHub **secret**, never stored in code.
- If the outputs changed, the workflow commits them back as "Automated daily model update."

> Actions are disabled on this showcase repo because it has no database credentials.

---

## Design decisions

**Coefficient of variation instead of standard deviation.** A 25-point scorer with a 5-point swing is far steadier than an 8-point scorer with the same swing. CV normalizes spread by the player's own average, so stars and role players can be compared on one scale.

**Season and recent windows, blended.** Season CV captures who a player is; recent CV captures who he's been lately (role changes, injuries, minutes shifts). Blending the two avoids overreacting to a hot week or ignoring a real change.

**Eligibility floors.** Without minimum games and averages, a bench player who scores 0–2 points every night would rank as "highly consistent." The floors keep the rankings meaningful.

**Incremental loads over full refreshes.** Re-downloading the season every day wastes API calls and invites throttling. Loading only games after the latest stored date keeps runs fast and light.

**Private config with a public fallback.** The model imports `config_private.py` when it exists and falls back to `config_example.py` otherwise. The method is fully visible and runnable; the tuned parameters stay private.

---

## Tech stack

Python 3.12 · pandas · NumPy · nba_api · SQLAlchemy · psycopg · Supabase (PostgreSQL) · Matplotlib · GitHub Actions · python-dotenv · VS Code · Claude Code (codebase audit for calculation and data-flow inefficiencies)

---

## Run it locally

```bash
git clone https://github.com/treypoore/nba-player-consistency.git
cd nba-player-consistency
pip install -r requirements.txt

# Point to your own PostgreSQL / Supabase database
echo 'DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/postgres' > .env

python daily_ingestion.py     # load game logs
python consistency_model.py   # score, rank and plot
```

Results land in `Outputs/` (ranked CSVs) and `Outputs/Plots/` (archetype charts). To tune the model, copy `config_example.py` to `config_private.py` and edit the values there; that file is git-ignored.

---

## Roadmap

- **True upserts.** Replace date-based appends with `INSERT … ON CONFLICT` on a game/player key, so a re-run can never duplicate rows.
- **Narrower error handling.** The "latest stored date" lookup currently treats any database error as an empty table; catching only the missing-table case would prevent accidental full reloads.
- **Backtesting.** Measure whether players ranked as consistent actually land closer to their averages in their next games. That step turns a descriptive score into a validated predictive signal.
- **Tests and permissions.** Add unit tests for the CV calculations, and set `permissions: contents: write` explicitly in the workflow.
