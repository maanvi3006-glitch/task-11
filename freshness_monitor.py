"""
freshness_monitor.py
====================
PlaceMux · Task 11 · Standalone freshness checker.
Can be run as a cron job or called from the dashboard.

Run:  python freshness_monitor.py
"""

import logging
import sqlite3
import sys

from config import DB_PATH, FRESHNESS_CRIT_HOURS, FRESHNESS_WARN_HOURS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

CHECKS = [
    (
        "offer_events",
        "SELECT ROUND((JULIANDAY('now') - JULIANDAY(MAX(timestamp))) * 24, 2) FROM offer_events",
    ),
    (
        "signatures",
        "SELECT ROUND((JULIANDAY('now') - JULIANDAY(MAX(signed_at))) * 24, 2) FROM signatures",
    ),
    (
        "verification_logs",
        "SELECT ROUND((JULIANDAY('now') - JULIANDAY(MAX(check_time))) * 24, 2) FROM verification_logs",
    ),
]


def run_freshness_checks(db_path: str = DB_PATH) -> bool:
    """Returns True if all checks pass, False if any warn/fail."""
    log.info("=== Freshness Monitor ===")
    all_ok = True
    try:
        conn = sqlite3.connect(db_path)
        for table, sql in CHECKS:
            hours = conn.execute(sql).fetchone()[0]
            if hours is None:
                log.warning("  %-22s  NO DATA", table)
                all_ok = False
            elif hours > FRESHNESS_CRIT_HOURS:
                log.error("  %-22s  %.1f hrs  [CRITICAL]", table, hours)
                all_ok = False
            elif hours > FRESHNESS_WARN_HOURS:
                log.warning("  %-22s  %.1f hrs  [WARN]", table, hours)
                all_ok = False
            else:
                log.info("  %-22s  %.1f hrs  [OK]", table, hours)
        conn.close()
    except sqlite3.Error as exc:
        log.critical("DB error: %s", exc)
        return False
    return all_ok


if __name__ == "__main__":
    ok = run_freshness_checks()
    sys.exit(0 if ok else 1)
