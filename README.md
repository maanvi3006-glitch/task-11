# PlaceMux · Offer Funnel Analytics
### Task 11 · Offer Generation & E-Sign Design · Phase 2 · Week 4

> **Decision-grade offer funnel metrics** — every number is sourced from
> real event tables, validated against itself, and tied to an action the
> founder would actually take.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Quick Start](#2-quick-start)
3. [Project Structure](#3-project-structure)
4. [Architecture](#4-architecture)
5. [Module Reference](#5-module-reference)
6. [Dashboard Guide](#6-dashboard-guide)
7. [Metric Dictionary](#7-metric-dictionary-summary)
8. [Data Quality](#8-data-quality)
9. [Export](#9-export)
10. [Deployment](#10-deployment)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Project Overview

This system measures the **complete offer funnel** for PlaceMux:

```
Offer Generated → Offer Sent → Offer Viewed → Offer Signed
                                            ↘ Offer Rejected
                                                    ↓
                                            Signature + Verification
```

**What makes this decision-grade:**
- Every KPI traces back to a named SQL query on real event rows
- Every KPI has a documented business decision and action trigger
- Freshness, null, duplicate, and anomaly checks run automatically
- No number is hardcoded — all thresholds live in `config.py`

---

## 2. Quick Start

### Prerequisites

```bash
Python 3.11+
pip install -r requirements.txt
```

### One-command setup

```bash
# 1 — Install dependencies
pip install -r requirements.txt

# 2 — Create database schema
python create_database.py

# 3 — Generate synthetic data (500–5000 records)
python generate_data.py

# 4 — Load data into SQLite
python load_data.py

# 5 — Launch dashboard
streamlit run dashboard.py
```

The dashboard opens at **http://localhost:8501**

### Verify each module independently

```bash
python metrics_engine.py   # prints all 20 KPIs
python validation.py       # runs 48 data-quality checks
python offer_funnel.py     # prints funnel tables + exports CSV
```

---

## 3. Project Structure

```
placemux_offer/
│
├── create_database.py      # Schema DDL — run first
├── generate_data.py        # Faker data generator
├── load_data.py            # CSV → SQLite loader with validation
├── metrics_engine.py       # 20 KPIs from named SQL queries
├── validation.py           # 48 data-quality checks
├── offer_funnel.py         # Funnel analytics + CSV export
├── dashboard.py            # Streamlit dashboard (5 sections)
├── config.py               # All constants — never hardcode elsewhere
├── utils.py                # Shared formatting helpers
├── freshness_monitor.py    # Standalone freshness checker
│
├── requirements.txt
├── README.md
├── SCHEMA.md
├── METRIC_DICTIONARY.md
├── DEMO_SCRIPT.md
│
├── placemux_offer.db       # SQLite database (auto-created)
│
├── data/
│   ├── candidates.csv
│   ├── offers.csv
│   ├── offer_events.csv
│   ├── signatures.csv
│   └── verification_logs.csv
│
├── exports/
│   └── offer_metrics_export.csv
│
└── docs/
```

---

## 4. Architecture

```
config.py
    │
    ├──▶ create_database.py   (schema)
    │         │
    │         ▼
    ├──▶ generate_data.py  ──▶  data/*.csv
    │         │
    │         ▼
    ├──▶ load_data.py      ──▶  placemux_offer.db
    │         │
    │    ┌────┴──────────────────────┐
    │    ▼                           ▼
    ├──▶ metrics_engine.py     validation.py
    │         │                      │
    │         └──────────┬───────────┘
    │                    ▼
    ├──▶ offer_funnel.py (funnel queries + export)
    │         │
    │         ▼
    └──▶ dashboard.py   (Streamlit — reads all modules)
```

**Key design rules:**
- `dashboard.py` contains **zero SQL** — it only calls module methods
- All SQL lives in `metrics_engine.py` and `offer_funnel.py`
- All thresholds live in `config.py`
- Every module is independently runnable for testing

---

## 5. Module Reference

### `config.py`
Central configuration. Edit this file to tune:
- `NUM_OFFERS` — dataset size (500–5000)
- `PROB_SENT / PROB_OPENED / PROB_SIGNED / PROB_REJECTED` — funnel drop-off rates
- `FRESHNESS_WARN_HOURS / FRESHNESS_CRIT_HOURS` — freshness SLA thresholds
- `MAX_NULL_RATE_PCT` — null detection sensitivity
- `ANOMALY_ZSCORE_THRESH` — spike detection sensitivity

### `create_database.py`
- Creates 5 tables + 9 indexes + schema version tracking
- Idempotent — safe to re-run
- Call `verify_schema()` to confirm all tables exist

### `generate_data.py`
- Generates realistic synthetic data using Faker (`en_IN` locale)
- Simulates full funnel with configurable drop-off probabilities
- Writes 5 CSVs to `data/`
- Seeded (42) for reproducible output

### `load_data.py`
- Reads CSVs → SQLite with `INSERT OR IGNORE` (idempotent)
- Validates FK integrity and PK uniqueness after load
- Reconciles CSV row count vs DB row count

### `metrics_engine.py`
- **20 KPIs** each defined as a named SQL query
- Every `MetricResult` carries: name, value, event_dependency,
  business_decision, action_trigger, sql, error
- `run_all()` → `list[MetricResult]`
- Additional methods: `get_funnel_stages()`, `get_daily_trend()`,
  `get_esign_breakdown()`, `get_rejection_reasons()`,
  `get_verification_trend()`, `get_metric(name)`

### `validation.py`
- **7 check categories, 48 checks total**
- Returns `ValidationReport` with `.passed`, `.warnings`, `.failures`
- Categories: Freshness, Null Rates, Duplicates, Anomaly Detection,
  Event Completeness, Metric Reconciliation, FK Integrity

### `offer_funnel.py`
- Funnel summary with drop-off rates per stage
- Cohort breakdowns: weekly, by department, by source channel
- Time-to-sign histogram (6 buckets)
- Stalled offer identification
- Rejection reason parsing (JSON metadata)
- Provider performance with avg verification latency
- `export_metrics_csv()` → writes `exports/offer_metrics_export.csv`

### `dashboard.py`
- 5-tab Streamlit dashboard
- 60-second data cache with manual refresh button
- All charts built with Plotly Express / Graph Objects
- Zero SQL — all data sourced from module methods

---

## 6. Dashboard Guide

| Tab | What to look at |
|-----|----------------|
| 📊 Executive KPIs | Overall conversion rate, send/view/sign rates, pending offers |
| 🔽 Offer Funnel | Funnel chart, drop-off table, daily trends, cohort breakdowns |
| ✍️ E-Sign Analytics | Provider success rates, verification trend, rejection reasons |
| 🛡️ Data Quality | Freshness age, null rates, duplicate checks, anomaly flags |
| 📥 Export | Download full CSV or KPI snapshot |

**Live demo flow (2 minutes):**
1. Open **Executive KPIs** — show conversion rate and explain its SQL source
2. Open **Offer Funnel** → Funnel Chart — identify biggest drop-off stage
3. Open **E-Sign Analytics** → Provider Performance — show verification rates
4. Open **Data Quality** — show all checks green
5. Open **Export** → download `offer_metrics_export.csv`

---

## 7. Metric Dictionary Summary

| # | Metric | Source Events | Action Trigger |
|---|--------|--------------|---------------|
| 1 | Total Offers Generated | offer_generated | Drop >20% WoW |
| 2 | Total Offers Sent | offer_sent | Sent < 90% of Generated |
| 3 | Total Offers Viewed | offer_opened | View Rate < 70% |
| 4 | Total Offers Signed | offer_signed | Sign Rate < 60% of Viewed |
| 5 | Total Offers Rejected | offer_rejected | Rejection Rate > 15% |
| 6 | Offer Send Rate % | generated + sent | Alert if < 90% |
| 7 | Offer View Rate % | sent + opened | Alert if < 70% |
| 8 | Offer Conversion Rate % | generated + signed | Alert if < 40% |
| 9 | Sign-to-View Rate % | opened + signed | Alert if < 65% |
| 10 | Rejection Rate % | opened + rejected | Alert if > 15% |
| 11 | Signature Completion % | offer_signed | Alert if < 98% |
| 12 | Verification Success % | signatures table | Alert if < 90% |
| 13 | Verification Failure % | signatures table | Alert if > 10% |
| 14 | Avg Gen→Sent (hrs) | generated + sent | Alert if > 4 hrs |
| 15 | Avg Sent→Viewed (hrs) | sent + opened | Alert if > 24 hrs |
| 16 | Avg Viewed→Signed (hrs) | opened + signed | Alert if > 12 hrs |
| 17 | Offers Pending Decision | offers.status | Recruiter follow-up |
| 18 | Offers Expired | offers.expiry_at | Review validity window |
| 19 | Top E-Sign Provider | signatures table | Switch if fail > 10% |
| 20 | Verification Re-check % | verification_logs | Alert if > 20% |

Full definitions in `METRIC_DICTIONARY.md`.

---

## 8. Data Quality

The system runs **48 automated checks** on every dashboard load:

| Category | Checks | What it catches |
|----------|--------|----------------|
| Freshness | 2 | Stale pipeline (no events > 24/48 hrs) |
| Null Rates | 27 | Missing required fields |
| Duplicates | 7 | PK and business-key collisions |
| Anomaly Detection | 1 | Daily volume spikes (z-score > 3) |
| Event Completeness | 3 | Broken event chains |
| Metric Reconciliation | 5 | KPI logic violations (e.g. Signed > Viewed) |
| FK Integrity | 4 | Orphaned child rows |

Thresholds are configurable in `config.py`.

---

## 9. Export

Two export formats available from the **Export** tab:

**`offer_metrics_export.csv`** — multi-section CSV:
- `## FUNNEL_SUMMARY` — stage counts and drop-off rates
- `## STAGE_DROPOFF` — transition-level retention
- `## COHORT_BY_WEEK` — weekly conversion trends
- `## COHORT_BY_DEPARTMENT` — per-department breakdown
- `## COHORT_BY_CHANNEL` — per source-channel breakdown
- `## PROVIDER_PERFORMANCE` — e-sign provider stats
- `## REJECTION_BREAKDOWN` — rejection reason counts
- `## TIME_TO_SIGN_DIST` — latency histogram

**`kpi_snapshot.csv`** — one row per KPI with value + metadata.

---

## 10. Deployment

### Streamlit Cloud

1. Push this repo to GitHub
2. Connect to [share.streamlit.io](https://share.streamlit.io)
3. Set **Main file path**: `dashboard.py`
4. Add to `secrets.toml` if needed (none required for SQLite)

**Important:** The SQLite file (`placemux_offer.db`) must be committed
to the repo or generated at startup via a `setup.py` / startup script:

```bash
# startup_script.sh (run before streamlit)
python create_database.py
python generate_data.py
python load_data.py
```

### Local

```bash
streamlit run dashboard.py
```

### Docker (optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
RUN python create_database.py && python generate_data.py && python load_data.py
EXPOSE 8501
CMD ["streamlit", "run", "dashboard.py", "--server.port=8501"]
```

---

## 11. Troubleshooting

| Symptom | Fix |
|---------|-----|
| `FileNotFoundError: data/offers.csv` | Run `python generate_data.py` first |
| `sqlite3.OperationalError: no such table` | Run `python create_database.py` |
| Dashboard shows `—` for all KPIs | Run `python load_data.py` to populate DB |
| Freshness check failing | Re-run `generate_data.py` + `load_data.py` |
| Streamlit not found | `pip install -r requirements.txt` |
| Port 8501 in use | `streamlit run dashboard.py --server.port 8502` |

---

## Compliance Note

All data in this system is **fully synthetic** (generated by Faker).
No real candidate PII is stored. For production use with real data,
ensure compliance with DPDP (India) and applicable consent frameworks
before tracking offer-open events.

---

*PlaceMux · Altrodav Technologies Pvt. Ltd. · Phase 2 Industry Immersion · Task 11*
