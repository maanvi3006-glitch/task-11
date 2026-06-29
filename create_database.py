"""
create_database.py
==================
PlaceMux · Task 11 · Offer Generation & E-Sign Design
------------------------------------------------------
Initialises the SQLite database with the full schema for the
Offer Funnel analytics system.

Execution order: 1 of 11
Run:  python create_database.py

Tables created
--------------
  candidates         – people who receive offers
  offers             – one row per offer document
  offer_events       – immutable event log (offer lifecycle)
  signatures         – e-sign records
  verification_logs  – tamper-check audit trail
"""

import sqlite3
import logging
import sys
from pathlib import Path

from config import DB_PATH

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── DDL statements ──────────────────────────────────────────────────────────

DDL_CANDIDATES = """
CREATE TABLE IF NOT EXISTS candidates (
    candidate_id    TEXT PRIMARY KEY,
    full_name       TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    phone           TEXT,
    role_applied    TEXT NOT NULL,
    department      TEXT NOT NULL,
    created_at      TEXT NOT NULL,          -- ISO-8601 UTC
    source_channel  TEXT NOT NULL           -- e.g. linkedin, referral, portal
);
"""

DDL_OFFERS = """
CREATE TABLE IF NOT EXISTS offers (
    offer_id        TEXT PRIMARY KEY,
    candidate_id    TEXT NOT NULL,
    generated_at    TEXT NOT NULL,          -- ISO-8601 UTC
    sent_at         TEXT,                   -- NULL until sent
    status          TEXT NOT NULL           -- generated | sent | viewed | signed | rejected
        CHECK (status IN ('generated','sent','viewed','signed','rejected')),
    salary_inr      INTEGER NOT NULL,
    role_title      TEXT NOT NULL,
    expiry_at       TEXT NOT NULL,          -- offer validity deadline
    FOREIGN KEY (candidate_id) REFERENCES candidates (candidate_id)
);
"""

DDL_OFFER_EVENTS = """
CREATE TABLE IF NOT EXISTS offer_events (
    event_id        TEXT PRIMARY KEY,
    offer_id        TEXT NOT NULL,
    event_name      TEXT NOT NULL
        CHECK (event_name IN (
            'offer_generated',
            'offer_sent',
            'offer_opened',
            'offer_signed',
            'offer_rejected'
        )),
    timestamp       TEXT NOT NULL,          -- ISO-8601 UTC
    actor           TEXT,                   -- system | candidate | hr_ops
    metadata        TEXT,                   -- JSON blob (device, IP hash, etc.)
    FOREIGN KEY (offer_id) REFERENCES offers (offer_id)
);
"""

DDL_SIGNATURES = """
CREATE TABLE IF NOT EXISTS signatures (
    sign_id             TEXT PRIMARY KEY,
    offer_id            TEXT NOT NULL UNIQUE,   -- one signature per offer
    provider            TEXT NOT NULL,           -- e.g. docusign, leegality, digio
    signed_at           TEXT NOT NULL,           -- ISO-8601 UTC
    verification_status TEXT NOT NULL
        CHECK (verification_status IN ('pending','verified','failed')),
    signer_ip_hash      TEXT,
    document_hash       TEXT,                    -- SHA-256 of signed PDF
    FOREIGN KEY (offer_id) REFERENCES offers (offer_id)
);
"""

DDL_VERIFICATION_LOGS = """
CREATE TABLE IF NOT EXISTS verification_logs (
    verification_id TEXT PRIMARY KEY,
    offer_id        TEXT NOT NULL,
    check_time      TEXT NOT NULL,          -- ISO-8601 UTC
    result          TEXT NOT NULL
        CHECK (result IN ('pass','fail','pending')),
    check_type      TEXT NOT NULL,          -- hash_check | provider_webhook | manual
    error_message   TEXT,                   -- NULL on pass
    FOREIGN KEY (offer_id) REFERENCES offers (offer_id)
);
"""

# Performance indexes – queried heavily by the metrics engine
DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_offers_candidate   ON offers (candidate_id);",
    "CREATE INDEX IF NOT EXISTS idx_offers_status       ON offers (status);",
    "CREATE INDEX IF NOT EXISTS idx_offers_generated    ON offers (generated_at);",
    "CREATE INDEX IF NOT EXISTS idx_events_offer        ON offer_events (offer_id);",
    "CREATE INDEX IF NOT EXISTS idx_events_name         ON offer_events (event_name);",
    "CREATE INDEX IF NOT EXISTS idx_events_ts           ON offer_events (timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_signatures_offer    ON signatures (offer_id);",
    "CREATE INDEX IF NOT EXISTS idx_verif_offer         ON verification_logs (offer_id);",
    "CREATE INDEX IF NOT EXISTS idx_verif_time          ON verification_logs (check_time);",
]


# ── Schema version tracking ─────────────────────────────────────────────────

DDL_SCHEMA_VERSION = """
CREATE TABLE IF NOT EXISTS _schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    description TEXT
);
"""

SCHEMA_VERSION = 1


# ── Main ────────────────────────────────────────────────────────────────────

def create_database(db_path: str = DB_PATH) -> None:
    """
    Creates (or verifies) the PlaceMux Offer SQLite database.

    Parameters
    ----------
    db_path : str
        File-system path to the SQLite file.  Taken from config.py by default.

    Raises
    ------
    SystemExit
        On any unrecoverable database error.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Connecting to database: %s", path.resolve())

    try:
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA journal_mode = WAL;")   # better concurrency
        conn.execute("PRAGMA foreign_keys = ON;")
        cur = conn.cursor()

        # ── Create tables ────────────────────────────────────────────────
        for name, ddl in [
            ("candidates",        DDL_CANDIDATES),
            ("offers",            DDL_OFFERS),
            ("offer_events",      DDL_OFFER_EVENTS),
            ("signatures",        DDL_SIGNATURES),
            ("verification_logs", DDL_VERIFICATION_LOGS),
            ("_schema_version",   DDL_SCHEMA_VERSION),
        ]:
            cur.execute(ddl)
            log.info("  ✓  Table ready: %s", name)

        # ── Create indexes ───────────────────────────────────────────────
        for idx_sql in DDL_INDEXES:
            cur.execute(idx_sql)

        log.info("  ✓  %d indexes applied.", len(DDL_INDEXES))

        # ── Record schema version (idempotent) ───────────────────────────
        cur.execute(
            """
            INSERT OR IGNORE INTO _schema_version (version, applied_at, description)
            VALUES (?, datetime('now'), 'Initial PlaceMux Offer schema – Task 11')
            """,
            (SCHEMA_VERSION,),
        )

        conn.commit()
        log.info("Database initialised successfully (schema v%d).", SCHEMA_VERSION)

    except sqlite3.Error as exc:
        log.critical("Database creation failed: %s", exc)
        sys.exit(1)

    finally:
        if "conn" in locals():
            conn.close()


def verify_schema(db_path: str = DB_PATH) -> bool:
    """
    Quick check that all expected tables exist.

    Returns
    -------
    bool
        True if all tables are present, False otherwise.
    """
    required_tables = {
        "candidates", "offers", "offer_events",
        "signatures", "verification_logs",
    }
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
        existing = {row[0] for row in cur.fetchall()}
        conn.close()

        missing = required_tables - existing
        if missing:
            log.warning("Missing tables: %s", missing)
            return False

        log.info("Schema verification passed – all tables present.")
        return True

    except sqlite3.Error as exc:
        log.error("Schema verification error: %s", exc)
        return False


if __name__ == "__main__":
    create_database()
    ok = verify_schema()
    sys.exit(0 if ok else 1)
