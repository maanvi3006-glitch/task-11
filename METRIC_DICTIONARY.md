# METRIC_DICTIONARY.md — PlaceMux Offer Funnel
### Task 11 · Offer Generation & E-Sign Design

> **Every metric in this system must pass the four-field test:**
> - **SQL Source** — exactly which query produces this number
> - **Event Dependency** — which `offer_events.event_name` rows it needs
> - **Business Decision** — what the founder decides based on this number
> - **Action Trigger** — the threshold that prompts a specific action
>
> If a metric cannot answer all four, it is a vanity metric and is cut.

---

## Quick Reference Table

| # | Metric Name | Type | Primary Event(s) | Action Threshold |
|---|-------------|------|-----------------|-----------------|
| 1 | Total Offers Generated | Volume | offer_generated | Drop >20% WoW |
| 2 | Total Offers Sent | Volume | offer_sent | <90% of Generated |
| 3 | Total Offers Viewed | Volume | offer_opened | View Rate <70% |
| 4 | Total Offers Signed | Volume | offer_signed | Sign Rate <60% of Viewed |
| 5 | Total Offers Rejected | Volume | offer_rejected | Rejection Rate >15% |
| 6 | Offer Send Rate % | Rate | generated + sent | <90% |
| 7 | Offer View Rate % | Rate | sent + opened | <70% |
| 8 | Offer Conversion Rate % | Rate | generated + signed | <40% |
| 9 | Sign-to-View Rate % | Rate | opened + signed | <65% |
| 10 | Rejection Rate % | Rate | opened + rejected | >15% |
| 11 | Signature Completion Rate % | Quality | offer_signed | <98% |
| 12 | Verification Success Rate % | Quality | signatures table | <90% |
| 13 | Verification Failure Rate % | Quality | signatures table | >10% |
| 14 | Avg Time Generated → Sent (hrs) | Latency | generated + sent | >4 hrs |
| 15 | Avg Time Sent → Viewed (hrs) | Latency | sent + opened | >24 hrs |
| 16 | Avg Time Viewed → Signed (hrs) | Latency | opened + signed | >12 hrs |
| 17 | Offers Pending Decision | Pipeline | offers.status | Per expiry date |
| 18 | Offers Expired | Pipeline | offers.expiry_at | >5% of Sent |
| 19 | Top E-Sign Provider | Operational | signatures table | Fail rate >10% |
| 20 | Verification Re-check Rate % | Quality | verification_logs | >20% |

---

## Full Metric Definitions

---

### M01 · Total Offers Generated

| Field | Value |
|-------|-------|
| **Category** | Volume |
| **Description** | Count of all distinct offer documents created in the system. This is the top of the funnel — the baseline against which every downstream metric is measured. |
| **Event Dependency** | `offer_generated` |
| **Business Decision** | Confirms the hiring pipeline is producing offers at the expected rate. Used to size HR-ops capacity and set weekly headcount targets. |
| **Action Trigger** | If weekly volume drops more than 20% versus the prior week, investigate the upstream pipeline for approval bottlenecks or requisition freezes. |

**SQL Source:**
```sql
SELECT COUNT(DISTINCT offer_id)
FROM   offer_events
WHERE  event_name = 'offer_generated'
```

**Interpretation guide:**
- Rising trend → pipeline is healthy, hiring is scaling
- Flat trend → steady-state hiring, monitor conversion rates
- Falling trend → upstream freeze or approval blockage; escalate immediately

---

### M02 · Total Offers Sent

| Field | Value |
|-------|-------|
| **Category** | Volume |
| **Description** | Count of offer documents successfully dispatched to candidates via the delivery channel (email / SMS). |
| **Event Dependency** | `offer_sent` |
| **Business Decision** | Confirms the dispatch pipeline is not stuck. A large gap between Generated and Sent indicates an HR-ops processing delay. |
| **Action Trigger** | Alert if Sent count falls below 90% of Generated within 2 hours of generation. Trigger HR-ops review. |

**SQL Source:**
```sql
SELECT COUNT(DISTINCT offer_id)
FROM   offer_events
WHERE  event_name = 'offer_sent'
```

**Note:** The gap `Generated − Sent` is the ops backlog. Monitor this daily.

---

### M03 · Total Offers Viewed

| Field | Value |
|-------|-------|
| **Category** | Volume |
| **Description** | Count of offers where the candidate opened the offer document at least once (first `offer_opened` event per offer). |
| **Event Dependency** | `offer_opened` |
| **Business Decision** | Low view count relative to Sent indicates email deliverability failure or poor subject-line engagement. High view count confirms candidates are receiving and engaging with the offer. |
| **Action Trigger** | If View Rate drops below 70% of Sent, immediately review email delivery logs and consider an SMS fallback channel. |

**SQL Source:**
```sql
SELECT COUNT(DISTINCT offer_id)
FROM   offer_events
WHERE  event_name = 'offer_opened'
```

---

### M04 · Total Offers Signed

| Field | Value |
|-------|-------|
| **Category** | Volume |
| **Description** | Count of offers where the candidate completed the e-sign step — the primary output of the offer funnel. |
| **Event Dependency** | `offer_signed` |
| **Business Decision** | Primary conversion output. Signed offers drive headcount forecasting, onboarding scheduling, and background-check initiation. |
| **Action Trigger** | If Sign Rate falls below 60% of Viewed, review offer competitiveness (comp-band, role clarity, deadline pressure). |

**SQL Source:**
```sql
SELECT COUNT(DISTINCT offer_id)
FROM   offer_events
WHERE  event_name = 'offer_signed'
```

---

### M05 · Total Offers Rejected

| Field | Value |
|-------|-------|
| **Category** | Volume |
| **Description** | Count of offers explicitly declined by the candidate via the rejection flow. Does not include expired offers where no decision was made. |
| **Event Dependency** | `offer_rejected` |
| **Business Decision** | High rejection volume triggers a compensation or role-fit review. Rejection reasons (from event metadata) guide the corrective action. |
| **Action Trigger** | If Rejection Rate exceeds 15% of Viewed in any rolling 7-day window, escalate to the hiring manager with a rejection-reason breakdown. |

**SQL Source:**
```sql
SELECT COUNT(DISTINCT offer_id)
FROM   offer_events
WHERE  event_name = 'offer_rejected'
```

---

### M06 · Offer Send Rate (%)

| Field | Value |
|-------|-------|
| **Category** | Funnel Rate |
| **Description** | Percentage of generated offers that were successfully sent to candidates. Measures HR-ops processing efficiency. |
| **Event Dependency** | `offer_generated`, `offer_sent` |
| **Business Decision** | A send rate below 90% indicates an operational bottleneck between offer approval and dispatch. Prompts process review. |
| **Action Trigger** | Alert if Send Rate falls below 90%. Check for stuck queues in the email/SMS provider or pending HR-ops approvals. |

**SQL Source:**
```sql
SELECT ROUND(
    100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_sent'      THEN offer_id END)
          / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_generated' THEN offer_id END), 0)
, 2)
FROM offer_events
```

**Benchmark:** Well-run pipelines maintain Send Rate ≥ 95%.

---

### M07 · Offer View Rate (%)

| Field | Value |
|-------|-------|
| **Category** | Funnel Rate |
| **Description** | Percentage of sent offers that were opened by the candidate at least once. |
| **Event Dependency** | `offer_sent`, `offer_opened` |
| **Business Decision** | Low view rate is a delivery problem, not a candidate-intent problem. Distinguishes email reachability issues from genuine disengagement. |
| **Action Trigger** | If View Rate falls below 70%, review email open rates, spam filter placement, and consider adding an SMS nudge within 4 hours of sending. |

**SQL Source:**
```sql
SELECT ROUND(
    100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_opened' THEN offer_id END)
          / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_sent' THEN offer_id END), 0)
, 2)
FROM offer_events
```

**Benchmark:** B2C email open rates run 20–40%. Offer letters should target ≥ 80% given the candidate's personal stake.

---

### M08 · Offer Conversion Rate (%)

| Field | Value |
|-------|-------|
| **Category** | Funnel Rate — North Star |
| **Description** | Percentage of generated offers that result in a completed signature. The single most important funnel metric — measures end-to-end effectiveness from creation to acceptance. |
| **Event Dependency** | `offer_generated`, `offer_signed` |
| **Business Decision** | This is the **North Star metric** for the offer funnel. Every other metric is a diagnostic to explain why this number is where it is. |
| **Action Trigger** | If Conversion Rate falls below 40%, trigger an offer strategy review covering: comp-band positioning, offer validity window, e-sign UX friction, and candidate follow-up cadence. |

**SQL Source:**
```sql
SELECT ROUND(
    100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_signed'    THEN offer_id END)
          / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_generated' THEN offer_id END), 0)
, 2)
FROM offer_events
```

**Benchmark:** Industry average for offer acceptance in competitive tech hiring runs 65–75%. Early-stage companies often see 50–65%.

---

### M09 · Sign-to-View Rate (%)

| Field | Value |
|-------|-------|
| **Category** | Funnel Rate |
| **Description** | Of candidates who opened the offer, the percentage who went on to sign. Isolates candidate intent from delivery noise. |
| **Event Dependency** | `offer_opened`, `offer_signed` |
| **Business Decision** | If View Rate is healthy but Sign-to-View is low, the problem is with the offer itself (terms, salary, deadline), not the delivery channel. |
| **Action Trigger** | If Sign-to-View falls below 65%, review offer terms, comp positioning, and follow-up call timing. Consider a 48-hour recruiter check-in call for all viewed-but-unsigned offers. |

**SQL Source:**
```sql
SELECT ROUND(
    100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_signed' THEN offer_id END)
          / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_opened' THEN offer_id END), 0)
, 2)
FROM offer_events
```

---

### M10 · Rejection Rate (%)

| Field | Value |
|-------|-------|
| **Category** | Funnel Rate |
| **Description** | Percentage of viewed offers that were explicitly rejected by the candidate. Excludes expired offers where no decision was recorded. |
| **Event Dependency** | `offer_opened`, `offer_rejected` |
| **Business Decision** | High rejection rate surfaces a compensation, role-fit, or timing problem. Rejection reason metadata (from `offer_events.metadata`) guides the specific fix. |
| **Action Trigger** | If Rejection Rate exceeds 15% of Viewed in any rolling 7-day window, generate a rejection-reason breakdown and present to the hiring manager within 24 hours. |

**SQL Source:**
```sql
SELECT ROUND(
    100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_rejected' THEN offer_id END)
          / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_opened' THEN offer_id END), 0)
, 2)
FROM offer_events
```

---

### M11 · Signature Completion Rate (%)

| Field | Value |
|-------|-------|
| **Category** | E-Sign Quality |
| **Description** | Of all `offer_signed` events fired, the percentage that have a corresponding row in the `signatures` table. Measures e-sign provider flow completion. |
| **Event Dependency** | `offer_signed` (cross-referenced with `signatures` table) |
| **Business Decision** | A rate below 100% means the e-sign provider is dropping sessions — the event fires but the signature record is never written. This is a data integrity and legal risk. |
| **Action Trigger** | If Signature Completion Rate falls below 98%, immediately check e-sign provider error logs and webhook delivery. Notify legal if any signed offer lacks a verifiable record. |

**SQL Source:**
```sql
SELECT ROUND(
    100.0 * COUNT(s.sign_id)
          / NULLIF(COUNT(DISTINCT e.offer_id), 0)
, 2)
FROM offer_events e
LEFT JOIN signatures s ON e.offer_id = s.offer_id
WHERE e.event_name = 'offer_signed'
```

---

### M12 · Verification Success Rate (%)

| Field | Value |
|-------|-------|
| **Category** | E-Sign Quality |
| **Description** | Percentage of signature records where `verification_status = 'verified'`. Measures the proportion of legally binding, tamper-evident signatures. |
| **Event Dependency** | `signatures` table (`verification_status` column) |
| **Business Decision** | Unverified signatures cannot be used as legal proof of offer acceptance. Low verification rate is a compliance risk and may require manual re-verification. |
| **Action Trigger** | If Verification Success Rate falls below 90%, escalate to the e-sign provider under the SLA. If below 80%, pause e-sign flows and notify legal and HR leadership. |

**SQL Source:**
```sql
SELECT ROUND(
    100.0 * SUM(CASE WHEN verification_status = 'verified' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(*), 0)
, 2)
FROM signatures
```

---

### M13 · Verification Failure Rate (%)

| Field | Value |
|-------|-------|
| **Category** | E-Sign Quality |
| **Description** | Percentage of signatures where verification failed outright. The complement of M12 minus any pending verifications. |
| **Event Dependency** | `signatures` table (`verification_status = 'failed'`) |
| **Business Decision** | Directly affects legal validity. Each failed verification requires manual review and potential re-signing. High failure rate inflates HR-ops workload and delays onboarding. |
| **Action Trigger** | If Verification Failure Rate exceeds 10%, pause automated e-sign flows and notify the legal team. Investigate provider error codes in `verification_logs.error_message`. |

**SQL Source:**
```sql
SELECT ROUND(
    100.0 * SUM(CASE WHEN verification_status = 'failed' THEN 1 ELSE 0 END)
          / NULLIF(COUNT(*), 0)
, 2)
FROM signatures
```

---

### M14 · Avg Time Generated → Sent (hrs)

| Field | Value |
|-------|-------|
| **Category** | Latency |
| **Description** | Mean hours between `offer_generated` and `offer_sent` events for the same offer. Measures HR-ops processing speed. |
| **Event Dependency** | `offer_generated`, `offer_sent` |
| **Business Decision** | A long generation-to-send lag signals HR-ops bottlenecks, approval chain delays, or document preparation issues. In competitive hiring, every hour of delay increases the risk of losing the candidate. |
| **Action Trigger** | If average exceeds 4 hours, review the offer preparation and approval workflow. Consider pre-approved offer templates to eliminate manual drafting time. |

**SQL Source:**
```sql
SELECT ROUND(
    AVG(
        (JULIANDAY(e_sent.timestamp) - JULIANDAY(e_gen.timestamp)) * 24
    )
, 2)
FROM offer_events e_gen
JOIN offer_events e_sent
  ON  e_gen.offer_id    = e_sent.offer_id
  AND e_gen.event_name  = 'offer_generated'
  AND e_sent.event_name = 'offer_sent'
```

**Benchmark:** Best-in-class hiring teams send offers within 1 hour of generation.

---

### M15 · Avg Time Sent → Viewed (hrs)

| Field | Value |
|-------|-------|
| **Category** | Latency |
| **Description** | Mean hours between `offer_sent` and the first `offer_opened` event. Measures candidate responsiveness. |
| **Event Dependency** | `offer_sent`, `offer_opened` |
| **Business Decision** | Long sent-to-viewed lag may indicate the offer went to spam, the candidate is disengaged, or competing offers are distracting them. |
| **Action Trigger** | If average exceeds 24 hours, add an automated nudge (SMS or call) at the 6-hour mark for all unseen offers. |

**SQL Source:**
```sql
SELECT ROUND(
    AVG(
        (JULIANDAY(e_view.timestamp) - JULIANDAY(e_sent.timestamp)) * 24
    )
, 2)
FROM offer_events e_sent
JOIN offer_events e_view
  ON  e_sent.offer_id   = e_view.offer_id
  AND e_sent.event_name = 'offer_sent'
  AND e_view.event_name = 'offer_opened'
```

---

### M16 · Avg Time Viewed → Signed (hrs)

| Field | Value |
|-------|-------|
| **Category** | Latency |
| **Description** | Mean hours between `offer_opened` and `offer_signed` for the same offer. Measures candidate decision speed after engagement. |
| **Event Dependency** | `offer_opened`, `offer_signed` |
| **Business Decision** | A long view-to-sign gap suggests hesitation, competing offers, or friction in the e-sign UX. Triggers a targeted recruiter intervention. |
| **Action Trigger** | If average exceeds 12 hours, schedule a recruiter check-in call for every offer that has been viewed but unsigned for more than 8 hours. |

**SQL Source:**
```sql
SELECT ROUND(
    AVG(
        (JULIANDAY(e_sign.timestamp) - JULIANDAY(e_view.timestamp)) * 24
    )
, 2)
FROM offer_events e_view
JOIN offer_events e_sign
  ON  e_view.offer_id   = e_sign.offer_id
  AND e_view.event_name = 'offer_opened'
  AND e_sign.event_name = 'offer_signed'
```

---

### M17 · Offers Pending Decision

| Field | Value |
|-------|-------|
| **Category** | Pipeline Health |
| **Description** | Count of offers with status `sent` or `viewed` whose expiry deadline has not yet passed. These are live offers awaiting a candidate decision. |
| **Event Dependency** | `offer_sent`, `offer_opened` (via `offers.status` and `offers.expiry_at`) |
| **Business Decision** | Active pipeline requiring recruiter follow-up. Each pending offer is a potential headcount gain that needs nurturing before it expires. |
| **Action Trigger** | For each pending offer within 48 hours of expiry with no decision, trigger an automated reminder email and flag for recruiter outreach. |

**SQL Source:**
```sql
SELECT COUNT(*)
FROM offers
WHERE status IN ('sent', 'viewed')
  AND expiry_at > datetime('now')
```

---

### M18 · Offers Expired

| Field | Value |
|-------|-------|
| **Category** | Pipeline Health |
| **Description** | Count of offers that passed their validity deadline without a signature or explicit rejection. These represent lost hiring opportunities. |
| **Event Dependency** | `offer_generated`, `offer_sent` (via `offers.expiry_at`) |
| **Business Decision** | Expired offers represent lost headcount. High expiry rate signals the validity window is too short, follow-up is insufficient, or candidate quality in the pipeline is low. |
| **Action Trigger** | If Expired Offers exceed 5% of Sent in any rolling 7-day window, review the offer validity window length and recruiter follow-up cadence. |

**SQL Source:**
```sql
SELECT COUNT(*)
FROM offers
WHERE status IN ('sent', 'viewed', 'generated')
  AND expiry_at <= datetime('now')
```

---

### M19 · Top E-Sign Provider

| Field | Value |
|-------|-------|
| **Category** | Operational |
| **Description** | The e-sign provider (Leegality, Digio, DocuSign) handling the highest volume of signatures in the current period. |
| **Event Dependency** | `offer_signed` (via `signatures.provider`) |
| **Business Decision** | Informs contract renewal prioritisation and SLA negotiation. If the top provider has a high failure rate, consider rebalancing volume to a backup provider. |
| **Action Trigger** | If the top provider's verification failure rate exceeds 10%, route new signatures to the next provider and open an SLA escalation ticket. |

**SQL Source:**
```sql
SELECT provider
FROM   signatures
GROUP  BY provider
ORDER  BY COUNT(*) DESC
LIMIT  1
```

---

### M20 · Verification Re-check Rate (%)

| Field | Value |
|-------|-------|
| **Category** | E-Sign Quality |
| **Description** | Percentage of offers that required more than one verification attempt in `verification_logs`. Indicates how often the first automated check fails and a re-check (manual or automated) is needed. |
| **Event Dependency** | `offer_signed` (via `verification_logs` — multiple rows per `offer_id`) |
| **Business Decision** | High re-check rate inflates HR-ops workload and delays onboarding by hours or days. Also signals provider auth-flow instability. |
| **Action Trigger** | If Re-check Rate exceeds 20%, review the provider's Aadhaar OTP / digital signature flow for timeout or rate-limit issues. Engage provider support. |

**SQL Source:**
```sql
SELECT ROUND(
    100.0 * COUNT(*)
          / NULLIF((SELECT COUNT(DISTINCT offer_id) FROM verification_logs), 0)
, 2)
FROM (
    SELECT offer_id
    FROM   verification_logs
    GROUP  BY offer_id
    HAVING COUNT(*) > 1
)
```

---

## Funnel-Level Metrics (Cohort Queries)

The following are computed in `offer_funnel.py` rather than
`metrics_engine.py` because they return multiple rows rather than
a single scalar.

| Metric | Source | Output |
|--------|--------|--------|
| Funnel Stage Counts | `offer_events` GROUP BY `event_name` | 5-row funnel |
| Stage Drop-off Rates | self-JOIN `offer_events` | Per-transition loss % |
| Weekly Cohort Conversion | `offer_events` + `STRFTIME` | Trend table |
| Department Conversion | `offer_events` JOIN `candidates` | Per-dept breakdown |
| Channel Conversion | `offer_events` JOIN `candidates` | Per-channel breakdown |
| Time-to-Sign Distribution | self-JOIN `offer_events` | 6-bucket histogram |
| Rejection Reason Breakdown | `JSON_EXTRACT(metadata, '$.reason')` | Reason counts |
| Provider Performance | `signatures` JOIN `verification_logs` | Per-provider stats |

---

## Metric Interdependencies

```
M01 Generated
  └── M06 Send Rate %         (M02 / M01)
        └── M02 Sent
              └── M07 View Rate %      (M03 / M02)
                    └── M15 Sent→Viewed latency
                          └── M03 Viewed
                                ├── M09 Sign-to-View %  (M04 / M03)
                                │     └── M16 Viewed→Signed latency
                                └── M10 Rejection Rate % (M05 / M03)

M01 Generated
  └── M08 Conversion Rate %   (M04 / M01)  ← North Star

M04 Signed
  └── M11 Signature Completion %
        └── signatures table
              ├── M12 Verification Success %
              ├── M13 Verification Failure %
              ├── M19 Top Provider
              └── M20 Re-check Rate %
                    └── verification_logs
```

---

## Validation Rules (Logical Constraints)

These must always hold. Violations indicate a data pipeline bug:

| Rule | Expression | Severity |
|------|-----------|----------|
| Sent ≤ Generated | M02 ≤ M01 | CRITICAL |
| Viewed ≤ Sent | M03 ≤ M02 | CRITICAL |
| Signed ≤ Viewed | M04 ≤ M03 | CRITICAL |
| Rejected ≤ Viewed | M05 ≤ M03 | CRITICAL |
| Signed + Rejected ≤ Viewed | M04 + M05 ≤ M03 | CRITICAL |
| Sig Completion ≤ 100% | M11 ≤ 100 | CRITICAL |
| Verif Success + Failure ≤ 100% | M12 + M13 ≤ 100 | CRITICAL |
| Conversion ≤ View Rate | M08 ≤ M07 | WARNING |

All constraints are enforced automatically in `validation.py`
under the **Metric Reconciliation** check category.

---

## Adding a New Metric

1. Add an entry to `METRIC_REGISTRY` in `metrics_engine.py`
2. Fill all four required fields: `event_dependency`, `business_decision`,
   `action_trigger`, `sql`
3. Add a row to this file under the appropriate section
4. Add a reconciliation check to `validation.py` if the metric
   has a logical relationship to an existing one
5. Reference it in `dashboard.py` by its registered `name` string

---

*Metric Dictionary v1 · PlaceMux · Task 11 · All metrics sourced from live SQLite event tables*
