"""
generate_data.py
================
PlaceMux · Task 11 · Offer Generation & E-Sign Design
------------------------------------------------------
Generates realistic synthetic data for the full offer funnel using Faker.
All probabilities are driven by config.py — nothing is hardcoded here.

Execution order: 2 of 11
Run:  python generate_data.py

Output
------
  data/candidates.csv
  data/offers.csv
  data/offer_events.csv
  data/signatures.csv
  data/verification_logs.csv

Funnel logic
------------
  offer_generated  →  [PROB_SENT]     → offer_sent
  offer_sent       →  [PROB_OPENED]   → offer_opened
  offer_opened     →  [PROB_SIGNED]   → offer_signed
                   →  [PROB_REJECTED] → offer_rejected
  offer_signed     →  signature record
  signature        →  verification_log (+ possible re-checks on fail)
"""

import csv
import hashlib
import json
import logging
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from faker import Faker

from config import (
    DATA_DIR,
    DATA_WINDOW_DAYS,
    DEPARTMENTS,
    ESIGN_PROVIDERS,
    NUM_CANDIDATES,
    NUM_OFFERS,
    OFFER_VALIDITY_DAYS,
    PROB_OPENED,
    PROB_REJECTED,
    PROB_SENT,
    PROB_SIGNED,
    PROB_VERIFICATION_PASS,
    ROLES,
    SOURCE_CHANNELS,
)

# ── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

fake = Faker("en_IN")
random.seed(42)
Faker.seed(42)

# ── Helpers ──────────────────────────────────────────────────────────────────

def new_id() -> str:
    """Short UUID4 string."""
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Return ISO-8601 UTC string (no microseconds)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def random_past_dt(max_days_ago: int, min_days_ago: int = 0) -> datetime:
    """Random UTC datetime within [min_days_ago, max_days_ago] in the past."""
    delta = random.randint(min_days_ago * 86400, max_days_ago * 86400)
    return utc_now() - timedelta(seconds=delta)


def add_minutes(dt: datetime, lo: int, hi: int) -> datetime:
    return dt + timedelta(minutes=random.randint(lo, hi))


def sha256_stub(text: str) -> str:
    """Deterministic SHA-256 hex digest (simulates document hash)."""
    return hashlib.sha256(text.encode()).hexdigest()


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log.info("  ✓  Wrote %d rows → %s", len(rows), path.name)


# ── Generator functions ──────────────────────────────────────────────────────

def generate_candidates(n: int) -> list[dict]:
    """
    Build `n` candidate records.
    Ensures email uniqueness (Faker can occasionally collide).
    """
    log.info("Generating %d candidates …", n)
    seen_emails: set[str] = set()
    rows = []

    while len(rows) < n:
        email = fake.email()
        if email in seen_emails:
            continue
        seen_emails.add(email)

        created = random_past_dt(DATA_WINDOW_DAYS + 30)   # candidates predate offers
        rows.append({
            "candidate_id":   new_id(),
            "full_name":      fake.name(),
            "email":          email,
            "phone":          fake.phone_number()[:15],
            "role_applied":   random.choice(ROLES),
            "department":     random.choice(DEPARTMENTS),
            "created_at":     iso(created),
            "source_channel": random.choice(SOURCE_CHANNELS),
        })

    return rows


def generate_offers_and_events(
    candidates: list[dict],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """
    For each offer, simulate the full funnel and produce:
      - offer rows
      - offer_event rows
      - signature rows
      - verification_log rows
    """
    log.info("Generating %d offers with full funnel …", NUM_OFFERS)

    offers:            list[dict] = []
    offer_events:      list[dict] = []
    signatures:        list[dict] = []
    verification_logs: list[dict] = []

    candidate_ids = [c["candidate_id"] for c in candidates]

    for _ in range(NUM_OFFERS):
        offer_id    = new_id()
        candidate_id = random.choice(candidate_ids)

        # ── Step 1: offer_generated ─────────────────────────────────────
        generated_at = random_past_dt(DATA_WINDOW_DAYS, min_days_ago=1)
        expiry_at    = generated_at + timedelta(days=OFFER_VALIDITY_DAYS)
        status       = "generated"

        offer_events.append({
            "event_id":   new_id(),
            "offer_id":   offer_id,
            "event_name": "offer_generated",
            "timestamp":  iso(generated_at),
            "actor":      "system",
            "metadata":   json.dumps({"trigger": "hr_ops_approval"}),
        })

        sent_at = None

        # ── Step 2: offer_sent ──────────────────────────────────────────
        if random.random() < PROB_SENT:
            sent_at  = add_minutes(generated_at, 5, 120)
            status   = "sent"

            offer_events.append({
                "event_id":   new_id(),
                "offer_id":   offer_id,
                "event_name": "offer_sent",
                "timestamp":  iso(sent_at),
                "actor":      "system",
                "metadata":   json.dumps({"channel": "email", "provider": "sendgrid"}),
            })

            # ── Step 3: offer_opened ────────────────────────────────────
            if random.random() < PROB_OPENED:
                opened_at = add_minutes(sent_at, 10, 1440)   # up to 24 h later
                status    = "viewed"

                offer_events.append({
                    "event_id":   new_id(),
                    "offer_id":   offer_id,
                    "event_name": "offer_opened",
                    "timestamp":  iso(opened_at),
                    "actor":      "candidate",
                    "metadata":   json.dumps({
                        "device": random.choice(["mobile", "desktop", "tablet"]),
                        "ip_hash": sha256_stub(offer_id + "ip")[:16],
                    }),
                })

                # ── Step 4a: offer_signed ───────────────────────────────
                if random.random() < PROB_SIGNED:
                    signed_at = add_minutes(opened_at, 5, 480)
                    status    = "signed"

                    offer_events.append({
                        "event_id":   new_id(),
                        "offer_id":   offer_id,
                        "event_name": "offer_signed",
                        "timestamp":  iso(signed_at),
                        "actor":      "candidate",
                        "metadata":   json.dumps({"method": "aadhaar_otp"}),
                    })

                    # ── Signature record ────────────────────────────────
                    provider   = random.choice(ESIGN_PROVIDERS)
                    v_status   = (
                        "verified" if random.random() < PROB_VERIFICATION_PASS
                        else "failed"
                    )
                    sign_id = new_id()

                    signatures.append({
                        "sign_id":             sign_id,
                        "offer_id":            offer_id,
                        "provider":            provider,
                        "signed_at":           iso(signed_at),
                        "verification_status": v_status,
                        "signer_ip_hash":      sha256_stub(offer_id + "signer")[:16],
                        "document_hash":       sha256_stub(offer_id + "doc"),
                    })

                    # ── Verification log ────────────────────────────────
                    check_time = add_minutes(signed_at, 1, 30)
                    verification_logs.append({
                        "verification_id": new_id(),
                        "offer_id":        offer_id,
                        "check_time":      iso(check_time),
                        "result":          "pass" if v_status == "verified" else "fail",
                        "check_type":      "provider_webhook",
                        "error_message":   (
                            None if v_status == "verified"
                            else random.choice([
                                "OTP mismatch",
                                "Aadhaar validation timeout",
                                "Document hash mismatch",
                            ])
                        ),
                    })

                    # Some failed verifications get a manual re-check
                    if v_status == "failed" and random.random() < 0.6:
                        recheck_time = add_minutes(check_time, 60, 360)
                        recheck_result = (
                            "pass" if random.random() < 0.7 else "fail"
                        )
                        verification_logs.append({
                            "verification_id": new_id(),
                            "offer_id":        offer_id,
                            "check_time":      iso(recheck_time),
                            "result":          recheck_result,
                            "check_type":      "manual",
                            "error_message":   (
                                None if recheck_result == "pass"
                                else "Manual review inconclusive"
                            ),
                        })

                # ── Step 4b: offer_rejected ─────────────────────────────
                elif random.random() < PROB_REJECTED:
                    rejected_at = add_minutes(opened_at, 30, 2880)
                    status      = "rejected"

                    offer_events.append({
                        "event_id":   new_id(),
                        "offer_id":   offer_id,
                        "event_name": "offer_rejected",
                        "timestamp":  iso(rejected_at),
                        "actor":      "candidate",
                        "metadata":   json.dumps({
                            "reason": random.choice([
                                "compensation_low",
                                "competing_offer",
                                "role_mismatch",
                                "relocation_concern",
                                "no_reason_given",
                            ])
                        }),
                    })

        # ── Offer row ───────────────────────────────────────────────────
        offers.append({
            "offer_id":     offer_id,
            "candidate_id": candidate_id,
            "generated_at": iso(generated_at),
            "sent_at":      iso(sent_at) if sent_at else None,
            "status":       status,
            "salary_inr":   random.randint(400_000, 4_000_000),
            "role_title":   random.choice(ROLES),
            "expiry_at":    iso(expiry_at),
        })

    return offers, offer_events, signatures, verification_logs


# ── CSV writers ──────────────────────────────────────────────────────────────

CANDIDATE_FIELDS = [
    "candidate_id", "full_name", "email", "phone",
    "role_applied", "department", "created_at", "source_channel",
]

OFFER_FIELDS = [
    "offer_id", "candidate_id", "generated_at", "sent_at",
    "status", "salary_inr", "role_title", "expiry_at",
]

EVENT_FIELDS = [
    "event_id", "offer_id", "event_name", "timestamp", "actor", "metadata",
]

SIGNATURE_FIELDS = [
    "sign_id", "offer_id", "provider", "signed_at",
    "verification_status", "signer_ip_hash", "document_hash",
]

VERIFICATION_FIELDS = [
    "verification_id", "offer_id", "check_time",
    "result", "check_type", "error_message",
]


# ── Entry point ──────────────────────────────────────────────────────────────

def generate_all() -> None:
    """
    Full generation pipeline.
    Writes five CSVs to data/ and prints a summary.
    """
    log.info("=== PlaceMux · Data Generation (Task 11) ===")

    candidates = generate_candidates(NUM_CANDIDATES)
    offers, events, signatures, verifications = generate_offers_and_events(candidates)

    # ── Write CSVs ───────────────────────────────────────────────────────
    write_csv(DATA_DIR / "candidates.csv",        candidates,   CANDIDATE_FIELDS)
    write_csv(DATA_DIR / "offers.csv",            offers,       OFFER_FIELDS)
    write_csv(DATA_DIR / "offer_events.csv",      events,       EVENT_FIELDS)
    write_csv(DATA_DIR / "signatures.csv",        signatures,   SIGNATURE_FIELDS)
    write_csv(DATA_DIR / "verification_logs.csv", verifications, VERIFICATION_FIELDS)

    # ── Funnel summary ───────────────────────────────────────────────────
    total       = len(offers)
    n_sent      = sum(1 for o in offers if o["status"] in ("sent","viewed","signed","rejected"))
    n_viewed    = sum(1 for o in offers if o["status"] in ("viewed","signed","rejected"))
    n_signed    = sum(1 for o in offers if o["status"] == "signed")
    n_rejected  = sum(1 for o in offers if o["status"] == "rejected")
    n_verified  = sum(1 for s in signatures if s["verification_status"] == "verified")

    log.info("── Funnel Summary ──────────────────────────────")
    log.info("  Candidates    : %d", len(candidates))
    log.info("  Offers total  : %d", total)
    log.info("  Sent          : %d  (%.1f%%)", n_sent,     100 * n_sent     / total)
    log.info("  Viewed        : %d  (%.1f%%)", n_viewed,   100 * n_viewed   / total)
    log.info("  Signed        : %d  (%.1f%%)", n_signed,   100 * n_signed   / total)
    log.info("  Rejected      : %d  (%.1f%%)", n_rejected, 100 * n_rejected / total)
    log.info("  Signatures    : %d", len(signatures))
    log.info("  Verified      : %d  (%.1f%%)",
             n_verified, 100 * n_verified / max(len(signatures), 1))
    log.info("  Verif. logs   : %d", len(verifications))
    log.info("  Events total  : %d", len(events))
    log.info("────────────────────────────────────────────────")
    log.info("Data generation complete.")


if __name__ == "__main__":
    try:
        generate_all()
    except Exception as exc:
        log.critical("Generation failed: %s", exc, exc_info=True)
        sys.exit(1)
