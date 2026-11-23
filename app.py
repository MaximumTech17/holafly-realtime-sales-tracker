"""Holafly Real-Time Sales Tracker MVP — Executive Operations Cockpit.

Visual system aligns Official Holafly brand identity (static/holafly_logo.svg, #e63946)
with the Intercom editorial data system (DESIGN (1).md):
  - Warm editorial off-white canvas (#faf9f6), Linen sidebar (#f1eee9), Pure White cards (#ffffff)
  - Crisp 1px warm stone hairline borders (#dedbd6) and architectural 4px border-radius
  - Inter light/regular editorial typography + IBM Plex Mono uppercase micro-labels (12px, 1.2px)
  - Clean 2px solid active underline tab navigation, zero drop-shadows, zero emojis
  - All custom HTML flattened before st.markdown(..., unsafe_allow_html=True) to prevent raw HTML leakage
"""

from __future__ import annotations

import base64
import html
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.analytics import (
    compute_agent_leaderboard,
    compute_discount_breakdown,
    compute_executive_kpis,
    compute_market_language_capacity,
    compute_market_pacing_table,
    compute_pipeline_health,
    compute_timeseries_10m,
    evaluate_anomaly_status,
    get_current_shift_bounds_utc,
)
from src.config import (
    AGENTS,
    COLORS,
    DB_PATH,
    LOGO_SVG_PATH,
    SCENARIO_MODES,
    SHIFTS,
    SQL_VIEWS_PATH,
    TARGET_ORDERS_PER_AGENT_HOUR,
    TIMEZONE_OPTIONS,
    VALID_LANGUAGES,
    VALID_MARKETS,
)
from src.db import load_quarantined_orders, load_valid_sales
from src.mock_generator import (
    initialize_or_reset_db,
    inject_manual_micro_batch,
    sync_live_orders_to_now,
)

st.set_page_config(
    page_title="Holafly Real-Time Sales Tracker",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _html(markup: str) -> str:
    """Flatten multi-line HTML by stripping leading whitespace per line so Markdown never emits code blocks."""
    return "".join(line.strip() for line in markup.splitlines() if line.strip())


def _load_logo_data_uri() -> str:
    """Read static/holafly_logo.svg and encode as base64 data URI for reliable Streamlit rendering."""
    if LOGO_SVG_PATH.exists():
        raw_bytes = LOGO_SVG_PATH.read_bytes()
        b64 = base64.b64encode(raw_bytes).decode("ascii")
        return f"data:image/svg+xml;base64,{b64}"
    return ""


# Holafly + Intercom Editorial CSS System (DESIGN (1).md)
st.markdown(
    _html(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@300;400;500;600&display=swap');

        :root {
            --canvas-cream: #faf9f6;
            --linen: #f1eee9;
            --stone: #d3cec6;
            --hairline: #dedbd6;
            --pure-white: #ffffff;
            --ink: #111111;
            --carbon: #000000;
            --iron: #414141;
            --graphite: #585858;
            --smoke: #888888;
            --holafly-red: #e63946;
            --forest-ok: #15803d;
            --amber-warn: #b45309;
        }

        html, body, [class*="css"], .stApp {
            font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif !important;
            color: var(--ink);
            font-feature-settings: "tnum" on;
        }

        /* Warm Editorial Canvas */
        .stApp {
            background-color: var(--canvas-cream) !important;
        }

        header[data-testid="stHeader"] {
            background-color: var(--canvas-cream) !important;
            border-bottom: 1px solid var(--hairline);
        }

        .block-container {
            max-width: 1380px !important;
            padding: 1.5rem 2.2rem 2.8rem 2.2rem !important;
        }

        /* Linen Sidebar Surface */
        section[data-testid="stSidebar"] {
            background-color: var(--linen) !important;
            border-right: 1px solid var(--hairline) !important;
        }
        section[data-testid="stSidebar"] .block-container {
            padding: 1.25rem 1.15rem 2rem 1.15rem !important;
        }
        .sidebar-eyebrow {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            color: var(--graphite);
            margin: 0 0 12px 0;
        }

        /* Sharp 4px Architectural Buttons — Holafly Primary (#e63946) & Solid Black Secondary (#000000) */
        section[data-testid="stSidebar"] button[kind="primary"] {
            background-color: var(--holafly-red) !important;
            color: var(--pure-white) !important;
            border: 1px solid var(--holafly-red) !important;
            border-radius: 4px !important;
            padding: 0.62rem 1rem !important;
            font-weight: 500 !important;
            font-size: 14px !important;
            box-shadow: none !important;
            white-space: nowrap !important;
        }
        section[data-testid="stSidebar"] button[kind="primary"]:hover {
            background-color: #c92a37 !important;
            border-color: #c92a37 !important;
            color: var(--pure-white) !important;
        }
        section[data-testid="stSidebar"] button[kind="secondary"] {
            background-color: var(--carbon) !important;
            color: var(--pure-white) !important;
            border: 1px solid var(--carbon) !important;
            border-radius: 4px !important;
            padding: 0.60rem 1rem !important;
            font-weight: 400 !important;
            font-size: 14px !important;
            box-shadow: none !important;
            white-space: nowrap !important;
        }
        section[data-testid="stSidebar"] button[kind="secondary"]:hover {
            background-color: #262626 !important;
            border-color: #262626 !important;
            color: var(--pure-white) !important;
        }

        /* Inputs, Selectboxes & Multiselect Tags (Sharp 4px Radius, Warm Neutrals) */
        div[data-baseweb="select"] > div,
        div[data-baseweb="input"] > div {
            border-radius: 4px !important;
            border-color: var(--hairline) !important;
            background-color: var(--pure-white) !important;
        }
        span[data-baseweb="tag"] {
            background-color: var(--linen) !important;
            color: var(--ink) !important;
            border: 1px solid var(--hairline) !important;
            border-radius: 4px !important;
            font-size: 12px !important;
            font-weight: 400 !important;
        }
        span[data-baseweb="tag"] svg {
            fill: var(--iron) !important;
        }

        /* Official Holafly Editorial Header */
        .hf-header {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 12px 24px;
            padding: 4px 0 18px 0;
            margin-bottom: 16px;
            border-bottom: 1px solid var(--hairline);
        }
        .hf-brand-row {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 16px;
        }
        .hf-logo-wrap {
            display: inline-flex;
            align-items: center;
            padding-right: 16px;
            border-right: 1px solid var(--hairline);
        }
        .hf-logo-wrap img {
            height: 28px;
            width: auto;
            display: block;
        }
        .hf-title-block {
            display: flex;
            flex-direction: column;
            gap: 2px;
        }
        .hf-eyebrow {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            color: var(--graphite);
            line-height: 1.3;
        }
        .hf-title {
            font-family: 'Inter', sans-serif;
            font-size: 26px;
            font-weight: 300;
            letter-spacing: -0.6px;
            line-height: 1.2;
            color: var(--ink);
            margin: 0;
        }
        .hf-meta-badge {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            font-weight: 400;
            letter-spacing: 1px;
            text-transform: uppercase;
            color: var(--iron);
            background-color: var(--pure-white);
            border: 1px solid var(--hairline);
            border-radius: 4px;
            padding: 6px 12px;
            white-space: nowrap;
        }

        /* Compact 1-Row Pipeline Telemetry Strip */
        .telemetry-strip {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
            gap: 12px 24px;
            background-color: var(--pure-white);
            border: 1px solid var(--hairline);
            border-radius: 4px;
            padding: 12px 18px;
            margin-bottom: 14px;
        }
        .tele-item {
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 120px;
        }
        .tele-label {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            color: var(--graphite);
            white-space: nowrap;
        }
        .tele-value {
            font-size: 14px;
            font-weight: 500;
            color: var(--ink);
            white-space: nowrap;
            font-variant-numeric: tabular-nums;
        }
        .tele-sub {
            font-size: 12px;
            color: var(--iron);
            font-weight: 400;
        }
        .sla-tag {
            display: inline-block;
            padding: 1px 7px;
            border-radius: 4px;
            font-family: 'IBM Plex Mono', monospace;
            font-size: 10.5px;
            font-weight: 500;
            letter-spacing: 0.8px;
            margin-left: 6px;
            vertical-align: middle;
        }
        .sla-pass {
            background-color: #ecfdf3;
            color: var(--forest-ok);
            border: 1px solid #bbf7d0;
        }
        .sla-fail {
            background-color: #fef2f2;
            color: var(--holafly-red);
            border: 1px solid #fecaca;
        }

        /* Restrained Editorial Alert Banner */
        .alert-card {
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            gap: 10px 14px;
            background-color: var(--pure-white);
            border: 1px solid var(--hairline);
            border-left-width: 3px;
            border-radius: 4px;
            padding: 12px 16px;
            margin-bottom: 18px;
        }
        .alert-tag {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            padding: 2px 8px;
            border-radius: 4px;
            white-space: nowrap;
        }
        .alert-msg {
            font-size: 14px;
            line-height: 1.45;
            color: var(--ink);
            font-weight: 400;
            flex: 1 1 320px;
        }

        /* Clean Horizontal Tabs with 2px Solid Active Underline (Intercom Editorial — No Pills) */
        .stTabs [data-baseweb="tab-list"] {
            gap: 28px !important;
            background-color: transparent !important;
            border-bottom: 1px solid var(--hairline) !important;
            border-radius: 0 !important;
            padding: 0 !important;
            margin-bottom: 20px !important;
            box-shadow: none !important;
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 0 !important;
            padding: 10px 2px !important;
            height: auto !important;
            background-color: transparent !important;
            color: var(--smoke) !important;
            font-size: 14px !important;
            font-weight: 400 !important;
            border: none !important;
            border-bottom: 2px solid transparent !important;
            white-space: nowrap !important;
        }
        .stTabs [data-baseweb="tab"]:hover {
            color: var(--ink) !important;
        }
        .stTabs [data-baseweb="tab"][aria-selected="true"] {
            background-color: transparent !important;
            color: var(--ink) !important;
            font-weight: 500 !important;
            border-bottom: 2px solid var(--ink) !important;
        }
        .stTabs [data-baseweb="tab-highlight"],
        .stTabs [data-baseweb="tab-border"] {
            display: none !important;
        }

        /* Responsive Custom KPI Card Grid (Architectural 4px Radius, Hairline Border, Zero Truncation) */
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(195px, 1fr));
            gap: 14px;
            margin: 2px 0 22px 0;
        }
        .kpi-card {
            background-color: var(--pure-white);
            border: 1px solid var(--hairline);
            border-top: 2px solid var(--holafly-red);
            border-radius: 4px;
            padding: 16px 18px 15px 18px;
            overflow: visible;
        }
        .kpi-label {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            color: var(--graphite);
            margin-bottom: 8px;
            white-space: normal;
            overflow: visible;
            line-height: 1.35;
        }
        .kpi-value {
            font-family: 'Inter', sans-serif;
            font-size: 26px;
            font-weight: 400;
            letter-spacing: -0.5px;
            color: var(--ink);
            line-height: 1.15;
            margin-bottom: 6px;
            font-variant-numeric: tabular-nums;
            white-space: normal;
            overflow: visible;
        }
        .kpi-delta {
            font-size: 12.5px;
            font-weight: 400;
            line-height: 1.4;
            white-space: normal;
            overflow: visible;
        }
        .delta-neutral { color: var(--iron); }
        .delta-pos { color: var(--forest-ok); font-weight: 500; }
        .delta-neg { color: var(--holafly-red); font-weight: 500; }

        /* Editorial Section Headers */
        .section-eyebrow {
            font-family: 'IBM Plex Mono', monospace;
            font-size: 11px;
            font-weight: 500;
            letter-spacing: 1.2px;
            text-transform: uppercase;
            color: var(--graphite);
            margin: 16px 0 2px 0;
        }
        .section-heading {
            font-family: 'Inter', sans-serif;
            font-size: 20px;
            font-weight: 300;
            letter-spacing: -0.3px;
            color: var(--ink);
            margin: 0 0 12px 0;
            line-height: 1.3;
        }

        /* Clean Flat Surfaces for DataFrames & Expanders */
        div[data-testid="stDataFrame"] {
            background-color: var(--pure-white);
            border: 1px solid var(--hairline);
            border-radius: 4px;
            padding: 2px;
        }
        div[data-testid="stExpander"] {
            background-color: var(--pure-white);
            border: 1px solid var(--hairline) !important;
            border-radius: 4px !important;
        }
        </style>
        """
    ),
    unsafe_allow_html=True,
)


def _ensure_db_ready(scenario_mode: str) -> None:
    """Ensure data/ directory exists and SQLite DB is initialized/synced on ephemeral restarts."""
    os.makedirs(DB_PATH.parent, exist_ok=True)
    if not DB_PATH.exists() or DB_PATH.stat().st_size == 0:
        initialize_or_reset_db(db_path=DB_PATH, scenario_mode=scenario_mode)
    else:
        sync_live_orders_to_now(db_path=DB_PATH, scenario_mode=scenario_mode)


def _ensure_session_defaults() -> None:
    if "active_scenario" not in st.session_state:
        st.session_state["active_scenario"] = "DEFAULT_LIVE"
        os.makedirs(DB_PATH.parent, exist_ok=True)
        initialize_or_reset_db(db_path=DB_PATH, scenario_mode="DEFAULT_LIVE")
    else:
        _ensure_db_ready(st.session_state["active_scenario"])
    if "last_manual_batch_msg" not in st.session_state:
        st.session_state["last_manual_batch_msg"] = ""


def _format_ts_local(iso_utc: str | None, offset_hours: int, tz_short: str) -> str:
    if not iso_utc:
        return "N/A"
    dt = datetime.strptime(iso_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    local_dt = dt + timedelta(hours=offset_hours)
    return local_dt.strftime(f"%Y-%m-%d %H:%M:%S {tz_short}")


def _alert_styles(state: str) -> tuple[str, str, str]:
    """Return (left_border_color, tag_bg, tag_text) aligned with Holafly + Intercom palette."""
    mapping = {
        "CRITICAL DROP": ("#e63946", "#fef2f2", "#b91c1c"),
        "WARNING": ("#b45309", "#fffbeb", "#92400e"),
        "SURGE": ("#15803d", "#ecfdf3", "#15803d"),
        "NORMAL": ("#111111", "#f1eee9", "#111111"),
    }
    return mapping.get(state, ("#111111", "#f1eee9", "#111111"))


def _render_kpi_grid(cards: list[dict[str, str]]) -> None:
    """Render flat architectural HTML KPI cards with zero leading indentation and zero truncation."""
    parts = ['<div class="kpi-grid">']
    for card in cards:
        tone = card.get("tone", "neutral")
        parts.append(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">{html.escape(card["label"])}</div>'
            f'<div class="kpi-value">{html.escape(card["value"])}</div>'
            f'<div class="kpi-delta delta-{tone}">{html.escape(card["delta"])}</div>'
            f"</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _render_section_header(eyebrow: str, title: str) -> None:
    st.markdown(
        f'<div class="section-eyebrow">{html.escape(eyebrow)}</div>'
        f'<div class="section-heading">{html.escape(title)}</div>',
        unsafe_allow_html=True,
    )


def _apply_editorial_chart_layout(fig: go.Figure, height: int = 350) -> go.Figure:
    """Apply Holafly + Intercom flat editorial Plotly styling (#ffffff plot, #f1eee9 gridlines)."""
    fig.update_layout(
        height=height,
        paper_bgcolor=COLORS["pure_white"],
        plot_bgcolor=COLORS["pure_white"],
        font=dict(family="Inter, sans-serif", color=COLORS["ink"], size=12.5),
        margin=dict(l=18, r=24, t=42, b=28),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.03,
            xanchor="left",
            x=0,
            bgcolor="rgba(255,255,255,0.92)",
            font=dict(size=12, color=COLORS["iron"]),
        ),
        xaxis=dict(
            gridcolor=COLORS["linen"],
            linecolor=COLORS["hairline"],
            tickfont=dict(size=11.5, color=COLORS["iron"]),
            automargin=True,
        ),
        yaxis=dict(
            gridcolor=COLORS["linen"],
            linecolor=COLORS["hairline"],
            tickfont=dict(size=11.5, color=COLORS["iron"]),
            automargin=True,
        ),
    )
    return fig


def _render_sidebar() -> dict:
    with st.sidebar:
        st.markdown('<div class="sidebar-eyebrow">OPERATIONS CONTROL</div>', unsafe_allow_html=True)

        scenario_keys = list(SCENARIO_MODES.keys())
        current_idx = scenario_keys.index(st.session_state["active_scenario"])
        selected_scenario = st.selectbox(
            "Operational Scenario Mode",
            options=scenario_keys,
            index=current_idx,
            format_func=lambda k: SCENARIO_MODES[k],
            help="Switch between the default live stream (active mid-shift drop) and baseline/surge test scenarios.",
        )

        if selected_scenario != st.session_state["active_scenario"]:
            st.session_state["active_scenario"] = selected_scenario
            initialize_or_reset_db(db_path=DB_PATH, scenario_mode=selected_scenario)
            st.session_state["last_manual_batch_msg"] = f"Loaded: {SCENARIO_MODES[selected_scenario]}"

        tz_label = st.selectbox("Display Timezone", options=list(TIMEZONE_OPTIONS.keys()), index=0)
        tz_offset = TIMEZONE_OPTIONS[tz_label]
        tz_short = tz_label.split(" ")[0]

        window_option = st.selectbox(
            "Time Window",
            options=[
                "Last 8 Hours (Default Operational View)",
                "Last 24 Hours (Full 3-Shift Cycle)",
                "Current Active Shift Only",
                "Last 2 Hours (Tactical Zoom)",
            ],
            index=0,
        )

        if st.button("Simulate +2m Batch", width="stretch", type="primary"):
            added = inject_manual_micro_batch(db_path=DB_PATH, scenario_mode=st.session_state["active_scenario"])
            st.session_state["last_manual_batch_msg"] = f"Injected +{added} raw events at UTC NOW()."

        if st.button("Reset Baseline", width="stretch", type="secondary"):
            initialize_or_reset_db(db_path=DB_PATH, scenario_mode=st.session_state["active_scenario"])
            st.session_state["last_manual_batch_msg"] = "Database rebuilt to deterministic rolling state."

        if st.session_state["last_manual_batch_msg"]:
            st.caption(f"Status: {st.session_state['last_manual_batch_msg']}")

        st.divider()

        with st.expander("Dimension Filters (Shift, Market, Language, Agent)", expanded=False):
            shift_options = list(SHIFTS.keys())
            selected_shifts = st.multiselect(
                "Shift",
                options=shift_options,
                default=shift_options,
                format_func=lambda s: SHIFTS[s]["short_name"],
            )
            selected_markets = st.multiselect(
                "Market",
                options=list(VALID_MARKETS),
                default=list(VALID_MARKETS),
            )
            selected_languages = st.multiselect(
                "Language",
                options=list(VALID_LANGUAGES),
                default=list(VALID_LANGUAGES),
            )
            all_agent_names = [a["agent_name"] for a in AGENTS]
            selected_agents = st.multiselect(
                "Agent",
                options=all_agent_names,
                default=all_agent_names,
            )

        st.divider()
        st.caption(
            "Auto-Refresh Engine: Active (60s UI fragment + 2m deterministic stream sync). "
            "Target SLA: <= 10 minutes."
        )

    return {
        "scenario": st.session_state["active_scenario"],
        "tz_label": tz_label,
        "tz_offset": tz_offset,
        "tz_short": tz_short,
        "window_option": window_option,
        "shifts": selected_shifts,
        "markets": selected_markets,
        "languages": selected_languages,
        "agents": selected_agents,
    }


@st.fragment(run_every="60s")
def render_live_cockpit(filters: dict) -> None:
    """Auto-refreshing live cockpit executing every 60 seconds without full-page flicker."""
    now_utc = datetime.now(timezone.utc)
    _ensure_db_ready(filters["scenario"])

    until_utc_str: str | None = None
    if filters["window_option"].startswith("Last 8 Hours"):
        since_dt = now_utc - timedelta(hours=8)
    elif filters["window_option"].startswith("Last 24 Hours"):
        since_dt = now_utc - timedelta(hours=24)
    elif filters["window_option"].startswith("Last 2 Hours"):
        since_dt = now_utc - timedelta(hours=2)
    else:
        shift_start_utc, shift_end_utc, _ = get_current_shift_bounds_utc(now_utc)
        since_dt = shift_start_utc
        until_utc_str = shift_end_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    since_utc_str = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    df_valid_all = load_valid_sales(db_path=DB_PATH)
    df_quarantine_window = load_quarantined_orders(db_path=DB_PATH, since_utc=since_utc_str)
    if until_utc_str and not df_quarantine_window.empty:
        df_quarantine_window = df_quarantine_window[
            df_quarantine_window["event_timestamp_utc"] < until_utc_str
        ]
    health = compute_pipeline_health(db_path=DB_PATH, since_utc=since_utc_str, reference_now_utc=now_utc)

    dim_mask_all = (
        df_valid_all["shift_id"].isin(filters["shifts"])
        & df_valid_all["market"].isin(filters["markets"])
        & df_valid_all["language"].isin(filters["languages"])
        & df_valid_all["agent_name"].isin(filters["agents"])
    )
    df_filtered_all = df_valid_all.loc[dim_mask_all].copy()
    time_mask = df_filtered_all["event_timestamp_utc"] >= since_utc_str
    if until_utc_str:
        time_mask = time_mask & (df_filtered_all["event_timestamp_utc"] < until_utc_str)
    df_valid = df_filtered_all.loc[time_mask].copy()

    anomaly = evaluate_anomaly_status(df_filtered_all, reference_now_utc=now_utc)
    kpis = compute_executive_kpis(df_valid)

    # Compact 1-Row Pipeline Telemetry Strip (Flattened HTML — Zero Truncation)
    last_ing_full = _format_ts_local(health["last_ingested_utc"], filters["tz_offset"], filters["tz_short"])
    last_ing_time = last_ing_full.split(" ")[1] + f" {filters['tz_short']}" if " " in last_ing_full else last_ing_full
    sla_cls = "sla-pass" if health["sla_pass"] else "sla-fail"
    sla_txt = "SLA <= 10m PASS" if health["sla_pass"] else "SLA BREACH"

    telemetry_html = (
        '<div class="telemetry-strip">'
        f'<div class="tele-item"><span class="tele-label">Last Ingested</span>'
        f'<span class="tele-value">{html.escape(last_ing_time)} <span class="tele-sub">({health["raw_count"]:,} raw)</span></span></div>'
        f'<div class="tele-item"><span class="tele-label">Freshness Lag</span>'
        f'<span class="tele-value">{html.escape(health["freshness_lag_display"])}<span class="sla-tag {sla_cls}">{sla_txt}</span></span></div>'
        f'<div class="tele-item"><span class="tele-label">Valid Sales</span>'
        f'<span class="tele-value">{health["valid_count"]:,} <span class="tele-sub">({health["valid_rate_pct"]:.1f}% clean)</span></span></div>'
        f'<div class="tele-item"><span class="tele-label">Excluded Duplicates</span>'
        f'<span class="tele-value">{health["duplicate_count"]:,} <span class="tele-sub">ROW_NUMBER()=1</span></span></div>'
        f'<div class="tele-item"><span class="tele-label">Excluded Refunds / Test</span>'
        f'<span class="tele-value">{health["excluded_invalid_test"]:,} <span class="tele-sub">Amt&lt;=0: {health["invalid_amount_count"]} / QA: {health["test_email_count"]} / Dim: {health["missing_dimension_count"]}</span></span></div>'
        "</div>"
    )
    st.markdown(telemetry_html, unsafe_allow_html=True)

    # Restrained Editorial Alert Card
    border_c, tag_bg, tag_fg = _alert_styles(anomaly["state"])
    alert_html = (
        f'<div class="alert-card" style="border-left-color: {border_c};">'
        f'<span class="alert-tag" style="background-color: {tag_bg}; color: {tag_fg};">[{html.escape(anomaly["state"])}]</span>'
        f'<span class="alert-msg">{html.escape(anomaly["message"])}</span>'
        "</div>"
    )
    st.markdown(alert_html, unsafe_allow_html=True)

    # Clean Horizontal Underline Tabs (Intercom Editorial)
    tab_mgr, tab_coord, tab_agent, tab_dq = st.tabs([
        "Sales Manager View",
        "Coordinator View (Workforce & Capacity)",
        "Agent View (Leaderboard & Live Feed)",
        "Data Quality & SQL Audit",
    ])

    # =========================================================================
    # TAB 1: SALES MANAGER VIEW
    # =========================================================================
    with tab_mgr:
        delta_tone = "neg" if anomaly["delta_pct"] <= -20.0 else "pos" if anomaly["delta_pct"] >= 20.0 else "neutral"
        _render_kpi_grid([
            {
                "label": "Total Net Revenue",
                "value": f"${kpis['total_revenue_usd']:,.2f}",
                "delta": f"Last 30m: ${anomaly['current_revenue_30m']:,.2f}",
                "tone": "neutral",
            },
            {
                "label": "Valid Orders",
                "value": f"{kpis['valid_orders_count']:,}",
                "delta": f"{anomaly['delta_pct']:+.1f}% vs 3h baseline ({anomaly['current_orders_30m']} vs {anomaly['baseline_mean_orders_30m']:.1f})",
                "tone": delta_tone,
            },
            {
                "label": "Average Order Value",
                "value": f"${kpis['aov_usd']:,.2f}",
                "delta": "Net paid USD per valid sale",
                "tone": "neutral",
            },
            {
                "label": "Discount Penetration",
                "value": f"{kpis['discount_penetration_pct']:.1f}%",
                "delta": "Share of orders with promo code",
                "tone": "neutral",
            },
            {
                "label": "Revenue / Shift Hour",
                "value": f"${kpis['revenue_per_shift_hour_usd']:,.0f}/hr",
                "delta": f"Across {kpis['elapsed_hours']:.1f}h active span",
                "tone": "neutral",
            },
        ])

        ts_10m = compute_timeseries_10m(df_valid, tz_offset_hours=filters["tz_offset"])
        if not ts_10m.empty:
            _render_section_header(
                f"LIVE VELOCITY TELEMETRY · 10-MIN INTERVALS ({filters['tz_short']})",
                "Real-Time Sales Velocity & Expected Baseline Band",
            )
            mu_10m = anomaly["baseline_mean_orders_30m"] / 3.0
            sd_10m = anomaly["baseline_std_orders_30m"] / 1.732
            upper_band = round(mu_10m + 1.5 * sd_10m, 2)
            lower_band = max(0.0, round(mu_10m - 1.5 * sd_10m, 2))

            fig_ts = go.Figure()
            fig_ts.add_trace(go.Scatter(
                x=list(ts_10m["bucket_local"]) + list(ts_10m["bucket_local"])[::-1],
                y=[upper_band] * len(ts_10m) + [lower_band] * len(ts_10m),
                fill="toself",
                fillcolor="rgba(211, 206, 198, 0.28)",
                line=dict(color="rgba(255,255,255,0)"),
                hoverinfo="skip",
                name=f"Expected Baseline Band ({lower_band:.1f} to {upper_band:.1f} ord/10m)",
            ))
            fig_ts.add_trace(go.Bar(
                x=ts_10m["bucket_local"],
                y=ts_10m["revenue_usd"],
                name="Net Revenue ($ USD)",
                marker_color="rgba(222, 219, 214, 0.65)",
                marker_line_width=0,
                yaxis="y2",
            ))
            point_colors = [
                COLORS["holafly_red"] if tag == "DROP_ANOMALY"
                else COLORS["forest_ok"] if tag == "SURGE_CAMPAIGN"
                else COLORS["ink"]
                for tag in ts_10m["scenario_tag"]
            ]
            fig_ts.add_trace(go.Scatter(
                x=ts_10m["bucket_local"],
                y=ts_10m["valid_orders"],
                mode="lines+markers",
                name="Valid Orders / 10m",
                line=dict(color=COLORS["ink"], width=2.2),
                marker=dict(size=6.5, color=point_colors, line=dict(width=1, color=COLORS["pure_white"])),
            ))
            fig_ts.add_hline(
                y=mu_10m,
                line_dash="dot",
                line_color=COLORS["graphite"],
                annotation_text=f"3h Baseline Mean ({mu_10m:.1f} ord/10m)",
                annotation_position="top left",
                annotation_font=dict(size=11, color=COLORS["iron"]),
            )
            _apply_editorial_chart_layout(fig_ts, height=365)
            fig_ts.update_layout(
                hovermode="x unified",
                yaxis=dict(title="Valid Orders / 10m", rangemode="tozero", gridcolor=COLORS["linen"]),
                yaxis2=dict(
                    title="Net Revenue ($ USD)",
                    overlaying="y",
                    side="right",
                    showgrid=False,
                    rangemode="tozero",
                    tickprefix="$",
                    tickfont=dict(size=11.5, color=COLORS["iron"]),
                ),
            )
            st.plotly_chart(fig_ts, width="stretch")

        c_left, c_right = st.columns([1.25, 1.0], gap="large")
        with c_left:
            _render_section_header("MARKET ATTRIBUTION", "30-Min Pacing vs. 3-Hour Baseline by Market")
            mkt_df = compute_market_pacing_table(df_filtered_all)
            if not mkt_df.empty:
                bar_colors = [
                    COLORS["holafly_red"] if v <= -20.0
                    else COLORS["forest_ok"] if v >= 15.0
                    else COLORS["ink"]
                    for v in mkt_df["30m Trend %"]
                ]
                fig_mkt = go.Figure(go.Bar(
                    x=mkt_df["Market"],
                    y=mkt_df["30m Trend %"],
                    marker_color=bar_colors,
                    text=[f"{v:+.1f}%" for v in mkt_df["30m Trend %"]],
                    textposition="outside",
                    cliponaxis=False,
                ))
                _apply_editorial_chart_layout(fig_mkt, height=255)
                fig_mkt.update_layout(
                    showlegend=False,
                    yaxis=dict(title="30m Trend (%)", zeroline=True, zerolinecolor=COLORS["hairline"]),
                    margin=dict(l=18, r=18, t=24, b=28),
                )
                st.plotly_chart(fig_mkt, width="stretch")
                st.dataframe(mkt_df, width="stretch", hide_index=True)

        with c_right:
            _render_section_header("PROMO MIX", "Discount Code Revenue & Margin Share")
            disc_df = compute_discount_breakdown(df_valid)
            if not disc_df.empty:
                disc_sorted = disc_df.sort_values("Net Revenue ($)", ascending=True)
                fig_disc = px.bar(
                    disc_sorted,
                    x="Net Revenue ($)",
                    y="Discount Code",
                    orientation="h",
                    text="Order Share %",
                )
                fig_disc.update_traces(
                    texttemplate="%{text:.1f}%",
                    textposition="outside",
                    cliponaxis=False,
                    marker_color=[
                        COLORS["holafly_red"] if code != "NONE" else COLORS["ink"]
                        for code in disc_sorted["Discount Code"]
                    ],
                )
                _apply_editorial_chart_layout(fig_disc, height=255)
                fig_disc.update_layout(
                    showlegend=False,
                    xaxis=dict(title="Net Revenue ($ USD)", tickprefix="$"),
                    yaxis=dict(title=""),
                    margin=dict(l=18, r=48, t=24, b=28),
                )
                st.plotly_chart(fig_disc, width="stretch")
                st.dataframe(disc_df, width="stretch", hide_index=True)

    # =========================================================================
    # TAB 2: COORDINATOR VIEW (WORKFORCE & CAPACITY)
    # =========================================================================
    with tab_coord:
        cap_df = compute_market_language_capacity(df_valid)
        if not cap_df.empty:
            overloaded_cnt = int((cap_df["Capacity Status"] == "OVERLOADED").sum())
            drop_cnt = int((cap_df["Capacity Status"] == "DROP ALERT").sum())
            under_cnt = int((cap_df["Capacity Status"] == "UNDER-UTILIZED").sum())
            active_agents_cnt = int(df_valid["agent_name"].nunique())
            avg_ord_hr = round(float(cap_df["Orders / Agent-Hr"].mean()), 2)

            _render_kpi_grid([
                {
                    "label": "Active Agents",
                    "value": f"{active_agents_cnt} / 15",
                    "delta": "Handling valid sales in window",
                    "tone": "neutral",
                },
                {
                    "label": "Avg Orders / Agent-Hr",
                    "value": f"{avg_ord_hr:.2f}",
                    "delta": f"Target benchmark: {TARGET_ORDERS_PER_AGENT_HOUR:.2f}/hr",
                    "tone": "neutral",
                },
                {
                    "label": "Queues Needing Action",
                    "value": f"{overloaded_cnt + drop_cnt}",
                    "delta": f"Overloaded: {overloaded_cnt} | Drop Alerts: {drop_cnt}",
                    "tone": "neg" if (overloaded_cnt + drop_cnt) > 0 else "pos",
                },
                {
                    "label": "Flex Capacity Available",
                    "value": f"{under_cnt} queues",
                    "delta": "Utilization < 70% (reallocate out)",
                    "tone": "pos" if under_cnt > 0 else "neutral",
                },
            ])

            col_hm, col_act = st.columns([1.0, 1.35], gap="large")
            with col_hm:
                _render_section_header("WORKFORCE HEATMAP", "Market x Language Capacity Matrix")
                hm_metric = st.radio(
                    "Matrix Metric",
                    options=["Utilization %", "Valid Orders", "Net Revenue ($)"],
                    horizontal=True,
                )
                piv = cap_df.pivot(index="Market", columns="Language", values=hm_metric).fillna(0)
                color_scale = (
                    [[0.0, "#f1eee9"], [0.45, "#ecfdf3"], [0.75, "#fef3c7"], [1.0, "#e63946"]]
                    if hm_metric == "Utilization %"
                    else [[0.0, "#faf9f6"], [0.5, "#d3cec6"], [1.0, "#111111"]]
                )
                fig_hm = px.imshow(
                    piv,
                    text_auto=".1f" if hm_metric == "Utilization %" else ".0f",
                    color_continuous_scale=color_scale,
                    aspect="auto",
                )
                _apply_editorial_chart_layout(fig_hm, height=340)
                fig_hm.update_layout(margin=dict(l=14, r=14, t=18, b=18), coloraxis_showscale=False)
                st.plotly_chart(fig_hm, width="stretch")

            with col_act:
                _render_section_header("INTRASHIFT REALLOCATION", "Live Staffing Action Queue")
                st.dataframe(
                    cap_df[[
                        "Market", "Language", "Valid Orders", "Active Agents",
                        "Orders / Agent-Hr", "Utilization %", "Last 30m Trend %",
                        "Capacity Status", "Recommended Coordinator Action",
                    ]],
                    width="stretch",
                    hide_index=True,
                    height=390,
                )

            _render_section_header("SHIFT COVERAGE", "Agent x Shift Market Breakdown")
            agent_mkt_piv = pd.pivot_table(
                df_valid,
                index=["shift_name", "agent_name"],
                columns="market",
                values="order_id",
                aggfunc="count",
                fill_value=0,
                margins=True,
                margins_name="Total",
            ).reset_index().rename(columns={"shift_name": "Shift", "agent_name": "Agent"})
            st.dataframe(agent_mkt_piv, width="stretch", hide_index=True)
        else:
            st.info("No valid orders match the current filter criteria.")

    # =========================================================================
    # TAB 3: AGENT VIEW (LEADERBOARD & LIVE ORDER FEED)
    # =========================================================================
    with tab_agent:
        lb_df = compute_agent_leaderboard(df_valid)
        if not lb_df.empty:
            _render_section_header("SHIFT PERFORMANCE", "Agent Leaderboard & Pace vs. Shift Average")
            col_bar, col_tbl = st.columns([1.0, 1.45], gap="large")
            with col_bar:
                sorted_lb = lb_df.sort_values("Net Revenue ($)", ascending=True)
                fig_lb = px.bar(
                    sorted_lb,
                    x="Net Revenue ($)",
                    y="Agent Name",
                    color="Status",
                    orientation="h",
                    color_discrete_map={
                        "TOP CLOSER": COLORS["forest_ok"],
                        "ON PACE": COLORS["ink"],
                        "NEEDS COACHING": COLORS["holafly_red"],
                    },
                    text="Pace vs Shift Avg (%)",
                )
                fig_lb.update_traces(texttemplate="%{text:+.1f}%", textposition="outside", cliponaxis=False)
                _apply_editorial_chart_layout(fig_lb, height=440)
                fig_lb.update_layout(
                    xaxis=dict(title="Net Revenue ($ USD)", tickprefix="$"),
                    yaxis=dict(title=""),
                    margin=dict(l=14, r=52, t=40, b=24),
                )
                st.plotly_chart(fig_lb, width="stretch")

            with col_tbl:
                st.dataframe(lb_df, width="stretch", hide_index=True, height=440)

            _render_section_header(
                f"REAL-TIME STREAM ({filters['tz_short']})",
                "Latest 25 Confirmed Valid Sales",
            )
            latest_df = df_valid.sort_values("event_timestamp_utc", ascending=False).head(25).copy()
            latest_df["Local Time"] = latest_df["event_timestamp_utc"].apply(
                lambda x: _format_ts_local(x, filters["tz_offset"], filters["tz_short"])
            )
            ev_ts = pd.to_datetime(latest_df["event_timestamp_utc"], utc=True)
            ing_ts = pd.to_datetime(latest_df["ingested_at_utc"], utc=True)
            latest_df["Ingest Lag (s)"] = (ing_ts - ev_ts).dt.total_seconds().astype(int)

            st.dataframe(
                latest_df[[
                    "Local Time", "order_id", "agent_name", "market", "language",
                    "discount_code", "amount_usd", "customer_email", "Ingest Lag (s)",
                ]].rename(columns={
                    "order_id": "Order ID",
                    "agent_name": "Agent",
                    "market": "Market",
                    "language": "Language",
                    "discount_code": "Discount Code",
                    "amount_usd": "Net Amount ($)",
                    "customer_email": "Customer Email (Fake)",
                }),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No valid orders match the current filter criteria.")

    # =========================================================================
    # TAB 4: DATA QUALITY & SQL AUDIT VIEW
    # =========================================================================
    with tab_dq:
        _render_section_header("WHAT COUNTS AS A SALE", "4-Gate SQL Data Quality Reconciliation Funnel")
        funnel_rows = [
            {"Pipeline Stage": "1. Raw Events Received (raw_orders)", "Records": health["raw_count"], "Share of Raw %": 100.0, "Rule": "All incoming webhook and retry events"},
            {"Pipeline Stage": "2. Excluded: Missing Required Dimensions", "Records": -health["missing_dimension_count"], "Share of Raw %": round(health["missing_dimension_count"] / max(1, health["raw_count"]) * 100, 2), "Rule": "Null/empty Order ID, Agent, Market, or Language"},
            {"Pipeline Stage": "3. Excluded: Internal QA / Test Emails", "Records": -health["test_email_count"], "Share of Raw %": round(health["test_email_count"] / max(1, health["raw_count"]) * 100, 2), "Rule": "@holafly.internal, @staging.holafly.com, @testmail.invalid, qa.*, test_*, loadtest.*"},
            {"Pipeline Stage": "4. Excluded: Zero / Negative Amounts (Refunds & Failed Captures)", "Records": -health["invalid_amount_count"], "Share of Raw %": round(health["invalid_amount_count"] / max(1, health["raw_count"]) * 100, 2), "Rule": "Amount <= $0.00 USD (any positive amount > $0.00 is valid, no upper cap)"},
            {"Pipeline Stage": "5. Excluded: Duplicate Order ID Retries", "Records": -health["duplicate_count"], "Share of Raw %": round(health["duplicate_count"] / max(1, health["raw_count"]) * 100, 2), "Rule": "ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY ingested_at_utc ASC) > 1"},
            {"Pipeline Stage": "6. Final Valid Sales (v_valid_sales)", "Records": health["valid_count"], "Share of Raw %": health["valid_rate_pct"], "Rule": f"Conservation Check: {'PASS (Delta = 0)' if health['reconciled'] else 'FAIL'}"},
        ]
        st.dataframe(pd.DataFrame(funnel_rows), width="stretch", hide_index=True)

        _render_section_header("QUARANTINE INSPECTOR", "Excluded Records Audit Log (v_quarantined_orders)")
        if not df_quarantine_window.empty:
            dq_filter = st.multiselect(
                "Filter Quarantine Status",
                options=sorted(df_quarantine_window["dq_status"].unique().tolist()),
                default=sorted(df_quarantine_window["dq_status"].unique().tolist()),
            )
            q_view = df_quarantine_window[df_quarantine_window["dq_status"].isin(dq_filter)]
            st.dataframe(
                q_view[[
                    "raw_event_id", "event_timestamp_utc", "order_id", "agent_name",
                    "market", "language", "customer_email", "amount_usd",
                    "occurrence_rank", "dq_status", "dq_reason",
                ]].head(100),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("Zero quarantined records in the selected window.")

        with st.expander("View Formal SQL Definition (sql/views.sql) & Production BigQuery Mapping"):
            st.markdown(
                """
                **Production Mapping at Holafly (Replacing 3-5h Looker Studio Lag with <= 2-Min Streaming):**
                1. **Ingestion:** Stripe/Checkout + Intercom Webhooks -> Pub/Sub -> **BigQuery Storage Write API (Streaming Inserts)** into partitioned `holafly_prod.raw.orders_stream`.
                2. **Transformation:** Incremental **BigQuery Materialized View / 2-Min Scheduled Query** scanning only the trailing 24h partition with `QUALIFY ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY ingested_at_utc ASC) = 1` and `amount_usd > 0.00`.
                3. **Serving:** Looker Studio backed by **BigQuery BI Engine** or this Cloud Run tactical cockpit refreshing every 60 seconds.
                """
            )
            st.code(SQL_VIEWS_PATH.read_text(encoding="utf-8"), language="sql")


def main() -> None:
    _ensure_session_defaults()
    logo_uri = _load_logo_data_uri()
    logo_html = (
        f'<div class="hf-logo-wrap"><img src="{logo_uri}" alt="Holafly" /></div>'
        if logo_uri
        else ""
    )
    header_html = (
        '<div class="hf-header">'
        '<div class="hf-brand-row">'
        f"{logo_html}"
        '<div class="hf-title-block">'
        '<span class="hf-eyebrow">HOLAFLY CONVERSATIONAL COMMERCE · LIVE TELEMETRY</span>'
        '<h1 class="hf-title">Real-Time Sales Tracker — Conversational Commerce</h1>'
        "</div>"
        "</div>"
        '<div class="hf-meta-badge">SLA TARGET &lt;= 10M · REFRESH 60S</div>'
        "</div>"
    )
    st.markdown(header_html, unsafe_allow_html=True)
    filters = _render_sidebar()
    render_live_cockpit(filters)


if __name__ == "__main__":
    main()
