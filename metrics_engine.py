"""
metrics_engine.py
=================
PlaceMux · Task 11 · Offer Generation & E-Sign Design
------------------------------------------------------
Central analytics engine.  Every KPI is derived from a named SQL query.
Nothing is hardcoded.  Every metric carries full provenance metadata.

Execution order: 4 of 11
Import: from metrics_engine import MetricsEngine

Metric registry schema
----------------------
Each entry in METRIC_REGISTRY is a dict with:
  name              – human-readable KPI label
  description       – one-line explanation
  sql               – the SQL query that computes it  (returns one row, one col)
  event_dependency  – which offer_events.event_name rows it depends on
  business_decision – what the founder decides based on this number
  action_trigger    – threshold / condition that prompts action

The engine also exposes:
  get_funnel_stages()   – ordered stage counts for the funnel chart
  get_daily_trend()     – daily event volume for time-series charts
  get_esign_breakdown() – per-provider signature & verification stats
  get_rejection_reasons()– breakdown of rejection metadata
  run_all()             – returns every metric as a list of MetricResult
"""

import logging
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from config import DB_PATH

log = logging.getLogger(__name__)

# ── Result container ─────────────────────────────────────────────────────────

@dataclass
class MetricResult:
    """One evaluated KPI with its value and full provenance."""
    name:               str
    value:              Any                  # scalar – int, float, or str
    description:        str        = ""
    event_dependency:   list[str]  = field(default_factory=list)
    business_decision:  str        = ""
    action_trigger:     str        = ""
    sql:                str        = ""
    error:              str | None = None    # set if query failed


# ── Metric registry ───────────────────────────────────────────────────────────
# Every KPI is defined here.  The engine iterates this list — nothing else
# should know the SQL strings.

METRIC_REGISTRY: list[dict] = [

    # ── 1. Total Offers Generated ─────────────────────────────────────────
    {
        "name":        "Total Offers Generated",
        "description": "Count of all offer documents created in the system.",
        "sql": """
            SELECT COUNT(DISTINCT offer_id)
            FROM   offer_events
            WHERE  event_name = 'offer_generated'
        """,
        "event_dependency":  ["offer_generated"],
        "business_decision": "Baseline pipeline volume; used to size HR-ops capacity.",
        "action_trigger":    "If weekly volume drops >20% vs prior week, investigate pipeline.",
    },

    # ── 2. Total Offers Sent ──────────────────────────────────────────────
    {
        "name":        "Total Offers Sent",
        "description": "Offers dispatched to candidates via the delivery channel.",
        "sql": """
            SELECT COUNT(DISTINCT offer_id)
            FROM   offer_events
            WHERE  event_name = 'offer_sent'
        """,
        "event_dependency":  ["offer_sent"],
        "business_decision": "Confirms delivery pipeline is not stuck.",
        "action_trigger":    "Alert if Sent < 90% of Generated within 2 hours of generation.",
    },

    # ── 3. Total Offers Viewed ────────────────────────────────────────────
    {
        "name":        "Total Offers Viewed",
        "description": "Candidates who opened the offer at least once.",
        "sql": """
            SELECT COUNT(DISTINCT offer_id)
            FROM   offer_events
            WHERE  event_name = 'offer_opened'
        """,
        "event_dependency":  ["offer_opened"],
        "business_decision": "Low view rate signals email deliverability or subject-line issues.",
        "action_trigger":    "If View Rate < 70%, review email delivery logs immediately.",
    },

    # ── 4. Total Offers Signed ────────────────────────────────────────────
    {
        "name":        "Total Offers Signed",
        "description": "Offers where the candidate completed the e-sign step.",
        "sql": """
            SELECT COUNT(DISTINCT offer_id)
            FROM   offer_events
            WHERE  event_name = 'offer_signed'
        """,
        "event_dependency":  ["offer_signed"],
        "business_decision": "Primary conversion output; drives headcount forecasting.",
        "action_trigger":    "If Sign Rate < 60% of Viewed, review offer competitiveness.",
    },

    # ── 5. Total Offers Rejected ──────────────────────────────────────────
    {
        "name":        "Total Offers Rejected",
        "description": "Offers explicitly declined by the candidate.",
        "sql": """
            SELECT COUNT(DISTINCT offer_id)
            FROM   offer_events
            WHERE  event_name = 'offer_rejected'
        """,
        "event_dependency":  ["offer_rejected"],
        "business_decision": "High rejection triggers compensation or role-fit review.",
        "action_trigger":    "If Rejection Rate > 15% of Viewed, escalate to hiring manager.",
    },

    # ── 6. Offer Send Rate (%) ────────────────────────────────────────────
    {
        "name":        "Offer Send Rate (%)",
        "description": "Percentage of generated offers that were sent.",
        "sql": """
            SELECT ROUND(
                100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_sent'      THEN offer_id END)
                      / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_generated' THEN offer_id END), 0)
            , 2)
            FROM offer_events
        """,
        "event_dependency":  ["offer_generated", "offer_sent"],
        "business_decision": "Confirms HR-ops is processing generated offers without bottleneck.",
        "action_trigger":    "Alert if Send Rate < 90%.",
    },

    # ── 7. Offer View Rate (%) ────────────────────────────────────────────
    {
        "name":        "Offer View Rate (%)",
        "description": "Percentage of sent offers opened by the candidate.",
        "sql": """
            SELECT ROUND(
                100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_opened' THEN offer_id END)
                      / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_sent'    THEN offer_id END), 0)
            , 2)
            FROM offer_events
        """,
        "event_dependency":  ["offer_sent", "offer_opened"],
        "business_decision": "Measures email reachability and candidate engagement.",
        "action_trigger":    "If View Rate < 70%, review email subject line and delivery.",
    },

    # ── 8. Offer Conversion Rate (%) ──────────────────────────────────────
    {
        "name":        "Offer Conversion Rate (%)",
        "description": "Percentage of generated offers that result in a signature.",
        "sql": """
            SELECT ROUND(
                100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_signed'    THEN offer_id END)
                      / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_generated' THEN offer_id END), 0)
            , 2)
            FROM offer_events
        """,
        "event_dependency":  ["offer_generated", "offer_signed"],
        "business_decision": "North-star metric for the entire offer funnel.",
        "action_trigger":    "If Conversion < 40%, trigger offer strategy review.",
    },

    # ── 9. Sign-to-View Rate (%) ──────────────────────────────────────────
    {
        "name":        "Sign-to-View Rate (%)",
        "description": "Of candidates who opened the offer, what % signed.",
        "sql": """
            SELECT ROUND(
                100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_signed' THEN offer_id END)
                      / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_opened' THEN offer_id END), 0)
            , 2)
            FROM offer_events
        """,
        "event_dependency":  ["offer_opened", "offer_signed"],
        "business_decision": "Isolates intent-to-sign after engagement; removes delivery noise.",
        "action_trigger":    "If Sign-to-View < 65%, review offer terms and follow-up cadence.",
    },

    # ── 10. Rejection Rate (%) ────────────────────────────────────────────
    {
        "name":        "Rejection Rate (%)",
        "description": "Percentage of viewed offers that were explicitly rejected.",
        "sql": """
            SELECT ROUND(
                100.0 * COUNT(DISTINCT CASE WHEN event_name = 'offer_rejected' THEN offer_id END)
                      / NULLIF(COUNT(DISTINCT CASE WHEN event_name = 'offer_opened' THEN offer_id END), 0)
            , 2)
            FROM offer_events
        """,
        "event_dependency":  ["offer_opened", "offer_rejected"],
        "business_decision": "High rejection signals compensation or role mismatch.",
        "action_trigger":    "If Rejection Rate > 15%, review comp-band and role brief.",
    },

    # ── 11. Signature Completion Rate (%) ────────────────────────────────
    {
        "name":        "Signature Completion Rate (%)",
        "description": "Of all e-sign requests initiated, what % have a completed signature.",
        "sql": """
            SELECT ROUND(
                100.0 * COUNT(s.sign_id)
                      / NULLIF(COUNT(DISTINCT e.offer_id), 0)
            , 2)
            FROM offer_events e
            LEFT JOIN signatures s ON e.offer_id = s.offer_id
            WHERE e.event_name = 'offer_signed'
        """,
        "event_dependency":  ["offer_signed"],
        "business_decision": "Confirms e-sign provider is completing flows without drop-off.",
        "action_trigger":    "If < 98%, check e-sign provider error logs.",
    },

    # ── 12. Verification Success Rate (%) ────────────────────────────────
    {
        "name":        "Verification Success Rate (%)",
        "description": "Percentage of signatures that passed tamper / identity verification.",
        "sql": """
            SELECT ROUND(
                100.0 * SUM(CASE WHEN verification_status = 'verified' THEN 1 ELSE 0 END)
                      / NULLIF(COUNT(*), 0)
            , 2)
            FROM signatures
        """,
        "event_dependency":  ["offer_signed"],
        "business_decision": "Low rate signals provider issues or candidate auth failures.",
        "action_trigger":    "If Verification Success < 90%, escalate to e-sign provider SLA.",
    },

    # ── 13. Verification Failure Rate (%) ────────────────────────────────
    {
        "name":        "Verification Failure Rate (%)",
        "description": "Percentage of signatures that failed verification.",
        "sql": """
            SELECT ROUND(
                100.0 * SUM(CASE WHEN verification_status = 'failed' THEN 1 ELSE 0 END)
                      / NULLIF(COUNT(*), 0)
            , 2)
            FROM signatures
        """,
        "event_dependency":  ["offer_signed"],
        "business_decision": "Directly affects legal validity of signed offers.",
        "action_trigger":    "If > 10%, pause e-sign flows and notify legal team.",
    },

    # ── 14. Avg Time: Generated → Sent (hours) ───────────────────────────
    {
        "name":        "Avg Time Generated → Sent (hrs)",
        "description": "Mean hours between offer creation and dispatch.",
        "sql": """
            SELECT ROUND(
                AVG(
                    (JULIANDAY(e_sent.timestamp) - JULIANDAY(e_gen.timestamp)) * 24
                )
            , 2)
            FROM offer_events e_gen
            JOIN offer_events e_sent
              ON  e_gen.offer_id   = e_sent.offer_id
              AND e_gen.event_name = 'offer_generated'
              AND e_sent.event_name = 'offer_sent'
        """,
        "event_dependency":  ["offer_generated", "offer_sent"],
        "business_decision": "Measures HR-ops processing speed.",
        "action_trigger":    "If avg > 4 hrs, review HR-ops workflow for bottlenecks.",
    },

    # ── 15. Avg Time: Sent → Viewed (hours) ──────────────────────────────
    {
        "name":        "Avg Time Sent → Viewed (hrs)",
        "description": "Mean hours between dispatch and first candidate open.",
        "sql": """
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
        """,
        "event_dependency":  ["offer_sent", "offer_opened"],
        "business_decision": "Measures candidate responsiveness; flags low-urgency offers.",
        "action_trigger":    "If avg > 24 hrs, add a follow-up nudge email.",
    },

    # ── 16. Avg Time: Viewed → Signed (hours) ────────────────────────────
    {
        "name":        "Avg Time Viewed → Signed (hrs)",
        "description": "Mean hours between first open and signature completion.",
        "sql": """
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
        """,
        "event_dependency":  ["offer_opened", "offer_signed"],
        "business_decision": "Long view-to-sign time suggests hesitation or competing offers.",
        "action_trigger":    "If avg > 12 hrs, trigger a recruiter check-in call.",
    },

    # ── 17. Offers Pending (not yet signed or rejected) ───────────────────
    {
        "name":        "Offers Pending Decision",
        "description": "Offers sent and viewed but not yet signed or rejected.",
        "sql": """
            SELECT COUNT(*)
            FROM offers
            WHERE status IN ('sent', 'viewed')
              AND expiry_at > datetime('now')
        """,
        "event_dependency":  ["offer_sent", "offer_opened"],
        "business_decision": "Active pipeline requiring recruiter follow-up.",
        "action_trigger":    "For each pending offer approaching expiry, trigger a nudge.",
    },

    # ── 18. Offers Expired ────────────────────────────────────────────────
    {
        "name":        "Offers Expired",
        "description": "Offers past their validity deadline with no signature or rejection.",
        "sql": """
            SELECT COUNT(*)
            FROM offers
            WHERE status IN ('sent', 'viewed', 'generated')
              AND expiry_at <= datetime('now')
        """,
        "event_dependency":  ["offer_generated", "offer_sent"],
        "business_decision": "Expired offers represent lost headcount; triggers re-engagement.",
        "action_trigger":    "If Expired > 5% of Sent, review offer validity window.",
    },

    # ── 19. Most-used E-Sign Provider ────────────────────────────────────
    {
        "name":        "Top E-Sign Provider",
        "description": "Provider handling the highest volume of signatures.",
        "sql": """
            SELECT provider
            FROM   signatures
            GROUP  BY provider
            ORDER  BY COUNT(*) DESC
            LIMIT  1
        """,
        "event_dependency":  ["offer_signed"],
        "business_decision": "Informs contract renewal prioritisation with providers.",
        "action_trigger":    "If top provider has verification failure > 10%, switch provider.",
    },

    # ── 20. Verification Re-check Rate (%) ───────────────────────────────
    {
        "name":        "Verification Re-check Rate (%)",
        "description": "Percentage of offers that required more than one verification attempt.",
        "sql": """
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
        """,
        "event_dependency":  ["offer_signed"],
        "business_decision": "High re-check rate inflates cost and delays onboarding.",
        "action_trigger":    "If Re-check Rate > 20%, review provider auth flow.",
    },
]


# ── Engine class ──────────────────────────────────────────────────────────────

class MetricsEngine:
    """
    Executes all registered SQL metrics against the live SQLite database.

    Usage
    -----
    engine = MetricsEngine()
    results = engine.run_all()          # list[MetricResult]
    funnel  = engine.get_funnel_stages()
    daily   = engine.get_daily_trend()
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    # ── Connection helper ────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    # ── Single metric evaluation ─────────────────────────────────────────

    def _evaluate(self, conn: sqlite3.Connection, metric: dict) -> MetricResult:
        """Run one metric's SQL and return a MetricResult."""
        try:
            cur  = conn.execute(metric["sql"])
            row  = cur.fetchone()
            value = row[0] if row else None
        except sqlite3.Error as exc:
            log.error("SQL error for metric '%s': %s", metric["name"], exc)
            return MetricResult(
                name=metric["name"],
                value=None,
                description=metric.get("description", ""),
                event_dependency=metric.get("event_dependency", []),
                business_decision=metric.get("business_decision", ""),
                action_trigger=metric.get("action_trigger", ""),
                sql=metric["sql"],
                error=str(exc),
            )

        return MetricResult(
            name=metric["name"],
            value=value,
            description=metric.get("description", ""),
            event_dependency=metric.get("event_dependency", []),
            business_decision=metric.get("business_decision", ""),
            action_trigger=metric.get("action_trigger", ""),
            sql=metric["sql"],
            error=None,
        )

    # ── Public: run all KPIs ─────────────────────────────────────────────

    def run_all(self) -> list[MetricResult]:
        """
        Evaluate every metric in METRIC_REGISTRY.

        Returns
        -------
        list[MetricResult]
            One entry per registry item, in registration order.
        """
        results = []
        try:
            conn = self._connect()
            for metric in METRIC_REGISTRY:
                result = self._evaluate(conn, metric)
                results.append(result)
                log.debug("  %s = %s", result.name, result.value)
        except sqlite3.Error as exc:
            log.critical("Cannot connect to database: %s", exc)
        finally:
            if "conn" in locals():
                conn.close()

        return results

    # ── Public: funnel stage counts ──────────────────────────────────────

    def get_funnel_stages(self) -> list[dict]:
        """
        Returns ordered funnel stages for chart rendering.

        Returns
        -------
        list of {"stage": str, "count": int, "event": str}
        """
        sql = """
            SELECT
                event_name,
                COUNT(DISTINCT offer_id) AS cnt
            FROM offer_events
            WHERE event_name IN (
                'offer_generated',
                'offer_sent',
                'offer_opened',
                'offer_signed',
                'offer_rejected'
            )
            GROUP BY event_name
        """
        ORDER = [
            "offer_generated",
            "offer_sent",
            "offer_opened",
            "offer_signed",
            "offer_rejected",
        ]
        LABELS = {
            "offer_generated": "Generated",
            "offer_sent":      "Sent",
            "offer_opened":    "Viewed",
            "offer_signed":    "Signed",
            "offer_rejected":  "Rejected",
        }

        try:
            conn = self._connect()
            rows = conn.execute(sql).fetchall()
            conn.close()
        except sqlite3.Error as exc:
            log.error("get_funnel_stages error: %s", exc)
            return []

        raw = {row["event_name"]: row["cnt"] for row in rows}
        return [
            {
                "stage": LABELS[e],
                "event": e,
                "count": raw.get(e, 0),
            }
            for e in ORDER
        ]

    # ── Public: daily event volume trend ─────────────────────────────────

    def get_daily_trend(self, days: int = 30) -> list[dict]:
        """
        Daily counts of each event type over the last `days` days.

        Returns
        -------
        list of {"date": str, "event_name": str, "count": int}
        """
        sql = """
            SELECT
                DATE(timestamp)  AS date,
                event_name,
                COUNT(*)         AS cnt
            FROM offer_events
            WHERE timestamp >= datetime('now', :offset)
            GROUP BY DATE(timestamp), event_name
            ORDER BY date ASC, event_name ASC
        """
        offset = f"-{days} days"
        try:
            conn  = self._connect()
            rows  = conn.execute(sql, {"offset": offset}).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except sqlite3.Error as exc:
            log.error("get_daily_trend error: %s", exc)
            return []

    # ── Public: e-sign provider breakdown ────────────────────────────────

    def get_esign_breakdown(self) -> list[dict]:
        """
        Per-provider signature volume and verification outcome counts.

        Returns
        -------
        list of {"provider", "total", "verified", "failed", "pending",
                 "success_rate_pct"}
        """
        sql = """
            SELECT
                provider,
                COUNT(*)                                                   AS total,
                SUM(CASE WHEN verification_status = 'verified' THEN 1 ELSE 0 END) AS verified,
                SUM(CASE WHEN verification_status = 'failed'   THEN 1 ELSE 0 END) AS failed,
                SUM(CASE WHEN verification_status = 'pending'  THEN 1 ELSE 0 END) AS pending,
                ROUND(
                    100.0
                    * SUM(CASE WHEN verification_status = 'verified' THEN 1 ELSE 0 END)
                    / NULLIF(COUNT(*), 0)
                , 2) AS success_rate_pct
            FROM signatures
            GROUP BY provider
            ORDER BY total DESC
        """
        try:
            conn  = self._connect()
            rows  = conn.execute(sql).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except sqlite3.Error as exc:
            log.error("get_esign_breakdown error: %s", exc)
            return []

    # ── Public: rejection reason breakdown ───────────────────────────────

    def get_rejection_reasons(self) -> list[dict]:
        """
        Parses the JSON metadata field on offer_rejected events to
        count rejection reasons.

        Returns
        -------
        list of {"reason": str, "count": int}
        """
        sql = """
            SELECT
                JSON_EXTRACT(metadata, '$.reason') AS reason,
                COUNT(*)                           AS cnt
            FROM offer_events
            WHERE event_name = 'offer_rejected'
            GROUP BY reason
            ORDER BY cnt DESC
        """
        try:
            conn  = self._connect()
            rows  = conn.execute(sql).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except sqlite3.Error as exc:
            log.error("get_rejection_reasons error: %s", exc)
            return []

    # ── Public: verification trend ───────────────────────────────────────

    def get_verification_trend(self, days: int = 30) -> list[dict]:
        """
        Daily verification pass/fail counts for the last `days` days.

        Returns
        -------
        list of {"date": str, "result": str, "count": int}
        """
        sql = """
            SELECT
                DATE(check_time) AS date,
                result,
                COUNT(*)         AS cnt
            FROM verification_logs
            WHERE check_time >= datetime('now', :offset)
            GROUP BY DATE(check_time), result
            ORDER BY date ASC, result ASC
        """
        offset = f"-{days} days"
        try:
            conn  = self._connect()
            rows  = conn.execute(sql, {"offset": offset}).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except sqlite3.Error as exc:
            log.error("get_verification_trend error: %s", exc)
            return []

    # ── Public: get single metric by name ────────────────────────────────

    def get_metric(self, name: str) -> MetricResult | None:
        """
        Evaluate and return a single metric by its registered name.
        Returns None if the name is not found.
        """
        match = next((m for m in METRIC_REGISTRY if m["name"] == name), None)
        if not match:
            log.warning("Metric not found in registry: '%s'", name)
            return None
        try:
            conn   = self._connect()
            result = self._evaluate(conn, match)
            conn.close()
            return result
        except sqlite3.Error as exc:
            log.error("get_metric DB error: %s", exc)
            return None


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    engine  = MetricsEngine()
    results = engine.run_all()

    print("\n" + "=" * 62)
    print("  PlaceMux · Offer Funnel KPIs")
    print("=" * 62)
    errors = 0
    for r in results:
        status = "✓" if r.error is None else "✗"
        print(f"  {status}  {r.name:<40}  {r.value}")
        if r.error:
            print(f"     ERROR: {r.error}")
            errors += 1

    print("=" * 62)
    print(f"  {len(results)} metrics evaluated  |  {errors} error(s)")

    print("\n── Funnel Stages ────────────────────────────────────────")
    for stage in engine.get_funnel_stages():
        print(f"  {stage['stage']:<14}  {stage['count']:>5}")

    print("\n── E-Sign Breakdown ─────────────────────────────────────")
    for row in engine.get_esign_breakdown():
        print(f"  {row['provider']:<12}  total={row['total']}  "
              f"verified={row['verified']}  success={row['success_rate_pct']}%")

    print("\n── Rejection Reasons ────────────────────────────────────")
    for row in engine.get_rejection_reasons():
        print(f"  {str(row['reason']):<28}  {row['cnt']}")

    sys.exit(0 if errors == 0 else 1)
