# DEMO_SCRIPT.md — PlaceMux Offer Funnel
### Task 11 · Offer Generation & E-Sign Design · Live Demo Guide

> **Purpose:** This script prepares you to demo the offer funnel
> dashboard live, explain every number on the spot, and answer the
> four questions the founder will always ask.
>
> Target demo length: **2 minutes** (strict — practise to time).
> Format: live dashboard on real data — no slides, no screenshots.

---

## Pre-Demo Checklist

Run these commands **before** the founder opens the browser.
If any step fails, fix it before the call — never debug live.

```bash
# 1. Confirm database exists and has data
python -c "
import sqlite3
conn = sqlite3.connect('placemux_offer.db')
for t in ['candidates','offers','offer_events','signatures','verification_logs']:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'  {t:<22} {n:>5} rows')
conn.close()
"

# 2. Run all validation checks — must be 0 failures
python validation.py

# 3. Verify all 20 KPIs return a value
python metrics_engine.py

# 4. Confirm export file exists
python offer_funnel.py

# 5. Start the dashboard
streamlit run dashboard.py
```

**Expected output for step 1:**
```
  candidates              600 rows
  offers                  500 rows
  offer_events           1593 rows
  signatures              243 rows
  verification_logs       285 rows
```

**Dashboard URL:** http://localhost:8501

---

## The Four Questions You Will Be Asked

The founder will ask these. Know the answer before you open your mouth.

| Question | Your answer |
|----------|-------------|
| Where does this number come from? | "It's a COUNT(DISTINCT offer_id) on the offer_events table filtered to event_name = 'offer_signed'. No manual entry." |
| Is this real data? | "Yes — synthetic but at realistic scale (500 offers, 1,593 events). The schema and queries are identical to what production would use." |
| What would I do if conversion dropped? | "Below 40% conversion triggers an offer strategy review — comp-band, e-sign UX, and follow-up cadence are the three levers." |
| Can someone tamper with a signed offer? | "No — every signed document has a SHA-256 hash stored in the signatures table. A re-hash of the PDF at any point confirms integrity." |

---

## 2-Minute Live Demo Script

### Opening (10 seconds)

> "This is the PlaceMux offer funnel dashboard — every number on this
> screen comes directly from the event log in SQLite. Nothing is
> manually entered. Let me walk you through it."

---

### Step 1 — Executive KPIs tab (30 seconds)

**Click:** Tab 1 — 📊 Executive KPIs

Point to the top row:

> "These four numbers tell us the volume story. We generated
> **[X] offers**, sent **[X]**, **[X]** were viewed, and **[X]**
> were signed."

Point to conversion rate:

> "This is the North Star — **[X]% conversion rate**. That's signed
> divided by generated, straight from the event table. Our threshold
> is 40%. We're [above / below] that."

Point to verification rate:

> "And **[X]% of signatures passed tamper verification** — that means
> the e-sign provider confirmed the document hash hasn't changed since
> signing."

**If asked where conversion rate comes from:**

> "It's this query — COUNT signed events divided by COUNT generated
> events on offer_events. I can show you the SQL in the metric
> dictionary expander right here."

*Click the 📖 Metric Dictionary expander to show the SQL inline.*

---

### Step 2 — Offer Funnel tab (40 seconds)

**Click:** Tab 2 — 🔽 Offer Funnel

Point to funnel chart:

> "This is the full funnel. Each bar is a distinct count from the
> event log — not a counter, not a report, actual events."

Point to the biggest drop-off bar:

> "The biggest drop is here — **[Transition name]** — we lose
> **[X]%** at this stage. That's our highest-priority lever right now."

Point to stage drop-off table:

> "This table shows every transition explicitly: how many entered,
> how many made it through, how many were lost, and the loss rate.
> All SQL-sourced."

Click the Department tab:

> "We can also break it by department. **[Best dept]** is converting
> at **[X]%**, **[worst dept]** at **[X]%**. That tells us which
> hiring managers need a conversation about offer competitiveness."

Click the Channel tab:

> "By source channel — **[best channel]** produces candidates
> most likely to accept. That's where we should concentrate
> sourcing spend."

---

### Step 3 — E-Sign Analytics tab (25 seconds)

**Click:** Tab 3 — ✍️ E-Sign Analytics

Point to provider chart:

> "Three e-sign providers. **[Top provider]** is handling
> **[X] signatures** with a **[X]% verification success rate**.
> Our SLA threshold is 90% — we're [above / below] it."

Point to verification trend:

> "This line chart shows daily verification pass vs fail over 30 days.
> A spike in fails here would immediately flag a provider outage
> before a candidate or legal team notices."

Point to rejection reasons:

> "Rejection reasons are parsed from the event metadata JSON.
> **[Top reason]** accounts for **[X]%** of rejections — that's
> actionable: it means [compensation / role fit / timing]."

---

### Step 4 — Data Quality tab (15 seconds)

**Click:** Tab 4 — 🛡️ Data Quality

> "48 automated checks run on every dashboard load.
> Freshness, nulls, duplicates, anomaly detection, FK integrity,
> and metric reconciliation. Right now we have
> **[X] passing, [X] warnings, [X] failures**."

If all green:

> "Everything is clean — the pipeline is healthy."

If warnings:

> "The freshness warning here means the last event was
> **[X] hours ago** — our SLA threshold is 24 hours.
> In production this would page on-call."

---

### Step 5 — Export (optional, 10 seconds)

**Click:** Tab 5 — 📥 Export

> "One click downloads a full CSV snapshot — funnel summary,
> cohort breakdowns, provider stats — for any stakeholder who
> needs the data offline."

*Click the download button to demonstrate it works.*

---

### Close (10 seconds)

> "Every metric has a documented SQL source, event dependency,
> business decision, and action trigger — all in the metric
> dictionary. The dashboard is reading directly from SQLite.
> No manual numbers anywhere."

---

## Handling Tough Questions

### "Why is conversion only [X]%? That seems low."

> "It means [X]% of offers we generate result in a signed acceptance.
> The funnel breakdown shows where we're losing candidates —
> the biggest gap is at [stage]. That's the specific thing
> to fix, not the overall number."

### "How do I know a candidate can't dispute the signature?"

> "Every signed offer has two safeguards. One: a SHA-256 hash of
> the document stored in the signatures table — if the PDF changes
> after signing, re-hashing it produces a different value and the
> tamper is detected. Two: the verification log records every
> provider webhook confirmation with a timestamp. That's an
> independent audit trail."

### "What if the e-sign provider goes down mid-flow?"

> "The verification_logs table records every attempt. If the webhook
> fails, the status stays 'pending' and the re-check rate metric
> (M20) spikes. Our threshold is 20% — above that we get an alert
> and can route new signatures to a backup provider."

### "Can you add [new metric] quickly?"

> "Yes. Every metric is a dict in the METRIC_REGISTRY list in
> metrics_engine.py — name, SQL, event dependency, business
> decision, action trigger. Add the dict, the dashboard picks it
> up automatically on next load."

### "How would this work with real candidate data?"

> "The schema is identical. We'd replace the Faker generator with
> real event ingestion — a webhook from the offer management system
> writes to offer_events, and the dashboard reads from the same
> SQLite file. For scale beyond ~50k rows, swap SQLite for
> PostgreSQL — only the connection string in config.py changes."

### "What's the freshness warning about?"

> "It means the most recent event in the table is [X] hours old.
> In a live system, the offer pipeline would be generating events
> continuously. The 24-hour warn threshold means: if no new event
> has arrived in a day, something in the upstream pipeline
> is broken and we want to know before the founder does."

---

## Numbers to Know Cold

Before the demo, run `python metrics_engine.py` and memorise these:

```bash
python -c "
from metrics_engine import MetricsEngine
engine = MetricsEngine()
results = engine.run_all()
key_metrics = [
    'Total Offers Generated',
    'Total Offers Signed',
    'Offer Conversion Rate (%)',
    'Offer View Rate (%)',
    'Sign-to-View Rate (%)',
    'Verification Success Rate (%)',
    'Avg Time Viewed → Signed (hrs)',
    'Top E-Sign Provider',
]
print()
for r in results:
    if r.name in key_metrics:
        print(f'  {r.name:<40}  {r.value}')
"
```

**Fill in before your demo:**

| Metric | Your Value |
|--------|-----------|
| Offers Generated | _______ |
| Offers Signed | _______ |
| Conversion Rate | _______ % |
| View Rate | _______ % |
| Sign-to-View Rate | _______ % |
| Verification Success | _______ % |
| Avg View→Sign | _______ hrs |
| Top Provider | _______ |
| Biggest drop-off stage | _______ |
| Best dept by conversion | _______ |

---

## Self-Check — Ready to Demo?

Answer **"yes, and I can show it live"** to each before presenting:

- [ ] Can you show the live dashboard with real numbers?
- [ ] Can you explain where Conversion Rate comes from (SQL + events)?
- [ ] Can you explain how a signed offer is tamper-evident?
- [ ] Can you identify the biggest drop-off stage and say what to do about it?
- [ ] Can you show the data quality tab is clean (or explain any warnings)?
- [ ] Can you download the export CSV live?
- [ ] Can you explain what would trigger an alert in production?
- [ ] Can you name the top e-sign provider and its verification rate?

If any answer is "no" — practise that section before the call.

---

## Recovery Playbook (If Something Goes Wrong)

| Problem | Fix |
|---------|-----|
| Dashboard won't start | `pip install -r requirements.txt` then retry |
| All KPIs show `—` | `python load_data.py` to reload database |
| Database not found | `python create_database.py && python generate_data.py && python load_data.py` |
| Port 8501 busy | `streamlit run dashboard.py --server.port 8502` |
| Validation shows failures | `python validation.py` to see which check — likely a data reload fixes it |
| Export file missing | Click "Regenerate Metrics CSV" in the Export tab |

---

## Post-Demo Hand-off Notes

If the next team asks what you built, tell them:

> "Offer measurement system. Five SQLite tables: candidates, offers,
> offer_events, signatures, verification_logs. Twenty KPIs computed
> from SQL on the event log. Dashboard in Streamlit. 48 automated
> data-quality checks. Export to CSV. Everything is in README.md —
> they can run it with three commands."

Hand-off the following:
- `placemux_offer.db` — live database
- `exports/offer_metrics_export.csv` — latest metrics snapshot
- `README.md` — setup and architecture guide
- `METRIC_DICTIONARY.md` — full KPI reference
- `SCHEMA.md` — database schema

---

*PlaceMux · Altrodav Technologies Pvt. Ltd. · Phase 2 · Task 11*
*Demo script version 1.0 — practise twice before the real thing.*
