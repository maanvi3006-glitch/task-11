"""
dashboard.py
============
PlaceMux · Task 11 · Offer Generation & E-Sign Design
------------------------------------------------------
Streamlit dashboard — reads directly from SQLite via the analytics modules.

Execution order: 7 of 11
Run:  streamlit run dashboard.py

Sections
--------
  1. Executive KPIs       – top-line numbers the founder checks daily
  2. Offer Funnel         – funnel chart, stage drop-off, cohort tables
  3. E-Sign Analytics     – provider breakdown, verification trends
  4. Data Quality Monitor – freshness, null rates, duplicates, anomalies
  5. Export               – download full metrics CSV

Architecture
------------
  dashboard.py imports:
    MetricsEngine  (metrics_engine.py)  → KPI scalars
    FunnelAnalytics (offer_funnel.py)   → tabular / chart data
    ValidationEngine (validation.py)    → data-quality report

  No SQL lives in this file.  All data comes from the modules above.
"""

import logging
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import (
    DASHBOARD_SUBTITLE,
    DASHBOARD_TITLE,
    DB_PATH,
    EXPORTS_DIR,
    EXPORT_FILENAME,
    PAGE_ICON,
)
from metrics_engine import MetricsEngine
from offer_funnel import FunnelAnalytics
from validation import ValidationEngine

log = logging.getLogger(__name__)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title=DASHBOARD_TITLE,
    page_icon=PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Colour palette (consistent across all charts) ────────────────────────────
COLOURS = {
    "primary":   "#4F46E5",
    "success":   "#10B981",
    "warning":   "#F59E0B",
    "danger":    "#EF4444",
    "neutral":   "#6B7280",
    "signed":    "#10B981",
    "rejected":  "#EF4444",
    "sent":      "#4F46E5",
    "generated": "#8B5CF6",
    "viewed":    "#F59E0B",
}

FUNNEL_PALETTE = [
    "#8B5CF6", "#4F46E5", "#F59E0B", "#10B981", "#EF4444",
]

# ── Cached data loaders ───────────────────────────────────────────────────────
# TTL = 60 s so the dashboard refreshes without a full page reload.

@st.cache_data(ttl=60, show_spinner=False)
def load_kpis() -> dict:
    engine  = MetricsEngine(DB_PATH)
    results = engine.run_all()
    return {r.name: r for r in results}


@st.cache_data(ttl=60, show_spinner=False)
def load_funnel_data() -> dict:
    fa = FunnelAnalytics(DB_PATH)
    return fa.get_all()


@st.cache_data(ttl=60, show_spinner=False)
def load_validation_report():
    ve = ValidationEngine(DB_PATH)
    return ve.run_all()


@st.cache_data(ttl=60, show_spinner=False)
def load_daily_trend() -> pd.DataFrame:
    engine = MetricsEngine(DB_PATH)
    rows   = engine.get_daily_trend(days=30)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).rename(columns={"cnt": "count"})


@st.cache_data(ttl=60, show_spinner=False)
def load_verification_trend() -> pd.DataFrame:
    engine = MetricsEngine(DB_PATH)
    rows   = engine.get_verification_trend(days=30)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).rename(columns={"cnt": "count"})


# ── Helper: metric card ───────────────────────────────────────────────────────

def kpi_card(col, label: str, value, delta: str = "", colour: str = "#4F46E5") -> None:
    """Render a single KPI tile inside a Streamlit column."""
    col.metric(label=label, value=value, delta=delta if delta else None)


def status_badge(status: str) -> str:
    icons = {"pass": "🟢", "warn": "🟡", "fail": "🔴"}
    return icons.get(status, "⚪")


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar() -> None:
    with st.sidebar:
        st.image(
            "https://placehold.co/200x60/4F46E5/FFFFFF?text=PlaceMux",
            use_container_width=True,
        )
        st.markdown(f"### {PAGE_ICON} {DASHBOARD_TITLE}")
        st.caption(DASHBOARD_SUBTITLE)
        st.divider()

        st.markdown("**Navigation**")
        st.markdown("""
- 📊 Executive KPIs
- 🔽 Offer Funnel
- ✍️ E-Sign Analytics
- 🛡️ Data Quality
- 📥 Export
        """)
        st.divider()

        st.markdown("**Database**")
        db_path = Path(DB_PATH)
        if db_path.exists():
            size_kb = db_path.stat().st_size / 1024
            st.success(f"Connected  ·  {size_kb:.1f} KB")
        else:
            st.error("Database not found")

        st.divider()
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()

        st.caption("Data refreshes every 60 s automatically.")


# ── Section 1: Executive KPIs ─────────────────────────────────────────────────

def render_executive_kpis(kpis: dict) -> None:
    st.header("📊 Executive KPIs")
    st.caption("Top-line offer funnel numbers — sourced live from SQLite event tables.")

    def val(name: str):
        r = kpis.get(name)
        if r is None or r.value is None:
            return "—"
        v = r.value
        if isinstance(v, float):
            return f"{v:.1f}%"  if "%" in name else f"{v:.1f}"
        return str(v)

    # Row 1 — volume
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📋 Total Generated",  val("Total Offers Generated"))
    c2.metric("📤 Total Sent",        val("Total Offers Sent"))
    c3.metric("👁️ Total Viewed",      val("Total Offers Viewed"))
    c4.metric("✅ Total Signed",       val("Total Offers Signed"))

    # Row 2 — rates
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("🎯 Conversion Rate",   val("Offer Conversion Rate (%)"))
    c6.metric("📬 Send Rate",          val("Offer Send Rate (%)"))
    c7.metric("👁️ View Rate",          val("Offer View Rate (%)"))
    c8.metric("❌ Rejection Rate",     val("Rejection Rate (%)"))

    # Row 3 — e-sign + timing
    c9, c10, c11, c12 = st.columns(4)
    c9.metric("✍️  Sign-to-View",      val("Sign-to-View Rate (%)"))
    c10.metric("🔐 Verification Pass", val("Verification Success Rate (%)"))
    c11.metric("⏱️ Gen→Sent (hrs)",    val("Avg Time Generated → Sent (hrs)"))
    c12.metric("⏱️ View→Sign (hrs)",   val("Avg Time Viewed → Signed (hrs)"))

    # Row 4 — pipeline health
    c13, c14, c15, c16 = st.columns(4)
    c13.metric("⏳ Pending Decision",  val("Offers Pending Decision"))
    c14.metric("💀 Expired Offers",    val("Offers Expired"))
    c15.metric("🏆 Top E-Sign Provider", val("Top E-Sign Provider"))
    c16.metric("🔁 Re-check Rate",     val("Verification Re-check Rate (%)"))

    # KPI detail expander
    with st.expander("📖 Metric Dictionary — click to expand", expanded=False):
        rows = []
        for name, r in kpis.items():
            rows.append({
                "Metric":           r.name,
                "Value":            r.value,
                "Event Dependency": ", ".join(r.event_dependency),
                "Business Decision":r.business_decision,
                "Action Trigger":   r.action_trigger,
                "Status":           "⚠️ Error" if r.error else "✓",
            })
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )


# ── Section 2: Offer Funnel ───────────────────────────────────────────────────

def render_offer_funnel(funnel_data: dict, daily_df: pd.DataFrame) -> None:
    st.header("🔽 Offer Funnel")

    # ── Funnel chart ──────────────────────────────────────────────────────
    summary = funnel_data.get("funnel_summary", [])
    if summary:
        df_funnel = pd.DataFrame(summary)

        col_chart, col_table = st.columns([3, 2])

        with col_chart:
            st.subheader("Funnel Chart")
            fig = go.Figure(go.Funnel(
                y      = df_funnel["stage"],
                x      = df_funnel["count"],
                marker = dict(color=FUNNEL_PALETTE),
                textinfo="value+percent previous",
                textfont=dict(size=14),
            ))
            fig.update_layout(
                margin=dict(l=10, r=10, t=10, b=10),
                height=380,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor ="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_table:
            st.subheader("Stage Summary")
            display_cols = [
                "stage", "count", "pct_of_generated",
                "drop_from_prev", "drop_rate_pct",
            ]
            df_display = df_funnel[display_cols].copy()
            df_display.columns = [
                "Stage", "Count", "% of Generated",
                "Lost vs Prev", "Drop Rate %",
            ]
            st.dataframe(df_display, use_container_width=True, hide_index=True)

    st.divider()

    # ── Stage drop-off bar chart ──────────────────────────────────────────
    dropoff = funnel_data.get("stage_dropoff", [])
    if dropoff:
        st.subheader("Stage Drop-off Analysis")
        df_drop = pd.DataFrame(dropoff)
        fig2 = px.bar(
            df_drop,
            x="transition",
            y=["to_count", "lost"],
            barmode="stack",
            labels={"value": "Offers", "variable": "Outcome", "transition": "Transition"},
            color_discrete_map={"to_count": COLOURS["success"], "lost": COLOURS["danger"]},
            text_auto=True,
        )
        fig2.update_layout(
            height=320,
            legend_title_text="",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor ="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # ── Daily event trend ─────────────────────────────────────────────────
    st.subheader("Daily Event Volume (Last 30 Days)")
    if not daily_df.empty:
        EVENT_COLOURS = {
            "offer_generated": COLOURS["generated"],
            "offer_sent":      COLOURS["sent"],
            "offer_opened":    COLOURS["viewed"],
            "offer_signed":    COLOURS["signed"],
            "offer_rejected":  COLOURS["rejected"],
        }
        fig3 = px.line(
            daily_df,
            x="date",
            y="count",
            color="event_name",
            markers=True,
            color_discrete_map=EVENT_COLOURS,
            labels={"date": "Date", "count": "Events", "event_name": "Event"},
        )
        fig3.update_layout(
            height=320,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor ="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("No daily trend data available.")

    st.divider()

    # ── Cohort tables ─────────────────────────────────────────────────────
    tab1, tab2, tab3 = st.tabs(
        ["📅 Weekly Cohort", "🏢 By Department", "📣 By Channel"]
    )

    with tab1:
        weekly = funnel_data.get("cohort_by_week", [])
        if weekly:
            df_w = pd.DataFrame(weekly)
            df_w["conversion_pct"] = df_w["conversion_pct"].apply(lambda x: f"{x}%")
            st.dataframe(df_w, use_container_width=True, hide_index=True)
        else:
            st.info("No weekly cohort data.")

    with tab2:
        dept = funnel_data.get("cohort_by_department", [])
        if dept:
            df_d = pd.DataFrame(dept)
            fig_dept = px.bar(
                df_d,
                x="department",
                y="conversion_pct",
                color="conversion_pct",
                color_continuous_scale=["#EF4444", "#F59E0B", "#10B981"],
                text="conversion_pct",
                labels={"conversion_pct": "Conversion %", "department": "Department"},
            )
            fig_dept.update_traces(texttemplate="%{text}%", textposition="outside")
            fig_dept.update_layout(
                height=340,
                showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor ="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_dept, use_container_width=True)
            st.dataframe(df_d, use_container_width=True, hide_index=True)
        else:
            st.info("No department cohort data.")

    with tab3:
        channel = funnel_data.get("cohort_by_channel", [])
        if channel:
            df_c = pd.DataFrame(channel)
            fig_ch = px.bar(
                df_c,
                x="channel",
                y="conversion_pct",
                color="conversion_pct",
                color_continuous_scale=["#EF4444", "#F59E0B", "#10B981"],
                text="conversion_pct",
                labels={"conversion_pct": "Conversion %", "channel": "Channel"},
            )
            fig_ch.update_traces(texttemplate="%{text}%", textposition="outside")
            fig_ch.update_layout(
                height=320,
                showlegend=False,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor ="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_ch, use_container_width=True)
            st.dataframe(df_c, use_container_width=True, hide_index=True)
        else:
            st.info("No channel cohort data.")

    st.divider()

    # ── Time-to-sign distribution ─────────────────────────────────────────
    st.subheader("⏱️ Time-to-Sign Distribution (View → Sign)")
    tts = funnel_data.get("time_to_sign_dist", [])
    if tts:
        df_tts = pd.DataFrame(tts)
        fig_tts = px.bar(
            df_tts,
            x="bucket",
            y="count",
            color="count",
            color_continuous_scale=["#10B981", "#F59E0B", "#EF4444"],
            text="count",
            labels={"bucket": "Time Bucket", "count": "Offers"},
        )
        fig_tts.update_traces(textposition="outside")
        fig_tts.update_layout(
            height=300,
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor ="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_tts, use_container_width=True)


# ── Section 3: E-Sign Analytics ───────────────────────────────────────────────

def render_esign_analytics(
    funnel_data: dict,
    verif_df: pd.DataFrame,
    kpis: dict,
) -> None:
    st.header("✍️ E-Sign Analytics")

    # ── Provider breakdown ────────────────────────────────────────────────
    st.subheader("Provider Performance")
    providers = funnel_data.get("provider_performance", [])
    if providers:
        df_prov = pd.DataFrame(providers)

        col_a, col_b = st.columns(2)

        with col_a:
            fig_prov = px.bar(
                df_prov,
                x="provider",
                y="total_signatures",
                color="success_rate_pct",
                color_continuous_scale=["#EF4444", "#F59E0B", "#10B981"],
                text="total_signatures",
                labels={
                    "provider": "Provider",
                    "total_signatures": "Total Signatures",
                    "success_rate_pct": "Success Rate %",
                },
                title="Signature Volume by Provider",
            )
            fig_prov.update_traces(textposition="outside")
            fig_prov.update_layout(
                height=320,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor ="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_prov, use_container_width=True)

        with col_b:
            fig_succ = px.bar(
                df_prov,
                x="provider",
                y="success_rate_pct",
                color="success_rate_pct",
                color_continuous_scale=["#EF4444", "#F59E0B", "#10B981"],
                text="success_rate_pct",
                labels={
                    "provider": "Provider",
                    "success_rate_pct": "Success Rate %",
                },
                title="Verification Success Rate by Provider",
            )
            fig_succ.update_traces(
                texttemplate="%{text}%", textposition="outside"
            )
            fig_succ.update_layout(
                height=320,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor ="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_succ, use_container_width=True)

        # Avg verification latency
        st.dataframe(
            df_prov[[
                "provider", "total_signatures", "verified",
                "failed", "success_rate_pct", "avg_verify_latency_mins",
            ]].rename(columns={
                "provider":                "Provider",
                "total_signatures":        "Total Sigs",
                "verified":                "Verified",
                "failed":                  "Failed",
                "success_rate_pct":        "Success %",
                "avg_verify_latency_mins": "Avg Latency (mins)",
            }),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ── Verification trend ────────────────────────────────────────────────
    st.subheader("Verification Outcome Trend (Last 30 Days)")
    if not verif_df.empty:
        RESULT_COLOURS = {
            "pass": COLOURS["success"],
            "fail": COLOURS["danger"],
            "pending": COLOURS["warning"],
        }
        fig_vt = px.line(
            verif_df,
            x="date",
            y="count",
            color="result",
            markers=True,
            color_discrete_map=RESULT_COLOURS,
            labels={"date": "Date", "count": "Verifications", "result": "Outcome"},
        )
        fig_vt.update_layout(
            height=300,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor ="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_vt, use_container_width=True)
    else:
        st.info("No verification trend data available.")

    st.divider()

    # ── Rejection reasons ─────────────────────────────────────────────────
    st.subheader("Rejection Reasons")
    rejections = funnel_data.get("rejection_breakdown", [])
    if rejections:
        df_rej = pd.DataFrame(rejections)
        col_pie, col_tbl = st.columns([2, 2])

        with col_pie:
            fig_rej = px.pie(
                df_rej,
                names="reason",
                values="count",
                color_discrete_sequence=px.colors.qualitative.Set2,
                hole=0.4,
            )
            fig_rej.update_layout(
                height=300,
                paper_bgcolor="rgba(0,0,0,0)",
            )
            st.plotly_chart(fig_rej, use_container_width=True)

        with col_tbl:
            st.dataframe(
                df_rej.rename(columns={
                    "reason": "Reason",
                    "count":  "Count",
                    "pct_of_rejections": "% of Rejections",
                }),
                use_container_width=True,
                hide_index=True,
            )
    else:
        st.info("No rejection data.")

    st.divider()

    # ── Stalled offers ────────────────────────────────────────────────────
    st.subheader("⏳ Stalled Offers (Sent/Viewed — No Decision)")
    stalled = funnel_data.get("top_stalled_offers", [])
    if stalled:
        df_stall = pd.DataFrame(stalled)
        st.dataframe(
            df_stall[[
                "full_name", "email", "department", "role_title",
                "status", "hours_idle", "expiry_at", "validity",
            ]].rename(columns={
                "full_name":  "Candidate",
                "email":      "Email",
                "department": "Dept",
                "role_title": "Role",
                "status":     "Status",
                "hours_idle": "Idle (hrs)",
                "expiry_at":  "Expires At",
                "validity":   "Validity",
            }),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success("No stalled offers — all sent offers have a decision.")


# ── Section 4: Data Quality Monitor ──────────────────────────────────────────

def render_data_quality(report) -> None:
    st.header("🛡️ Data Quality Monitor")

    # ── Overall badge ─────────────────────────────────────────────────────
    overall = report.overall_status
    badge_map = {
        "pass": ("✅ All Checks Passed", "success"),
        "warn": ("⚠️ Warnings Detected", "warning"),
        "fail": ("🚨 Failures Detected", "error"),
    }
    label, kind = badge_map.get(overall, ("Unknown", "info"))
    getattr(st, kind)(
        f"{label}  —  "
        f"Pass: {len(report.passed)}  |  "
        f"Warn: {len(report.warnings)}  |  "
        f"Fail: {len(report.failures)}  |  "
        f"Total: {len(report.results)}"
    )

    # ── Summary metrics ────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("✅ Passed",   len(report.passed))
    c2.metric("⚠️ Warnings", len(report.warnings))
    c3.metric("❌ Failures", len(report.failures))
    c4.metric("📋 Total",    len(report.results))

    st.divider()

    # ── Checks by category ────────────────────────────────────────────────
    categories = {
        "Freshness":       [r for r in report.results if "Freshness" in r.check_name],
        "Null Rates":      [r for r in report.results if "Null Rate" in r.check_name],
        "Duplicates":      [r for r in report.results if "Duplicate" in r.check_name],
        "Anomaly":         [r for r in report.results if "Anomaly" in r.check_name],
        "Completeness":    [r for r in report.results if "Completeness" in r.check_name],
        "Reconciliation":  [r for r in report.results if "Reconciliation" in r.check_name],
        "FK Integrity":    [r for r in report.results if "FK Integrity" in r.check_name],
    }

    for cat_name, checks in categories.items():
        if not checks:
            continue

        failures = [c for c in checks if c.status == "fail"]
        warnings = [c for c in checks if c.status == "warn"]
        icon = "✅" if not failures and not warnings else ("⚠️" if not failures else "❌")

        with st.expander(f"{icon} {cat_name}  ({len(checks)} checks)", expanded=bool(failures)):
            rows = [{
                "Status": status_badge(c.status),
                "Check":  c.check_name,
                "Detail": c.detail,
            } for c in checks]
            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()

    # ── Full check log ────────────────────────────────────────────────────
    with st.expander("📋 Full Validation Log", expanded=False):
        all_rows = [{
            "Status":     status_badge(r.status),
            "Check Name": r.check_name,
            "Detail":     r.detail,
            "Value":      str(r.value) if r.value is not None else "—",
        } for r in report.results]
        st.dataframe(
            pd.DataFrame(all_rows),
            use_container_width=True,
            hide_index=True,
        )


# ── Section 5: Export ─────────────────────────────────────────────────────────

def render_export(funnel_data: dict, kpis: dict) -> None:
    st.header("📥 Export")
    st.markdown(
        "Download a full CSV snapshot of all offer funnel metrics "
        "for offline analysis or stakeholder sharing."
    )

    col_l, col_r = st.columns(2)

    # ── Export 1: Full metrics CSV ────────────────────────────────────────
    with col_l:
        st.subheader("📊 Full Metrics Export")
        st.caption("Includes funnel summary, cohorts, provider stats, rejections.")

        export_path = EXPORTS_DIR / EXPORT_FILENAME
        if st.button("⚙️ Regenerate Metrics CSV"):
            with st.spinner("Generating …"):
                fa = FunnelAnalytics(DB_PATH)
                fa.export_metrics_csv()
            st.success(f"Written → {export_path.name}")

        if export_path.exists():
            with open(export_path, "rb") as fh:
                st.download_button(
                    label="⬇️ Download offer_metrics_export.csv",
                    data=fh.read(),
                    file_name=EXPORT_FILENAME,
                    mime="text/csv",
                    use_container_width=True,
                )
            size_kb = export_path.stat().st_size / 1024
            st.caption(f"File size: {size_kb:.1f} KB")
        else:
            st.info("Click 'Regenerate' to create the export file.")

    # ── Export 2: KPI snapshot ────────────────────────────────────────────
    with col_r:
        st.subheader("🎯 KPI Snapshot")
        st.caption("Single-row CSV of all current KPI values.")

        kpi_rows = [{
            "metric":           r.name,
            "value":            r.value,
            "event_dependency": ", ".join(r.event_dependency),
            "business_decision":r.business_decision,
            "action_trigger":   r.action_trigger,
        } for r in kpis.values()]

        kpi_csv = pd.DataFrame(kpi_rows).to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download KPI Snapshot CSV",
            data=kpi_csv,
            file_name="kpi_snapshot.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.caption(f"{len(kpi_rows)} KPIs included.")

    st.divider()

    # ── Preview table ─────────────────────────────────────────────────────
    st.subheader("Preview — Funnel Summary")
    summary = funnel_data.get("funnel_summary", [])
    if summary:
        st.dataframe(
            pd.DataFrame(summary),
            use_container_width=True,
            hide_index=True,
        )


# ── Main layout ───────────────────────────────────────────────────────────────

def main() -> None:
    render_sidebar()

    # ── Header ────────────────────────────────────────────────────────────
    st.title(f"{PAGE_ICON} {DASHBOARD_TITLE}")
    st.caption(DASHBOARD_SUBTITLE)
    st.divider()

    # ── Load data (cached) ────────────────────────────────────────────────
    with st.spinner("Loading data …"):
        kpis        = load_kpis()
        funnel_data = load_funnel_data()
        report      = load_validation_report()
        daily_df    = load_daily_trend()
        verif_df    = load_verification_trend()

    # ── Tabs ──────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Executive KPIs",
        "🔽 Offer Funnel",
        "✍️ E-Sign Analytics",
        "🛡️ Data Quality",
        "📥 Export",
    ])

    with tab1:
        render_executive_kpis(kpis)

    with tab2:
        render_offer_funnel(funnel_data, daily_df)

    with tab3:
        render_esign_analytics(funnel_data, verif_df, kpis)

    with tab4:
        render_data_quality(report)

    with tab5:
        render_export(funnel_data, kpis)


if __name__ == "__main__":
    main()
