"""
offer_funnel.py
===============
PlaceMux · Task 11 · Offer Generation & E-Sign Design
------------------------------------------------------
Dedicated funnel analytics module.

Execution order: 6 of 11
Import: from offer_funnel import FunnelAnalytics

Provides
--------
  get_funnel_summary()        – ordered stage counts + drop-off rates
  get_stage_dropoff()         – pct lost at each transition
  get_cohort_by_week()        – weekly cohort conversion table
  get_cohort_by_department()  – per-department funnel breakdown
  get_cohort_by_channel()     – per source-channel breakdown
  get_time_to_sign_dist()     – histogram buckets for view→sign latency
  get_top_drop_offers()       – offers that stalled and why
  export_metrics_csv()        – writes exports/offer_metrics_export.csv

Every query is named, documented, and returns plain dicts so that
dashboard.py can consume them without knowing SQL.
"""

import csv
import logging
import sqlite3
from pathlib import Path
from typing import Any

from config import DB_PATH, EXPORTS_DIR, EXPORT_FILENAME

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _q(conn: sqlite3.Connection, sql: str, params: dict = {}) -> list[dict]:
    """Execute SQL and return list of plain dicts."""
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    except sqlite3.Error as exc:
        log.error("FunnelAnalytics query error: %s | sql: %.80s", exc, sql.strip())
        return []


def _scalar(conn: sqlite3.Connection, sql: str, params: dict = {}) -> Any:
    rows = _q(conn, sql, params)
    if rows:
        first = rows[0]
        return next(iter(first.values()))
    return None


def _pct(numerator: int | float, denominator: int | float) -> float:
    """Safe percentage rounded to 2 dp."""
    if not denominator:
        return 0.0
    return round(100.0 * numerator / denominator, 2)


# ── FunnelAnalytics class ─────────────────────────────────────────────────────

class FunnelAnalytics:
    """
    All offer-funnel computations sourced from SQLite event tables.

    Parameters
    ----------
    db_path : str
        Path to placemux_offer.db  (defaults to config.DB_PATH).
    """

    # Canonical funnel order
    FUNNEL_STAGES = [
        ("offer_generated", "Generated"),
        ("offer_sent",      "Sent"),
        ("offer_opened",    "Viewed"),
        ("offer_signed",    "Signed"),
        ("offer_rejected",  "Rejected"),
    ]

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    # ── 1. Funnel summary ─────────────────────────────────────────────────

    def get_funnel_summary(self) -> list[dict]:
        """
        Returns one dict per stage:
          stage, event, count, pct_of_generated, pct_of_prev_stage,
          drop_from_prev (absolute), drop_rate_pct

        SQL source: offer_events (grouped by event_name)
        Business decision: identify weakest conversion step.
        Action trigger: any drop > 30% from prev stage triggers review.
        """
        sql = """
            SELECT event_name, COUNT(DISTINCT offer_id) AS cnt
            FROM   offer_events
            WHERE  event_name IN (
                'offer_generated','offer_sent',
                'offer_opened','offer_signed','offer_rejected'
            )
            GROUP BY event_name
        """
        conn = _connect(self.db_path)
        raw  = {r["event_name"]: r["cnt"] for r in _q(conn, sql)}
        conn.close()

        stages  = []
        base    = raw.get("offer_generated", 0)
        prev    = None

        for event, label in self.FUNNEL_STAGES:
            count = raw.get(event, 0)

            pct_of_generated = _pct(count, base)
            pct_of_prev      = _pct(count, prev) if prev is not None else 100.0
            drop_from_prev   = (prev - count) if prev is not None else 0
            drop_rate_pct    = _pct(drop_from_prev, prev) if prev else 0.0

            stages.append({
                "stage":            label,
                "event":            event,
                "count":            count,
                "pct_of_generated": pct_of_generated,
                "pct_of_prev":      pct_of_prev,
                "drop_from_prev":   drop_from_prev,
                "drop_rate_pct":    drop_rate_pct,
            })

            # Rejected is a parallel branch — don't chain it as prev
            if event != "offer_rejected":
                prev = count

        return stages

    # ── 2. Stage drop-off table ───────────────────────────────────────────

    def get_stage_dropoff(self) -> list[dict]:
        """
        Explicit transition table: from_stage → to_stage with
        count retained, count lost, and loss rate.

        SQL source: self-join on offer_events
        Business decision: pinpoints which transition to fix first.
        Action trigger: loss rate > 20% on any transition.
        """
        transitions = [
            ("offer_generated", "offer_sent",    "Generated → Sent"),
            ("offer_sent",      "offer_opened",  "Sent → Viewed"),
            ("offer_opened",    "offer_signed",  "Viewed → Signed"),
            ("offer_opened",    "offer_rejected","Viewed → Rejected"),
        ]

        sql_tmpl = """
            SELECT
                COUNT(DISTINCT e_from.offer_id) AS from_count,
                COUNT(DISTINCT e_to.offer_id)   AS to_count
            FROM offer_events e_from
            LEFT JOIN offer_events e_to
                   ON e_from.offer_id   = e_to.offer_id
                  AND e_to.event_name   = :to_event
            WHERE e_from.event_name = :from_event
        """

        conn = _connect(self.db_path)
        rows = []
        for from_ev, to_ev, label in transitions:
            result = _q(conn, sql_tmpl,
                        {"from_event": from_ev, "to_event": to_ev})
            if result:
                r          = result[0]
                from_count = r["from_count"]
                to_count   = r["to_count"]
                lost       = from_count - to_count
                rows.append({
                    "transition":   label,
                    "from_event":   from_ev,
                    "to_event":     to_ev,
                    "from_count":   from_count,
                    "to_count":     to_count,
                    "lost":         lost,
                    "loss_rate_pct": _pct(lost, from_count),
                    "retention_pct": _pct(to_count, from_count),
                })
        conn.close()
        return rows

    # ── 3. Weekly cohort breakdown ────────────────────────────────────────

    def get_cohort_by_week(self) -> list[dict]:
        """
        Groups offers by ISO week of generation and tracks how many
        reached each stage within that cohort.

        SQL source: offer_events joined to itself
        Business decision: trend analysis — is conversion improving week-on-week?
        Action trigger: if any week's conversion < 40%, flag for review.
        """
        sql = """
            SELECT
                STRFTIME('%Y-W%W', gen.timestamp)              AS week,
                COUNT(DISTINCT gen.offer_id)                   AS generated,
                COUNT(DISTINCT sent.offer_id)                  AS sent,
                COUNT(DISTINCT viewed.offer_id)                AS viewed,
                COUNT(DISTINCT signed.offer_id)                AS signed,
                COUNT(DISTINCT rejected.offer_id)              AS rejected,
                ROUND(
                    100.0 * COUNT(DISTINCT signed.offer_id)
                          / NULLIF(COUNT(DISTINCT gen.offer_id), 0)
                , 2)                                           AS conversion_pct
            FROM offer_events gen
            LEFT JOIN offer_events sent
                   ON gen.offer_id = sent.offer_id
                  AND sent.event_name = 'offer_sent'
            LEFT JOIN offer_events viewed
                   ON gen.offer_id = viewed.offer_id
                  AND viewed.event_name = 'offer_opened'
            LEFT JOIN offer_events signed
                   ON gen.offer_id = signed.offer_id
                  AND signed.event_name = 'offer_signed'
            LEFT JOIN offer_events rejected
                   ON gen.offer_id = rejected.offer_id
                  AND rejected.event_name = 'offer_rejected'
            WHERE gen.event_name = 'offer_generated'
            GROUP BY STRFTIME('%Y-W%W', gen.timestamp)
            ORDER BY week ASC
        """
        conn  = _connect(self.db_path)
        rows  = _q(conn, sql)
        conn.close()
        return rows

    # ── 4. Cohort by department ───────────────────────────────────────────

    def get_cohort_by_department(self) -> list[dict]:
        """
        Per-department funnel: counts at each stage + conversion rate.

        SQL source: offer_events JOIN offers JOIN candidates
        Business decision: which department has the worst offer acceptance?
        Action trigger: department conversion < 30% → escalate to dept head.
        """
        sql = """
            SELECT
                c.department,
                COUNT(DISTINCT gen.offer_id)      AS generated,
                COUNT(DISTINCT sent.offer_id)     AS sent,
                COUNT(DISTINCT viewed.offer_id)   AS viewed,
                COUNT(DISTINCT signed.offer_id)   AS signed,
                COUNT(DISTINCT rejected.offer_id) AS rejected,
                ROUND(
                    100.0 * COUNT(DISTINCT signed.offer_id)
                          / NULLIF(COUNT(DISTINCT gen.offer_id), 0)
                , 2)                              AS conversion_pct
            FROM offer_events gen
            JOIN offers    o ON gen.offer_id    = o.offer_id
            JOIN candidates c ON o.candidate_id = c.candidate_id
            LEFT JOIN offer_events sent
                   ON gen.offer_id = sent.offer_id
                  AND sent.event_name = 'offer_sent'
            LEFT JOIN offer_events viewed
                   ON gen.offer_id = viewed.offer_id
                  AND viewed.event_name = 'offer_opened'
            LEFT JOIN offer_events signed
                   ON gen.offer_id = signed.offer_id
                  AND signed.event_name = 'offer_signed'
            LEFT JOIN offer_events rejected
                   ON gen.offer_id = rejected.offer_id
                  AND rejected.event_name = 'offer_rejected'
            WHERE gen.event_name = 'offer_generated'
            GROUP BY c.department
            ORDER BY conversion_pct DESC
        """
        conn = _connect(self.db_path)
        rows = _q(conn, sql)
        conn.close()
        return rows

    # ── 5. Cohort by source channel ───────────────────────────────────────

    def get_cohort_by_channel(self) -> list[dict]:
        """
        Per source-channel funnel: which acquisition channel produces
        candidates most likely to accept an offer?

        SQL source: offer_events JOIN offers JOIN candidates
        Business decision: focus sourcing spend on highest-converting channel.
        Action trigger: channel conversion < 35% → deprioritise channel.
        """
        sql = """
            SELECT
                c.source_channel                  AS channel,
                COUNT(DISTINCT gen.offer_id)      AS generated,
                COUNT(DISTINCT sent.offer_id)     AS sent,
                COUNT(DISTINCT viewed.offer_id)   AS viewed,
                COUNT(DISTINCT signed.offer_id)   AS signed,
                ROUND(
                    100.0 * COUNT(DISTINCT signed.offer_id)
                          / NULLIF(COUNT(DISTINCT gen.offer_id), 0)
                , 2)                              AS conversion_pct
            FROM offer_events gen
            JOIN offers     o ON gen.offer_id    = o.offer_id
            JOIN candidates c ON o.candidate_id  = c.candidate_id
            LEFT JOIN offer_events sent
                   ON gen.offer_id = sent.offer_id
                  AND sent.event_name = 'offer_sent'
            LEFT JOIN offer_events viewed
                   ON gen.offer_id = viewed.offer_id
                  AND viewed.event_name = 'offer_opened'
            LEFT JOIN offer_events signed
                   ON gen.offer_id = signed.offer_id
                  AND signed.event_name = 'offer_signed'
            WHERE gen.event_name = 'offer_generated'
            GROUP BY c.source_channel
            ORDER BY conversion_pct DESC
        """
        conn = _connect(self.db_path)
        rows = _q(conn, sql)
        conn.close()
        return rows

    # ── 6. Time-to-sign distribution (histogram buckets) ─────────────────

    def get_time_to_sign_dist(self) -> list[dict]:
        """
        Buckets the view → sign latency in hours into bins:
          <1h, 1–4h, 4–12h, 12–24h, 24–48h, >48h

        SQL source: self-join offer_events on offer_opened + offer_signed
        Business decision: if most sign > 24h later, add a nudge reminder.
        Action trigger: >30% bucket in >24h → add 12h automated follow-up.
        """
        sql = """
            SELECT
                CASE
                    WHEN hours <  1  THEN '< 1 hr'
                    WHEN hours <  4  THEN '1–4 hrs'
                    WHEN hours < 12  THEN '4–12 hrs'
                    WHEN hours < 24  THEN '12–24 hrs'
                    WHEN hours < 48  THEN '24–48 hrs'
                    ELSE '> 48 hrs'
                END              AS bucket,
                COUNT(*)         AS count
            FROM (
                SELECT
                    (JULIANDAY(s.timestamp) - JULIANDAY(v.timestamp)) * 24 AS hours
                FROM offer_events v
                JOIN offer_events s
                  ON v.offer_id   = s.offer_id
                 AND v.event_name = 'offer_opened'
                 AND s.event_name = 'offer_signed'
                WHERE hours >= 0
            )
            GROUP BY bucket
            ORDER BY MIN(hours)
        """
        conn = _connect(self.db_path)
        rows = _q(conn, sql)
        conn.close()

        # Ensure all buckets appear even if count = 0
        ordered_buckets = [
            "< 1 hr", "1–4 hrs", "4–12 hrs",
            "12–24 hrs", "24–48 hrs", "> 48 hrs",
        ]
        raw = {r["bucket"]: r["count"] for r in rows}
        return [
            {"bucket": b, "count": raw.get(b, 0)}
            for b in ordered_buckets
        ]

    # ── 7. Stalled offers (top drop candidates) ───────────────────────────

    def get_top_stalled_offers(self, limit: int = 20) -> list[dict]:
        """
        Offers that were sent or viewed but never signed or rejected,
        ordered by how long they have been idle (oldest first).

        SQL source: offers table + offer_events
        Business decision: these are warm leads — prioritise recruiter follow-up.
        Action trigger: idle > 3 days and not expired → trigger nudge email.
        """
        sql = """
            SELECT
                o.offer_id,
                c.full_name,
                c.email,
                c.department,
                o.role_title,
                o.status,
                o.generated_at,
                o.expiry_at,
                ROUND(
                    (JULIANDAY('now') - JULIANDAY(o.generated_at)) * 24
                , 1)                          AS hours_idle,
                CASE
                    WHEN o.expiry_at <= datetime('now') THEN 'expired'
                    ELSE 'active'
                END                           AS validity
            FROM offers o
            JOIN candidates c ON o.candidate_id = c.candidate_id
            WHERE o.status IN ('sent', 'viewed')
            ORDER BY hours_idle DESC
            LIMIT :limit
        """
        conn = _connect(self.db_path)
        rows = _q(conn, sql, {"limit": limit})
        conn.close()
        return rows

    # ── 8. Rejection reason breakdown ────────────────────────────────────

    def get_rejection_breakdown(self) -> list[dict]:
        """
        Parses JSON metadata on offer_rejected events to count reasons.

        SQL source: offer_events (event_name = 'offer_rejected')
        Business decision: 'compensation_low' dominating → comp-band review.
        Action trigger: any single reason > 40% of total rejections.
        """
        sql = """
            SELECT
                COALESCE(
                    JSON_EXTRACT(metadata, '$.reason'),
                    'unknown'
                )                AS reason,
                COUNT(*)         AS count,
                ROUND(
                    100.0 * COUNT(*)
                          / NULLIF((
                                SELECT COUNT(*)
                                FROM   offer_events
                                WHERE  event_name = 'offer_rejected'
                            ), 0)
                , 2)             AS pct_of_rejections
            FROM offer_events
            WHERE event_name = 'offer_rejected'
            GROUP BY reason
            ORDER BY count DESC
        """
        conn = _connect(self.db_path)
        rows = _q(conn, sql)
        conn.close()
        return rows

    # ── 9. Provider performance summary ──────────────────────────────────

    def get_provider_performance(self) -> list[dict]:
        """
        E-sign provider breakdown with avg verification latency.

        SQL source: signatures JOIN verification_logs
        Business decision: select / renew contract with best-performing provider.
        Action trigger: provider verification success < 90% → SLA escalation.
        """
        sql = """
            SELECT
                s.provider,
                COUNT(s.sign_id)                                                AS total_signatures,
                SUM(CASE WHEN s.verification_status = 'verified' THEN 1 ELSE 0 END) AS verified,
                SUM(CASE WHEN s.verification_status = 'failed'   THEN 1 ELSE 0 END) AS failed,
                ROUND(
                    100.0 * SUM(CASE WHEN s.verification_status = 'verified' THEN 1 ELSE 0 END)
                          / NULLIF(COUNT(s.sign_id), 0)
                , 2)                                                            AS success_rate_pct,
                ROUND(
                    AVG(
                        (JULIANDAY(v.check_time) - JULIANDAY(s.signed_at)) * 60
                    )
                , 1)                                                            AS avg_verify_latency_mins
            FROM signatures s
            LEFT JOIN verification_logs v
                   ON s.offer_id  = v.offer_id
                  AND v.check_type = 'provider_webhook'
            GROUP BY s.provider
            ORDER BY success_rate_pct DESC
        """
        conn = _connect(self.db_path)
        rows = _q(conn, sql)
        conn.close()
        return rows

    # ── 10. Export: full metrics CSV ──────────────────────────────────────

    def export_metrics_csv(self) -> Path:
        """
        Writes a comprehensive CSV of all funnel metrics to
        exports/offer_metrics_export.csv.

        Includes:
          - Funnel summary
          - Stage drop-off
          - Weekly cohort
          - Department cohort
          - Channel cohort
          - Provider performance
          - Rejection breakdown

        Returns
        -------
        Path
            Absolute path to the written CSV.

        SQL source: all queries above
        Business decision: share-able snapshot for async stakeholder review.
        Action trigger: export on demand or schedule daily at 09:00.
        """
        export_path = EXPORTS_DIR / EXPORT_FILENAME

        sections: list[tuple[str, list[dict]]] = [
            ("FUNNEL_SUMMARY",        self.get_funnel_summary()),
            ("STAGE_DROPOFF",         self.get_stage_dropoff()),
            ("COHORT_BY_WEEK",        self.get_cohort_by_week()),
            ("COHORT_BY_DEPARTMENT",  self.get_cohort_by_department()),
            ("COHORT_BY_CHANNEL",     self.get_cohort_by_channel()),
            ("PROVIDER_PERFORMANCE",  self.get_provider_performance()),
            ("REJECTION_BREAKDOWN",   self.get_rejection_breakdown()),
            ("TIME_TO_SIGN_DIST",     self.get_time_to_sign_dist()),
        ]

        try:
            with open(export_path, "w", newline="", encoding="utf-8") as fh:
                writer = None

                for section_name, rows in sections:
                    if not rows:
                        continue

                    # Section header row
                    fh.write(f"## {section_name}\n")

                    # Write rows using DictWriter
                    fieldnames = list(rows[0].keys())
                    w = csv.DictWriter(fh, fieldnames=fieldnames)
                    w.writeheader()
                    w.writerows(rows)
                    fh.write("\n")   # blank line between sections

            log.info("Metrics exported → %s", export_path)
            return export_path

        except OSError as exc:
            log.error("Export failed: %s", exc)
            raise

    # ── 11. Single combined dict for dashboard ────────────────────────────

    def get_all(self) -> dict:
        """
        Convenience method: returns every funnel dataset as a single dict.
        Used by dashboard.py to fetch everything in one call.
        """
        return {
            "funnel_summary":       self.get_funnel_summary(),
            "stage_dropoff":        self.get_stage_dropoff(),
            "cohort_by_week":       self.get_cohort_by_week(),
            "cohort_by_department": self.get_cohort_by_department(),
            "cohort_by_channel":    self.get_cohort_by_channel(),
            "time_to_sign_dist":    self.get_time_to_sign_dist(),
            "top_stalled_offers":   self.get_top_stalled_offers(),
            "rejection_breakdown":  self.get_rejection_breakdown(),
            "provider_performance": self.get_provider_performance(),
        }


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fa = FunnelAnalytics()

    print("\n" + "=" * 65)
    print("  PlaceMux · Offer Funnel Analytics")
    print("=" * 65)

    print("\n── Funnel Summary ───────────────────────────────────────────")
    print(f"  {'Stage':<12} {'Count':>6}  {'Of Generated':>13}  {'Drop Rate':>10}")
    print(f"  {'-'*12} {'-'*6}  {'-'*13}  {'-'*10}")
    for s in fa.get_funnel_summary():
        print(
            f"  {s['stage']:<12} {s['count']:>6}  "
            f"{s['pct_of_generated']:>12.1f}%  "
            f"{s['drop_rate_pct']:>9.1f}%"
        )

    print("\n── Stage Drop-off ───────────────────────────────────────────")
    print(f"  {'Transition':<25} {'From':>6} {'To':>6} {'Lost':>6} {'Loss%':>7}")
    print(f"  {'-'*25} {'-'*6} {'-'*6} {'-'*6} {'-'*7}")
    for d in fa.get_stage_dropoff():
        print(
            f"  {d['transition']:<25} {d['from_count']:>6} "
            f"{d['to_count']:>6} {d['lost']:>6} "
            f"{d['loss_rate_pct']:>6.1f}%"
        )

    print("\n── Cohort by Department ─────────────────────────────────────")
    print(f"  {'Department':<18} {'Gen':>5} {'Sent':>5} "
          f"{'View':>5} {'Sign':>5} {'Conv%':>7}")
    print(f"  {'-'*18} {'-'*5} {'-'*5} {'-'*5} {'-'*5} {'-'*7}")
    for d in fa.get_cohort_by_department():
        print(
            f"  {d['department']:<18} {d['generated']:>5} "
            f"{d['sent']:>5} {d['viewed']:>5} "
            f"{d['signed']:>5} {d['conversion_pct']:>6.1f}%"
        )

    print("\n── Cohort by Source Channel ─────────────────────────────────")
    for d in fa.get_cohort_by_channel():
        print(
            f"  {d['channel']:<18}  gen={d['generated']}  "
            f"signed={d['signed']}  conv={d['conversion_pct']}%"
        )

    print("\n── Time-to-Sign Distribution ────────────────────────────────")
    for b in fa.get_time_to_sign_dist():
        bar = "█" * min(b["count"], 40)
        print(f"  {b['bucket']:<12}  {b['count']:>4}  {bar}")

    print("\n── Provider Performance ─────────────────────────────────────")
    for p in fa.get_provider_performance():
        print(
            f"  {p['provider']:<12}  sigs={p['total_signatures']}  "
            f"success={p['success_rate_pct']}%  "
            f"avg_latency={p['avg_verify_latency_mins']} mins"
        )

    print("\n── Rejection Breakdown ──────────────────────────────────────")
    for r in fa.get_rejection_breakdown():
        print(f"  {str(r['reason']):<28}  n={r['count']}  ({r['pct_of_rejections']}%)")

    print("\n── Top Stalled Offers ───────────────────────────────────────")
    for o in fa.get_top_stalled_offers(limit=5):
        print(
            f"  {o['full_name']:<25}  {o['role_title']:<22}  "
            f"idle={o['hours_idle']}h  [{o['validity']}]"
        )

    # Export
    out = fa.export_metrics_csv()
    print(f"\n✓  Metrics exported → {out}")
    print("=" * 65)

    sys.exit(0)
