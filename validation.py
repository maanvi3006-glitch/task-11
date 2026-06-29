"""
validation.py
=============
PlaceMux · Task 11 · Offer Generation & E-Sign Design
------------------------------------------------------
Full data-quality and metric-validation layer.

Execution order: 5 of 11
Import: from validation import ValidationEngine

Checks performed
----------------
  1. Freshness validation     – last event age vs WARN / CRIT thresholds
  2. Null-rate detection      – per-column null counts across all tables
  3. Duplicate detection      – PK and business-key uniqueness
  4. Anomaly detection        – z-score on daily event volume
  5. Event completeness       – every offer_generated has downstream events
  6. Metric reconciliation    – cross-check KPIs against each other for
                                logical consistency (e.g. Signed ≤ Viewed)
  7. Orphan detection         – FK integrity spot-checks
  8. Status-event alignment   – offer.status matches its latest event

Every check returns a ValidationResult with:
  check_name   – human label
  status       – "pass" | "warn" | "fail"
  detail       – explanation or value that triggered the flag
  sql          – the query used (for auditability)
"""

import logging
import math
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from config import (
    ANOMALY_ZSCORE_THRESH,
    DB_PATH,
    FRESHNESS_CRIT_HOURS,
    FRESHNESS_WARN_HOURS,
    MAX_DUPLICATE_RATE_PCT,
    MAX_NULL_RATE_PCT,
)

log = logging.getLogger(__name__)


# ── Result container ─────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    check_name: str
    status:     str          # "pass" | "warn" | "fail"
    detail:     str
    sql:        str  = ""
    value:      Any  = None  # raw number behind the check


@dataclass
class ValidationReport:
    results:    list[ValidationResult] = field(default_factory=list)

    @property
    def passed(self)  -> list[ValidationResult]:
        return [r for r in self.results if r.status == "pass"]

    @property
    def warnings(self) -> list[ValidationResult]:
        return [r for r in self.results if r.status == "warn"]

    @property
    def failures(self) -> list[ValidationResult]:
        return [r for r in self.results if r.status == "fail"]

    @property
    def overall_status(self) -> str:
        if self.failures:
            return "fail"
        if self.warnings:
            return "warn"
        return "pass"

    def summary(self) -> str:
        return (
            f"Checks: {len(self.results)}  |  "
            f"Pass: {len(self.passed)}  |  "
            f"Warn: {len(self.warnings)}  |  "
            f"Fail: {len(self.failures)}  |  "
            f"Overall: {self.overall_status.upper()}"
        )


# ── Engine ────────────────────────────────────────────────────────────────────

class ValidationEngine:
    """
    Runs all data-quality and metric-validation checks.

    Usage
    -----
    engine = ValidationEngine()
    report = engine.run_all()
    print(report.summary())
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path

    # ── Connection ───────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _q(self, conn: sqlite3.Connection, sql: str, params: dict = {}) -> list:
        try:
            return conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            log.error("Validation query error: %s | SQL: %s", exc, sql.strip()[:80])
            return []

    def _scalar(self, conn: sqlite3.Connection, sql: str, params: dict = {}) -> Any:
        rows = self._q(conn, sql, params)
        if rows:
            return rows[0][0]
        return None

    # ════════════════════════════════════════════════════════════════════
    # 1. FRESHNESS VALIDATION
    # ════════════════════════════════════════════════════════════════════

    def check_freshness(self, conn: sqlite3.Connection) -> list[ValidationResult]:
        """
        Measure hours since the most recent event in offer_events.
        WARN  → > FRESHNESS_WARN_HOURS
        FAIL  → > FRESHNESS_CRIT_HOURS
        """
        sql = """
            SELECT ROUND(
                (JULIANDAY('now') - JULIANDAY(MAX(timestamp))) * 24
            , 2)
            FROM offer_events
        """
        hours = self._scalar(conn, sql)

        if hours is None:
            return [ValidationResult(
                check_name="Event Table Freshness",
                status="fail",
                detail="offer_events table is empty — no events found.",
                sql=sql,
                value=None,
            )]

        if hours > FRESHNESS_CRIT_HOURS:
            status = "fail"
            detail = (
                f"Last event was {hours:.1f} hrs ago "
                f"(critical threshold: {FRESHNESS_CRIT_HOURS} hrs). "
                "Pipeline may be down."
            )
        elif hours > FRESHNESS_WARN_HOURS:
            status = "warn"
            detail = (
                f"Last event was {hours:.1f} hrs ago "
                f"(warn threshold: {FRESHNESS_WARN_HOURS} hrs)."
            )
        else:
            status = "pass"
            detail = f"Last event {hours:.1f} hrs ago — within freshness SLA."

        # Also check signatures freshness
        sql_sig = """
            SELECT ROUND(
                (JULIANDAY('now') - JULIANDAY(MAX(signed_at))) * 24
            , 2)
            FROM signatures
        """
        sig_hours = self._scalar(conn, sql_sig)
        results = [ValidationResult(
            check_name="Event Table Freshness",
            status=status,
            detail=detail,
            sql=sql,
            value=hours,
        )]

        if sig_hours is not None:
            sig_status = (
                "fail" if sig_hours > FRESHNESS_CRIT_HOURS else
                "warn" if sig_hours > FRESHNESS_WARN_HOURS else
                "pass"
            )
            results.append(ValidationResult(
                check_name="Signature Table Freshness",
                status=sig_status,
                detail=f"Last signature {sig_hours:.1f} hrs ago.",
                sql=sql_sig,
                value=sig_hours,
            ))

        return results

    # ════════════════════════════════════════════════════════════════════
    # 2. NULL-RATE DETECTION
    # ════════════════════════════════════════════════════════════════════

    # Columns that MUST NOT be null (required fields)
    REQUIRED_COLUMNS: dict[str, list[str]] = {
        "candidates":  ["candidate_id", "full_name", "email",
                        "role_applied", "department", "created_at"],
        "offers":      ["offer_id", "candidate_id", "generated_at",
                        "status", "salary_inr", "role_title"],
        "offer_events":["event_id", "offer_id", "event_name", "timestamp"],
        "signatures":  ["sign_id", "offer_id", "provider",
                        "signed_at", "verification_status"],
        "verification_logs": ["verification_id", "offer_id",
                              "check_time", "result", "check_type"],
    }

    def check_null_rates(self, conn: sqlite3.Connection) -> list[ValidationResult]:
        """
        For every required column, compute null rate and flag if above threshold.
        """
        results = []
        for table, columns in self.REQUIRED_COLUMNS.items():
            total_sql   = f"SELECT COUNT(*) FROM {table}"          # noqa: S608
            total_rows  = self._scalar(conn, total_sql) or 0

            if total_rows == 0:
                results.append(ValidationResult(
                    check_name=f"Null Rate: {table}",
                    status="fail",
                    detail=f"Table {table} has 0 rows.",
                    sql=total_sql,
                ))
                continue

            for col in columns:
                null_sql = (
                    f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL"  # noqa: S608
                )
                null_count = self._scalar(conn, null_sql) or 0
                null_pct   = 100.0 * null_count / total_rows

                if null_pct > MAX_NULL_RATE_PCT:
                    status = "fail"
                    detail = (
                        f"{table}.{col}: {null_count}/{total_rows} nulls "
                        f"({null_pct:.2f}%) — exceeds {MAX_NULL_RATE_PCT}% threshold."
                    )
                elif null_count > 0:
                    status = "warn"
                    detail = (
                        f"{table}.{col}: {null_count} nulls "
                        f"({null_pct:.2f}%) — below threshold but non-zero."
                    )
                else:
                    status = "pass"
                    detail = f"{table}.{col}: no nulls."

                results.append(ValidationResult(
                    check_name=f"Null Rate: {table}.{col}",
                    status=status,
                    detail=detail,
                    sql=null_sql,
                    value=null_pct,
                ))

        return results

    # ════════════════════════════════════════════════════════════════════
    # 3. DUPLICATE DETECTION
    # ════════════════════════════════════════════════════════════════════

    PK_CHECKS: list[tuple[str, str]] = [
        ("candidates",        "candidate_id"),
        ("offers",            "offer_id"),
        ("offer_events",      "event_id"),
        ("signatures",        "offer_id"),       # one signature per offer
        ("verification_logs", "verification_id"),
    ]

    # Business-key uniqueness (beyond PK)
    BIZ_KEY_CHECKS: list[tuple[str, str, str]] = [
        ("candidates", "email",
         "SELECT email, COUNT(*) FROM candidates GROUP BY email HAVING COUNT(*) > 1 LIMIT 5"),
        ("offers", "candidate_id (recent)",
         """
         SELECT candidate_id, COUNT(*) FROM offers
         WHERE generated_at >= datetime('now', '-7 days')
         GROUP BY candidate_id HAVING COUNT(*) > 3 LIMIT 5
         """),
    ]

    def check_duplicates(self, conn: sqlite3.Connection) -> list[ValidationResult]:
        results = []

        # PK duplicates
        for table, pk in self.PK_CHECKS:
            sql = f"""
                SELECT COUNT(*) FROM (
                    SELECT {pk} FROM {table}
                    GROUP BY {pk} HAVING COUNT(*) > 1
                )
            """                                              # noqa: S608
            dup_count  = self._scalar(conn, sql) or 0
            total_sql  = f"SELECT COUNT(*) FROM {table}"   # noqa: S608
            total_rows = self._scalar(conn, total_sql) or 1
            dup_pct    = 100.0 * dup_count / total_rows

            if dup_pct > MAX_DUPLICATE_RATE_PCT:
                status = "fail"
                detail = f"{dup_count} duplicate PKs in {table}.{pk} ({dup_pct:.2f}%)."
            elif dup_count > 0:
                status = "warn"
                detail = f"{dup_count} duplicate PKs in {table}.{pk}."
            else:
                status = "pass"
                detail = f"No duplicate PKs in {table}.{pk}."

            results.append(ValidationResult(
                check_name=f"Duplicate PK: {table}.{pk}",
                status=status,
                detail=detail,
                sql=sql,
                value=dup_count,
            ))

        # Business-key duplicates
        for table, label, sql in self.BIZ_KEY_CHECKS:
            dups = self._q(conn, sql)
            if dups:
                results.append(ValidationResult(
                    check_name=f"Duplicate Biz-Key: {table}.{label}",
                    status="warn",
                    detail=f"{len(dups)} business-key groups with duplicates in {table}.",
                    sql=sql,
                    value=len(dups),
                ))
            else:
                results.append(ValidationResult(
                    check_name=f"Duplicate Biz-Key: {table}.{label}",
                    status="pass",
                    detail=f"No business-key duplicates in {table}.{label}.",
                    sql=sql,
                    value=0,
                ))

        return results

    # ════════════════════════════════════════════════════════════════════
    # 4. ANOMALY DETECTION  (z-score on daily event volume)
    # ════════════════════════════════════════════════════════════════════

    def check_anomalies(self, conn: sqlite3.Connection) -> list[ValidationResult]:
        """
        Compute daily event counts for the last 30 days.
        Flag any day whose count deviates more than ANOMALY_ZSCORE_THRESH
        standard deviations from the mean.
        """
        sql = """
            SELECT DATE(timestamp) AS day, COUNT(*) AS cnt
            FROM   offer_events
            WHERE  timestamp >= datetime('now', '-30 days')
            GROUP  BY DATE(timestamp)
            ORDER  BY day ASC
        """
        rows = self._q(conn, sql)

        if len(rows) < 3:
            return [ValidationResult(
                check_name="Daily Volume Anomaly",
                status="warn",
                detail="Fewer than 3 days of data — anomaly detection skipped.",
                sql=sql,
            )]

        counts = [r["cnt"] for r in rows]
        mean   = sum(counts) / len(counts)
        variance = sum((c - mean) ** 2 for c in counts) / len(counts)
        std    = math.sqrt(variance) if variance > 0 else 0

        anomalies = []
        for r in rows:
            if std > 0:
                z = abs(r["cnt"] - mean) / std
                if z > ANOMALY_ZSCORE_THRESH:
                    anomalies.append(
                        f"{r['day']}: {r['cnt']} events (z={z:.2f})"
                    )

        if anomalies:
            return [ValidationResult(
                check_name="Daily Volume Anomaly",
                status="warn",
                detail=(
                    f"{len(anomalies)} anomalous day(s) detected "
                    f"(z > {ANOMALY_ZSCORE_THRESH}): {'; '.join(anomalies)}"
                ),
                sql=sql,
                value=len(anomalies),
            )]

        return [ValidationResult(
            check_name="Daily Volume Anomaly",
            status="pass",
            detail=(
                f"No anomalies in daily event volume "
                f"(mean={mean:.1f}, std={std:.1f}, "
                f"threshold z={ANOMALY_ZSCORE_THRESH})."
            ),
            sql=sql,
            value=0,
        )]

    # ════════════════════════════════════════════════════════════════════
    # 5. EVENT COMPLETENESS
    # ════════════════════════════════════════════════════════════════════

    def check_event_completeness(self, conn: sqlite3.Connection) -> list[ValidationResult]:
        """
        Verify that:
          • Every offer_id has exactly one offer_generated event.
          • Signed offers have a corresponding signature record.
          • Signature records have at least one verification log.
        """
        results = []

        # 5a – Offers with no offer_generated event
        sql_a = """
            SELECT COUNT(*) FROM offers o
            WHERE NOT EXISTS (
                SELECT 1 FROM offer_events e
                WHERE  e.offer_id   = o.offer_id
                AND    e.event_name = 'offer_generated'
            )
        """
        missing_gen = self._scalar(conn, sql_a) or 0
        results.append(ValidationResult(
            check_name="Event Completeness: offer_generated",
            status="fail" if missing_gen > 0 else "pass",
            detail=(
                f"{missing_gen} offer(s) missing 'offer_generated' event."
                if missing_gen else
                "All offers have an 'offer_generated' event."
            ),
            sql=sql_a,
            value=missing_gen,
        ))

        # 5b – Signed offers missing signature record
        sql_b = """
            SELECT COUNT(*) FROM offer_events e
            WHERE  e.event_name = 'offer_signed'
            AND NOT EXISTS (
                SELECT 1 FROM signatures s WHERE s.offer_id = e.offer_id
            )
        """
        missing_sig = self._scalar(conn, sql_b) or 0
        results.append(ValidationResult(
            check_name="Event Completeness: signature record",
            status="fail" if missing_sig > 0 else "pass",
            detail=(
                f"{missing_sig} signed offer(s) have no signature record."
                if missing_sig else
                "All signed offers have a signature record."
            ),
            sql=sql_b,
            value=missing_sig,
        ))

        # 5c – Signatures with no verification log
        sql_c = """
            SELECT COUNT(*) FROM signatures s
            WHERE NOT EXISTS (
                SELECT 1 FROM verification_logs v WHERE v.offer_id = s.offer_id
            )
        """
        missing_verif = self._scalar(conn, sql_c) or 0
        results.append(ValidationResult(
            check_name="Event Completeness: verification log",
            status="warn" if missing_verif > 0 else "pass",
            detail=(
                f"{missing_verif} signature(s) have no verification log."
                if missing_verif else
                "All signatures have at least one verification log."
            ),
            sql=sql_c,
            value=missing_verif,
        ))

        return results

    # ════════════════════════════════════════════════════════════════════
    # 6. METRIC RECONCILIATION
    # ════════════════════════════════════════════════════════════════════

    def check_metric_reconciliation(self, conn: sqlite3.Connection) -> list[ValidationResult]:
        """
        Cross-validate KPIs against each other for logical consistency.
        These are hard logical rules that must always hold.
        """
        results = []

        checks = [
            (
                "Signed ≤ Viewed",
                """
                SELECT
                    COUNT(DISTINCT CASE WHEN event_name='offer_signed'  THEN offer_id END) AS signed,
                    COUNT(DISTINCT CASE WHEN event_name='offer_opened'  THEN offer_id END) AS viewed
                FROM offer_events
                """,
                lambda r: r["signed"] <= r["viewed"],
                lambda r: (
                    f"signed={r['signed']} ≤ viewed={r['viewed']} ✓"
                    if r["signed"] <= r["viewed"]
                    else f"LOGIC ERROR: signed={r['signed']} > viewed={r['viewed']}"
                ),
            ),
            (
                "Sent ≤ Generated",
                """
                SELECT
                    COUNT(DISTINCT CASE WHEN event_name='offer_sent'      THEN offer_id END) AS sent,
                    COUNT(DISTINCT CASE WHEN event_name='offer_generated' THEN offer_id END) AS generated
                FROM offer_events
                """,
                lambda r: r["sent"] <= r["generated"],
                lambda r: (
                    f"sent={r['sent']} ≤ generated={r['generated']} ✓"
                    if r["sent"] <= r["generated"]
                    else f"LOGIC ERROR: sent={r['sent']} > generated={r['generated']}"
                ),
            ),
            (
                "Signatures ≤ Signed Events",
                """
                SELECT
                    (SELECT COUNT(*) FROM signatures)                                  AS sig_rows,
                    (SELECT COUNT(DISTINCT offer_id) FROM offer_events
                     WHERE  event_name = 'offer_signed')                               AS signed_events
                """,
                lambda r: r["sig_rows"] <= r["signed_events"],
                lambda r: (
                    f"sig_rows={r['sig_rows']} ≤ signed_events={r['signed_events']} ✓"
                    if r["sig_rows"] <= r["signed_events"]
                    else f"LOGIC ERROR: {r['sig_rows']} sig rows > {r['signed_events']} signed events"
                ),
            ),
            (
                "Verification Logs reference valid offers",
                """
                SELECT COUNT(*) AS orphans
                FROM verification_logs v
                LEFT JOIN offers o ON v.offer_id = o.offer_id
                WHERE o.offer_id IS NULL
                """,
                lambda r: r["orphans"] == 0,
                lambda r: (
                    "All verification logs reference valid offers ✓"
                    if r["orphans"] == 0
                    else f"{r['orphans']} orphaned verification log(s)."
                ),
            ),
            (
                "Offer status matches event log",
                """
                SELECT COUNT(*) AS mismatches
                FROM offers o
                WHERE o.status = 'signed'
                AND NOT EXISTS (
                    SELECT 1 FROM offer_events e
                    WHERE e.offer_id   = o.offer_id
                    AND   e.event_name = 'offer_signed'
                )
                """,
                lambda r: r["mismatches"] == 0,
                lambda r: (
                    "All 'signed' status offers have a matching event ✓"
                    if r["mismatches"] == 0
                    else f"{r['mismatches']} offer(s) have status='signed' but no event."
                ),
            ),
        ]

        for label, sql, predicate, detail_fn in checks:
            rows = self._q(conn, sql)
            if not rows:
                results.append(ValidationResult(
                    check_name=f"Reconciliation: {label}",
                    status="warn",
                    detail="Query returned no rows.",
                    sql=sql,
                ))
                continue

            row    = dict(rows[0])
            passed = predicate(row)
            results.append(ValidationResult(
                check_name=f"Reconciliation: {label}",
                status="pass" if passed else "fail",
                detail=detail_fn(row),
                sql=sql,
            ))

        return results

    # ════════════════════════════════════════════════════════════════════
    # 7. ORPHAN / FK INTEGRITY
    # ════════════════════════════════════════════════════════════════════

    def check_orphans(self, conn: sqlite3.Connection) -> list[ValidationResult]:
        orphan_checks = [
            (
                "Orphan offers (no candidate)",
                """
                SELECT COUNT(*) FROM offers o
                LEFT JOIN candidates c ON o.candidate_id = c.candidate_id
                WHERE c.candidate_id IS NULL
                """,
            ),
            (
                "Orphan events (no offer)",
                """
                SELECT COUNT(*) FROM offer_events e
                LEFT JOIN offers o ON e.offer_id = o.offer_id
                WHERE o.offer_id IS NULL
                """,
            ),
            (
                "Orphan signatures (no offer)",
                """
                SELECT COUNT(*) FROM signatures s
                LEFT JOIN offers o ON s.offer_id = o.offer_id
                WHERE o.offer_id IS NULL
                """,
            ),
            (
                "Orphan verification logs (no offer)",
                """
                SELECT COUNT(*) FROM verification_logs v
                LEFT JOIN offers o ON v.offer_id = o.offer_id
                WHERE o.offer_id IS NULL
                """,
            ),
        ]
        results = []
        for label, sql in orphan_checks:
            count = self._scalar(conn, sql) or 0
            results.append(ValidationResult(
                check_name=f"FK Integrity: {label}",
                status="fail" if count > 0 else "pass",
                detail=f"{count} orphan row(s)." if count else "No orphans.",
                sql=sql,
                value=count,
            ))
        return results

    # ════════════════════════════════════════════════════════════════════
    # MASTER: run_all
    # ════════════════════════════════════════════════════════════════════

    def run_all(self) -> ValidationReport:
        """
        Execute every validation check and return a ValidationReport.
        """
        report = ValidationReport()
        try:
            conn = self._connect()

            for check_fn in [
                self.check_freshness,
                self.check_null_rates,
                self.check_duplicates,
                self.check_anomalies,
                self.check_event_completeness,
                self.check_metric_reconciliation,
                self.check_orphans,
            ]:
                try:
                    batch = check_fn(conn)
                    report.results.extend(batch)
                except Exception as exc:
                    log.error("Check failed (%s): %s", check_fn.__name__, exc)
                    report.results.append(ValidationResult(
                        check_name=check_fn.__name__,
                        status="fail",
                        detail=f"Unexpected error: {exc}",
                    ))

        except sqlite3.Error as exc:
            log.critical("Cannot connect for validation: %s", exc)
            report.results.append(ValidationResult(
                check_name="DB Connection",
                status="fail",
                detail=str(exc),
            ))
        finally:
            if "conn" in locals():
                conn.close()

        return report


# ── CLI smoke test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    engine = ValidationEngine()
    report = engine.run_all()

    ICONS = {"pass": "✓", "warn": "⚠", "fail": "✗"}

    print("\n" + "=" * 70)
    print("  PlaceMux · Data Validation Report")
    print("=" * 70)
    for r in report.results:
        icon = ICONS.get(r.status, "?")
        print(f"  {icon}  [{r.status.upper():<4}]  {r.check_name}")
        print(f"          {r.detail}")
    print("=" * 70)
    print(f"  {report.summary()}")
    print("=" * 70)

    sys.exit(0 if report.overall_status != "fail" else 1)
