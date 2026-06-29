"""
config.py
=========
PlaceMux · Task 11 · Central configuration
-------------------------------------------
All tunable constants live here.
No other module should hardcode paths, thresholds, or names.
"""

from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).resolve().parent
DB_PATH     = str(BASE_DIR / "placemux_offer.db")
DATA_DIR    = BASE_DIR / "data"
EXPORTS_DIR = BASE_DIR / "exports"

# Ensure directories exist at import time
DATA_DIR.mkdir(exist_ok=True)
EXPORTS_DIR.mkdir(exist_ok=True)

# ── Data generation ─────────────────────────────────────────────────────────
NUM_CANDIDATES  = 600        # realistic company-scale headcount
NUM_OFFERS      = 500        # offers issued (some candidates get >1)

# Funnel drop-off probabilities (realistic hiring funnel)
PROB_SENT       = 0.92       # 92 % of generated offers are sent
PROB_OPENED     = 0.85       # 85 % of sent offers are opened
PROB_SIGNED     = 0.68       # 68 % of opened offers are signed
PROB_REJECTED   = 0.18       # 18 % of opened offers are rejected (rest expire)

# E-sign
ESIGN_PROVIDERS         = ["leegality", "digio", "docusign"]
PROB_VERIFICATION_PASS  = 0.94   # 94 % of signatures verify successfully

# Offer validity window (days from generation)
OFFER_VALIDITY_DAYS = 7

# Data date range (offers generated within this many days from today)
DATA_WINDOW_DAYS = 90

# ── Freshness thresholds ────────────────────────────────────────────────────
FRESHNESS_WARN_HOURS  = 24   # warn if no new event in 24 h
FRESHNESS_CRIT_HOURS  = 48   # critical if no new event in 48 h

# ── Data quality thresholds ─────────────────────────────────────────────────
MAX_NULL_RATE_PCT      = 5.0   # alert if any column null-rate exceeds 5 %
MAX_DUPLICATE_RATE_PCT = 1.0   # alert if duplicate rate exceeds 1 %
ANOMALY_ZSCORE_THRESH  = 3.0   # z-score threshold for daily volume anomaly

# ── Export ──────────────────────────────────────────────────────────────────
EXPORT_FILENAME = "offer_metrics_export.csv"

# ── Dashboard ───────────────────────────────────────────────────────────────
DASHBOARD_TITLE    = "PlaceMux · Offer Funnel Analytics"
DASHBOARD_SUBTITLE = "Task 11 · Offer Generation & E-Sign Design"
PAGE_ICON          = "📋"

# Departments and roles (kept consistent across generated data)
DEPARTMENTS = [
    "Engineering", "Product", "Design", "Data", "Sales",
    "Marketing", "Finance", "HR", "Operations", "Legal",
]

ROLES = [
    "Software Engineer", "Data Analyst", "Product Manager",
    "UX Designer", "Sales Executive", "Marketing Specialist",
    "Financial Analyst", "HR Business Partner", "Operations Lead",
    "Legal Counsel", "Backend Engineer", "Frontend Engineer",
    "DevOps Engineer", "ML Engineer", "Content Strategist",
]

SOURCE_CHANNELS = ["linkedin", "referral", "company_portal", "naukri", "internshala"]
