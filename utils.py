"""
utils.py
========
PlaceMux · Task 11 · Shared formatting and helper utilities.
Imported by metrics_engine, offer_funnel, and dashboard.
"""

from datetime import datetime, timezone


def pct(numerator: float, denominator: float, decimals: int = 2) -> float:
    """Safe percentage calculation — returns 0.0 on zero denominator."""
    if not denominator:
        return 0.0
    return round(100.0 * numerator / denominator, decimals)


def fmt_pct(value: float | None) -> str:
    """Format a float as '45.23%' or '—' if None."""
    if value is None:
        return "—"
    return f"{value:.2f}%"


def fmt_hrs(value: float | None) -> str:
    """Format float hours as '2.5 hrs' or '—' if None."""
    if value is None:
        return "—"
    return f"{value:.1f} hrs"


def utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hours_since(iso_str: str) -> float | None:
    """Return hours elapsed since an ISO-8601 UTC timestamp string."""
    try:
        dt = datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        delta = datetime.now(timezone.utc) - dt
        return round(delta.total_seconds() / 3600, 2)
    except (ValueError, TypeError):
        return None


def truncate(text: str, max_len: int = 60) -> str:
    """Truncate a string with ellipsis if over max_len."""
    if not text:
        return ""
    return text if len(text) <= max_len else text[: max_len - 3] + "..."
