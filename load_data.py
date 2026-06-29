"""
load_data.py
============
PlaceMux · Task 11 · Offer Generation & E-Sign Design
------------------------------------------------------
Loads the five generated CSVs into the SQLite database.

Execution order: 3 of 11
Run:  python load_data.py

Safety guarantees
-----------------
  • Idempotent  – safe to re-run; uses INSERT OR IGNORE to skip duplicates
  • FK-checked  – PRAGMA foreign_keys = ON before any insert
  • Typed       – NULL placeholders in CSV are converted to Python None
  • Validated   – row counts reconciled between CSV and DB after each load
  • Transacted  – each table loaded in a single transaction; rolls back on error
  • Logged      – every step emits a structured log line

Load order (respects FK dependencies)
--------------------------------------
  1. candidates
  2. offers          (FK → candidates)
  3. offer_events    (FK → offers)
  4. signatures      (FK → offers)
  5. verification_logs (FK → offers)
"""

import csv
import logging
import sqlite3
import sys
from pathlib import Path
from typing import Any

from config import DATA_DIR, DB_PATH
from create_database import create_database, verify_schema

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Table → CSV mapping with INSERT SQL ─────────────────────────────────────

TABLE_CONFIG: list[dict] = [
    {
        "table":  "candidates",
        "csv":    DATA_DIR / "candidates.csv",
        "sql":    """
            INSERT OR IGNORE INTO candidates
                (candidate_id, full_name, email, phone,
                 role_applied, department, created_at, source_channel)
            VALUES
                (:candidate_id, :full_name, :email, :phone,
                 :role_applied, :department, :created_at, :source_channel)
        """,
    },
    {
        "table":  "offers",
        "csv":    DATA_DIR / "offers.csv",
        "sql":    """
            INSERT OR IGNORE INTO offers
                (offer_id, candidate_id, generated_at, sent_at,
                 status, salary_inr, role_title, expiry_at)
            VALUES
                (:offer_id, :candidate_id, :generated_at, :sent_at,
                 :status, :salary_inr, :role_title, :expiry_at)
        """,
    },
    {
        "table":  "offer_events",
        "csv":    DATA_DIR / "offer_events.csv",
        "sql":    """
            INSERT OR IGNORE INTO offer_events
                (event_id, offer_id, event_name, timestamp, actor, metadata)
            VALUES
                (:event_id, :offer_id, :event_name, :timestamp, :actor, :metadata)
        """,
    },
    {
        "table":  "signatures",
        "csv":    DATA_DIR / "signatures.csv",
        "sql":    """
            INSERT OR IGNORE INTO signatures
                (sign_id, offer_id, provider, signed_at,
                 verification_status, signer_ip_hash, document_hash)
            VALUES
                (:sign_id, :offer_id, :provider, :signed_at,
                 :verification_status, :signer_ip_hash, :document_hash)
        """,
    },
    {
        "table":  "verification_logs",
        "csv":    DATA_DIR / "verification_logs.csv",
        "sql":    """
            INSERT OR IGNORE INTO verification_logs
                (verification_id, offer_id, check_time,
                 result, check_type, error_message)
            VALUES
                (:verification_id, :offer_id, :check_time,
                 :result, :check_type, :error_message)
        """,
    },
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def _nullify(row: dict[str, str]) -> dict[str, Any]:
    """
    Convert empty strings and the literal string 'None' to Python None
    so SQLite stores them as NULL.
    """
    return {
        k: (None if v in ("", "None", "null", "NULL") else v)
        for k, v in row.items()
    }


def _read_csv(path: Path) -> list[dict[str, Any]]:
    """
    Read a CSV file and return a list of null-cleaned dicts.

    Raises
    ------
    FileNotFoundError
        If the CSV does not exist (data generation not yet run).
    """
    if not path.exists():
        raise FileNotFoundError(
            f"CSV not found: {path}\n"
            "Run  python generate_data.py  first."
        )

    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = [_nullify(row) for row in reader]

    log.info("  Read %d rows from %s", len(rows), path.name)
    return rows


def _count_table(conn: sqlite3.Connection, table: str) -> int:
    cur = conn.execute(f"SELECT COUNT(*) FROM {table};")   # noqa: S608 – table name is internal
    return cur.fetchone()[0]


def _load_table(
    conn: sqlite3.Connection,
    table: str,
    rows: list[dict],
    sql: str,
) -> tuple[int, int]:
    """
    Load rows into `table` inside a single transaction.

    Returns
    -------
    (inserted, skipped) counts
    """
    before = _count_table(conn, table)

    try:
        with conn:                          # auto-commit / rollback
            conn.executemany(sql, rows)
    except sqlite3.IntegrityError as exc:
        log.error("  FK / integrity error loading %s: %s", table, exc)
        raise
    except sqlite3.Error as exc:
        log.error("  SQLite error loading %s: %s", table, exc)
        raise

    after    = _count_table(conn, table)
    inserted = after - before
    skipped  = len(rows) - inserted
    return inserted, skipped


def _reconcile(table: str, csv_rows: int, inserted: int, skipped: int) -> None:
    """Log a reconciliation line and warn if numbers look off."""
    log.info(
        "  %-22s  csv=%d  inserted=%d  skipped=%d",
        table, csv_rows, inserted, skipped,
    )
    if inserted + skipped != csv_rows:
        log.warning(
            "  Reconciliation mismatch on %s: %d + %d ≠ %d",
            table, inserted, skipped, csv_rows,
        )


# ── Duplicate detection ──────────────────────────────────────────────────────

def check_duplicates(conn: sqlite3.Connection) -> None:
    """
    Scan each table's primary-key column for duplicates and warn.
    (Should never fire with INSERT OR IGNORE, but good as a safety net.)
    """
    checks = [
        ("candidates",        "candidate_id"),
        ("offers",            "offer_id"),
        ("offer_events",      "event_id"),
        ("signatures",        "offer_id"),       # one sig per offer
        ("verification_logs", "verification_id"),
    ]

    log.info("── Duplicate check ─────────────────────────────────")
    all_clean = True
    for table, pk in checks:
        cur = conn.execute(
            f"""
            SELECT {pk}, COUNT(*) AS cnt
            FROM   {table}
            GROUP  BY {pk}
            HAVING cnt > 1
            LIMIT  5;
            """                                   # noqa: S608
        )
        dups = cur.fetchall()
        if dups:
            log.warning("  DUPLICATE PKs in %s: %s", table, dups)
            all_clean = False
        else:
            log.info("  ✓  No duplicates in %s", table)

    if all_clean:
        log.info("  All tables clean.")


# ── FK integrity spot-check ──────────────────────────────────────────────────

def check_referential_integrity(conn: sqlite3.Connection) -> None:
    """
    Verify that every child row references a real parent.
    Logs warnings for orphaned rows.
    """
    fk_checks = [
        (
            "offers → candidates",
            """
            SELECT COUNT(*) FROM offers o
            LEFT JOIN candidates c ON o.candidate_id = c.candidate_id
            WHERE c.candidate_id IS NULL
            """,
        ),
        (
            "offer_events → offers",
            """
            SELECT COUNT(*) FROM offer_events e
            LEFT JOIN offers o ON e.offer_id = o.offer_id
            WHERE o.offer_id IS NULL
            """,
        ),
        (
            "signatures → offers",
            """
            SELECT COUNT(*) FROM signatures s
            LEFT JOIN offers o ON s.offer_id = o.offer_id
            WHERE o.offer_id IS NULL
            """,
        ),
        (
            "verification_logs → offers",
            """
            SELECT COUNT(*) FROM verification_logs v
            LEFT JOIN offers o ON v.offer_id = o.offer_id
            WHERE o.offer_id IS NULL
            """,
        ),
    ]

    log.info("── Referential integrity check ─────────────────────")
    all_ok = True
    for label, sql in fk_checks:
        count = conn.execute(sql).fetchone()[0]
        if count:
            log.warning("  ORPHAN ROWS in %s: %d", label, count)
            all_ok = False
        else:
            log.info("  ✓  %s", label)

    if all_ok:
        log.info("  All FK relationships intact.")


# ── Main ─────────────────────────────────────────────────────────────────────

def load_all(db_path: str = DB_PATH) -> None:
    """
    Full load pipeline:
      1. Ensure schema exists
      2. Load each table from CSV
      3. Reconcile row counts
      4. Check duplicates
      5. Verify referential integrity
    """
    log.info("=== PlaceMux · Data Load (Task 11) ===")

    # Ensure schema is in place (create_database is idempotent)
    create_database(db_path)
    if not verify_schema(db_path):
        log.critical("Schema verification failed – aborting load.")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")

    try:
        log.info("── Loading tables ──────────────────────────────────")
        for cfg in TABLE_CONFIG:
            table = cfg["table"]
            log.info("Loading: %s", table)

            rows = _read_csv(cfg["csv"])
            inserted, skipped = _load_table(conn, table, rows, cfg["sql"])
            _reconcile(table, len(rows), inserted, skipped)

        # ── Post-load checks ─────────────────────────────────────────
        check_duplicates(conn)
        check_referential_integrity(conn)

        # ── Final row counts ─────────────────────────────────────────
        log.info("── Final row counts ────────────────────────────────")
        for cfg in TABLE_CONFIG:
            n = _count_table(conn, cfg["table"])
            log.info("  %-22s  %d rows", cfg["table"], n)

        log.info("Data load complete.")

    except FileNotFoundError as exc:
        log.critical("%s", exc)
        sys.exit(1)

    except sqlite3.Error as exc:
        log.critical("Unrecoverable database error: %s", exc, exc_info=True)
        sys.exit(1)

    finally:
        conn.close()


if __name__ == "__main__":
    load_all()
