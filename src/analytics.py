"""Analytics, Workforce Capacity, Shift Pace & Anomaly Detection Engine."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import (
    AGENT_LOOKUP,
    BASELINE_WINDOW_MINUTES,
    CRITICAL_DROP_PCT,
    CRITICAL_DROP_Z,
    CRITICAL_DROP_Z_PCT_GUARD,
    CURRENT_WINDOW_MINUTES,
    DB_PATH,
    MIN_BASELINE_ORDERS_30M,
    SHIFTS,
    SLA_MAX_LATENCY_MINUTES,
    SURGE_PCT,
    SURGE_Z,
    SURGE_Z_PCT_GUARD,
    TARGET_ORDERS_PER_AGENT_HOUR,
    UTILIZATION_OVERLOADED_PCT,
    UTILIZATION_UNDERUTILIZED_PCT,
    WARNING_DROP_PCT,
    WARNING_DROP_Z,
    WARNING_DROP_Z_PCT_GUARD,
)
from src.db import get_connection


def compute_pipeline_health(
    db_path: Path | str = DB_PATH,
    since_utc: str | None = None,
    reference_now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Compute Data Quality reconciliation counters and Freshness Lag against the 10m SLA."""
    now_utc = reference_now_utc or datetime.now(timezone.utc)
    where_clause = "WHERE event_timestamp_utc >= ?" if since_utc else ""
    params = (since_utc,) if since_utc else ()

    sql = f"""
        SELECT
            COUNT(*) AS raw_count,
            SUM(CASE WHEN dq_status = 'VALID' THEN 1 ELSE 0 END) AS valid_count,
            SUM(CASE WHEN dq_status = 'DUPLICATE' THEN 1 ELSE 0 END) AS duplicate_count,
            SUM(CASE WHEN dq_status = 'INVALID_AMOUNT' THEN 1 ELSE 0 END) AS invalid_amount_count,
            SUM(CASE WHEN dq_status = 'TEST_EMAIL' THEN 1 ELSE 0 END) AS test_email_count,
            SUM(CASE WHEN dq_status = 'MISSING_DIMENSION' THEN 1 ELSE 0 END) AS missing_dimension_count,
            MAX(ingested_at_utc) AS last_ingested_utc,
            MAX(event_timestamp_utc) AS last_event_utc
        FROM v_classified_orders
        {where_clause};
    """
    with get_connection(db_path) as conn:
        row = conn.execute(sql, params).fetchone()

    raw_count = int(row["raw_count"] or 0)
    valid_count = int(row["valid_count"] or 0)
    duplicate_count = int(row["duplicate_count"] or 0)
    invalid_amount_count = int(row["invalid_amount_count"] or 0)
    test_email_count = int(row["test_email_count"] or 0)
    missing_dimension_count = int(row["missing_dimension_count"] or 0)
    excluded_invalid_test = invalid_amount_count + test_email_count + missing_dimension_count

    last_ingested_utc = row["last_ingested_utc"]
    last_event_utc = row["last_event_utc"]
    if last_ingested_utc:
        last_dt = datetime.strptime(last_ingested_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        lag_seconds = max(0.0, (now_utc - last_dt).total_seconds())
    else:
        lag_seconds = 0.0

    lag_minutes = round(lag_seconds / 60.0, 2)
    lag_mm = int(lag_seconds // 60)
    lag_ss = int(lag_seconds % 60)

    return {
        "raw_count": raw_count,
        "valid_count": valid_count,
        "duplicate_count": duplicate_count,
        "invalid_amount_count": invalid_amount_count,
        "test_email_count": test_email_count,
        "missing_dimension_count": missing_dimension_count,
        "excluded_invalid_test": excluded_invalid_test,
        "reconciled": raw_count == (valid_count + duplicate_count + excluded_invalid_test),
        "valid_rate_pct": round((valid_count / raw_count) * 100.0, 1) if raw_count else 0.0,
        "last_ingested_utc": last_ingested_utc,
        "last_event_utc": last_event_utc,
        "freshness_lag_seconds": round(lag_seconds, 1),
        "freshness_lag_minutes": lag_minutes,
        "freshness_lag_display": f"{lag_mm}m {lag_ss:02d}s",
        "sla_pass": lag_minutes <= SLA_MAX_LATENCY_MINUTES,
    }


def get_current_shift_bounds_utc(
    now_utc: datetime | None = None,
) -> tuple[datetime, datetime, str]:
    """Return (shift_start_utc, shift_end_utc, shift_id) using full UTC timestamps.

    Properly handles midnight-crossing SHIFT_3_NIGHT (22:00 prev day COT -> 06:00 COT)
    without splitting pre-midnight and post-midnight records.
    """
    ref_utc = (now_utc or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_cot = ref_utc - timedelta(hours=5)
    hour_cot = now_cot.hour

    if 6 <= hour_cot < 14:
        shift_id = "SHIFT_1_MORNING"
        start_cot = now_cot.replace(hour=6, minute=0, second=0, microsecond=0)
    elif 14 <= hour_cot < 22:
        shift_id = "SHIFT_2_AFTERNOON"
        start_cot = now_cot.replace(hour=14, minute=0, second=0, microsecond=0)
    else:
        shift_id = "SHIFT_3_NIGHT"
        if hour_cot >= 22:
            start_cot = now_cot.replace(hour=22, minute=0, second=0, microsecond=0)
        else:
            start_cot = (now_cot - timedelta(days=1)).replace(hour=22, minute=0, second=0, microsecond=0)

    end_cot = start_cot + timedelta(hours=8)
    start_utc = (start_cot + timedelta(hours=5)).replace(tzinfo=timezone.utc)
    end_utc = (end_cot + timedelta(hours=5)).replace(tzinfo=timezone.utc)
    return start_utc, end_utc, shift_id


def compute_elapsed_hours(df_valid: pd.DataFrame) -> float:
    """Compute elapsed hours spanned by the valid sales dataframe (floored at 0.5h)."""
    if df_valid.empty:
        return 0.5
    ts = pd.to_datetime(df_valid["event_timestamp_utc"], utc=True)
    span_hours = (ts.max() - ts.min()).total_seconds() / 3600.0
    return max(0.5, span_hours)


def compute_executive_kpis(df_valid: pd.DataFrame) -> dict[str, Any]:
    """Compute core Sales Manager KPIs strictly over valid_sales."""
    if df_valid.empty:
        return {
            "total_revenue_usd": 0.00,
            "valid_orders_count": 0,
            "aov_usd": 0.00,
            "discount_penetration_pct": 0.0,
            "revenue_per_shift_hour_usd": 0.00,
            "elapsed_hours": 0.5,
        }

    valid_orders = int(len(df_valid))
    total_revenue = round(float(df_valid["amount_usd"].sum()), 2)
    aov = round(total_revenue / valid_orders, 2) if valid_orders > 0 else 0.00
    discounted_orders = int(df_valid["is_discounted"].sum())
    discount_penetration_pct = round((discounted_orders / valid_orders) * 100.0, 1) if valid_orders > 0 else 0.0
    elapsed_hours = compute_elapsed_hours(df_valid)
    rev_per_hour = round(total_revenue / elapsed_hours, 2)

    return {
        "total_revenue_usd": total_revenue,
        "valid_orders_count": valid_orders,
        "aov_usd": aov,
        "discount_penetration_pct": discount_penetration_pct,
        "revenue_per_shift_hour_usd": rev_per_hour,
        "elapsed_hours": round(elapsed_hours, 2),
    }


def evaluate_anomaly_status(
    df_valid: pd.DataFrame,
    reference_now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Compare latest 30m valid orders against trailing 180m (6x30m) baseline.

    Applies min-sample guard (mu_base >= 10.0) to prevent false alarms on small slices.
    """
    if df_valid.empty:
        return {
            "state": "NORMAL",
            "sufficient_sample": False,
            "current_orders_30m": 0,
            "current_revenue_30m": 0.0,
            "baseline_mean_orders_30m": 0.0,
            "baseline_std_orders_30m": 2.0,
            "baseline_mean_revenue_30m": 0.0,
            "delta_pct": 0.0,
            "z_score": 0.0,
            "worst_markets": [],
            "top_promo": "NONE",
            "message": "No valid orders in active filter scope to evaluate anomaly detection.",
        }

    ts = pd.to_datetime(df_valid["event_timestamp_utc"], utc=True)
    t_max = pd.Timestamp(reference_now_utc).tz_convert("UTC") if reference_now_utc else ts.max()
    # Anchor to the latest actual data point if reference_now_utc is slightly ahead
    if ts.max() > t_max:
        t_max = ts.max()

    curr_start = t_max - pd.Timedelta(minutes=CURRENT_WINDOW_MINUTES)
    base_start = curr_start - pd.Timedelta(minutes=BASELINE_WINDOW_MINUTES)

    curr_mask = (ts > curr_start) & (ts <= t_max)
    df_curr = df_valid.loc[curr_mask]
    current_orders = int(len(df_curr))
    current_revenue = round(float(df_curr["amount_usd"].sum()), 2)

    # Partition baseline [base_start, curr_start] into 6 non-overlapping 30-min intervals
    bucket_counts: list[int] = []
    bucket_revenues: list[float] = []
    for k in range(6):
        w_start = base_start + pd.Timedelta(minutes=k * CURRENT_WINDOW_MINUTES)
        w_end = w_start + pd.Timedelta(minutes=CURRENT_WINDOW_MINUTES)
        w_mask = (ts > w_start) & (ts <= w_end)
        bucket_counts.append(int(w_mask.sum()))
        bucket_revenues.append(float(df_valid.loc[w_mask, "amount_usd"].sum()))

    mu_base = sum(bucket_counts) / 6.0
    mu_rev_base = sum(bucket_revenues) / 6.0
    variance = sum((b - mu_base) ** 2 for b in bucket_counts) / 5.0
    sigma_base = max(math.sqrt(variance), 2.0, 0.10 * mu_base)

    # Identify worst dropping markets in current 30m vs baseline 30m average
    base_df = df_valid.loc[(ts > base_start) & (ts <= curr_start)]
    market_deltas: list[tuple[str, float]] = []
    for mkt in df_valid["market"].unique():
        m_base = float((base_df["market"] == mkt).sum()) / 6.0
        m_curr = float((df_curr["market"] == mkt).sum())
        if m_base >= 2.0:
            m_delta = ((m_curr - m_base) / m_base) * 100.0
            market_deltas.append((str(mkt), round(m_delta, 1)))
    market_deltas.sort(key=lambda x: x[1])
    worst_markets = [f"{m} ({d:+.0f}%)" for m, d in market_deltas[:2] if d < -15.0]

    # Top promo code in current window
    non_none = df_curr[df_curr["discount_code"] != "NONE"]
    top_promo = str(non_none["discount_code"].mode().iloc[0]) if not non_none.empty else "NONE"

    if mu_base < MIN_BASELINE_ORDERS_30M:
        return {
            "state": "NORMAL",
            "sufficient_sample": False,
            "current_orders_30m": current_orders,
            "current_revenue_30m": current_revenue,
            "baseline_mean_orders_30m": round(mu_base, 1),
            "baseline_std_orders_30m": round(sigma_base, 2),
            "baseline_mean_revenue_30m": round(mu_rev_base, 2),
            "delta_pct": round(((current_orders - mu_base) / mu_base) * 100.0, 1) if mu_base > 0 else 0.0,
            "z_score": round((current_orders - mu_base) / sigma_base, 2),
            "worst_markets": worst_markets,
            "top_promo": top_promo,
            "message": (
                f"NORMAL (INSUFFICIENT SAMPLE FOR ALERT): Trailing 3h baseline is {mu_base:.1f} orders/30m "
                f"(< {MIN_BASELINE_ORDERS_30M:.0f} guard threshold). Alerts suppressed to avoid false positives."
            ),
        }

    delta_pct = round(((current_orders - mu_base) / mu_base) * 100.0, 1)
    z_score = round((current_orders - mu_base) / sigma_base, 2)
    worst_str = ", ".join(worst_markets) if worst_markets else "Global Queue"

    if delta_pct <= CRITICAL_DROP_PCT or (z_score <= CRITICAL_DROP_Z and delta_pct <= CRITICAL_DROP_Z_PCT_GUARD):
        state = "CRITICAL DROP"
        msg = (
            f"CRITICAL SALES DROP: Valid orders in last 30m dropped {abs(delta_pct):.1f}% "
            f"({current_orders} vs {mu_base:.1f} baseline | Z={z_score:+.2f}). "
            f"Inspect top dropping markets ({worst_str}) for Intercom queue saturation or checkout gateway errors."
        )
    elif delta_pct <= WARNING_DROP_PCT or (z_score <= WARNING_DROP_Z and delta_pct <= WARNING_DROP_Z_PCT_GUARD):
        state = "WARNING"
        msg = (
            f"WARNING — PACING SLIP: Valid orders in last 30m are {abs(delta_pct):.1f}% below 3h baseline "
            f"({current_orders} vs {mu_base:.1f} | Z={z_score:+.2f}). Monitor FRT and concurrency in {worst_str}."
        )
    elif delta_pct >= SURGE_PCT or (z_score >= SURGE_Z and delta_pct >= SURGE_Z_PCT_GUARD):
        state = "SURGE"
        msg = (
            f"TRAFFIC & SALES SURGE: Valid orders in last 30m surged +{delta_pct:.1f}% above baseline "
            f"({current_orders} vs {mu_base:.1f} | Z={z_score:+.2f} | Top promo: {top_promo}). "
            f"Flex stand-by agents into peak language queues."
        )
    else:
        state = "NORMAL"
        msg = (
            f"SYSTEM & SHIFT PACING NORMAL: Last 30m sales ({current_orders} orders, ${current_revenue:,.2f}) "
            f"are tracking within expected baseline band ({mu_base:.1f} ± {sigma_base:.1f} orders/30m | Z={z_score:+.2f})."
        )

    return {
        "state": state,
        "sufficient_sample": True,
        "current_orders_30m": current_orders,
        "current_revenue_30m": current_revenue,
        "baseline_mean_orders_30m": round(mu_base, 1),
        "baseline_std_orders_30m": round(sigma_base, 2),
        "baseline_mean_revenue_30m": round(mu_rev_base, 2),
        "delta_pct": delta_pct,
        "z_score": z_score,
        "worst_markets": worst_markets,
        "top_promo": top_promo,
        "message": msg,
    }


def compute_timeseries_10m(df_valid: pd.DataFrame, tz_offset_hours: int = -5) -> pd.DataFrame:
    """Aggregate valid sales into 10-minute buckets in the selected display timezone."""
    if df_valid.empty:
        return pd.DataFrame(columns=["bucket_local", "valid_orders", "revenue_usd", "scenario_tag"])

    work = df_valid.copy()
    ts_local = pd.to_datetime(work["event_timestamp_utc"], utc=True) + pd.Timedelta(hours=tz_offset_hours)
    work["bucket_local"] = ts_local.dt.floor("10min").dt.tz_localize(None)

    agg = (
        work.groupby("bucket_local", as_index=False)
        .agg(
            valid_orders=("order_id", "count"),
            revenue_usd=("amount_usd", "sum"),
            scenario_tag=("scenario_tag", lambda s: s.mode().iloc[0] if not s.empty else "BASELINE"),
        )
        .sort_values("bucket_local")
    )
    agg["revenue_usd"] = agg["revenue_usd"].round(2)
    return agg


def compute_market_pacing_table(df_valid: pd.DataFrame) -> pd.DataFrame:
    """Compute per-market total performance plus last-30m vs trailing-3h baseline trend."""
    if df_valid.empty:
        return pd.DataFrame()

    ts = pd.to_datetime(df_valid["event_timestamp_utc"], utc=True)
    t_max = ts.max()
    curr_start = t_max - pd.Timedelta(minutes=CURRENT_WINDOW_MINUTES)
    base_start = curr_start - pd.Timedelta(minutes=BASELINE_WINDOW_MINUTES)

    curr_df = df_valid.loc[ts > curr_start]
    base_df = df_valid.loc[(ts > base_start) & (ts <= curr_start)]

    rows = []
    for market, grp in df_valid.groupby("market"):
        orders = int(len(grp))
        rev = round(float(grp["amount_usd"].sum()), 2)
        aov = round(rev / orders, 2) if orders else 0.0
        disc_pct = round(float(grp["is_discounted"].mean()) * 100.0, 1) if orders else 0.0

        curr_30m = int((curr_df["market"] == market).sum())
        base_30m = round(float((base_df["market"] == market).sum()) / 6.0, 1)
        trend_pct = round(((curr_30m - base_30m) / base_30m) * 100.0, 1) if base_30m > 0 else 0.0

        rows.append({
            "Market": market,
            "Valid Orders": orders,
            "Net Revenue ($)": rev,
            "AOV ($)": aov,
            "Discount %": disc_pct,
            "Last 30m Orders": curr_30m,
            "3h Baseline / 30m": base_30m,
            "30m Trend %": trend_pct,
        })
    return pd.DataFrame(rows).sort_values("Net Revenue ($)", ascending=False).reset_index(drop=True)


def compute_discount_breakdown(df_valid: pd.DataFrame) -> pd.DataFrame:
    """Compute discount code performance table."""
    if df_valid.empty:
        return pd.DataFrame()
    total_orders = len(df_valid)
    agg = (
        df_valid.groupby("discount_code", as_index=False)
        .agg(
            valid_orders=("order_id", "count"),
            net_revenue_usd=("amount_usd", "sum"),
        )
        .sort_values("net_revenue_usd", ascending=False)
    )
    agg["share_pct"] = (agg["valid_orders"] / total_orders * 100.0).round(1)
    agg["aov_usd"] = (agg["net_revenue_usd"] / agg["valid_orders"]).round(2)
    agg["net_revenue_usd"] = agg["net_revenue_usd"].round(2)
    return agg.rename(columns={
        "discount_code": "Discount Code",
        "valid_orders": "Valid Orders",
        "share_pct": "Order Share %",
        "net_revenue_usd": "Net Revenue ($)",
        "aov_usd": "AOV ($)",
    }).reset_index(drop=True)


def compute_market_language_capacity(df_valid: pd.DataFrame) -> pd.DataFrame:
    """Compute Market x Language workforce utilization & live shift reallocation actions."""
    if df_valid.empty:
        return pd.DataFrame()

    elapsed_hours = compute_elapsed_hours(df_valid)
    ts = pd.to_datetime(df_valid["event_timestamp_utc"], utc=True)
    t_max = ts.max()
    curr_start = t_max - pd.Timedelta(minutes=CURRENT_WINDOW_MINUTES)
    base_start = curr_start - pd.Timedelta(minutes=BASELINE_WINDOW_MINUTES)
    curr_df = df_valid.loc[ts > curr_start]
    base_df = df_valid.loc[(ts > base_start) & (ts <= curr_start)]

    # Compute each agent's effective time share across Market x Language queues so utilization reflects real load
    agent_total_orders = df_valid.groupby("agent_name")["order_id"].count().to_dict()

    rows = []
    for (market, language), grp in df_valid.groupby(["market", "language"]):
        orders = int(len(grp))
        rev = round(float(grp["amount_usd"].sum()), 2)
        active_agents = int(grp["agent_name"].nunique())

        # FTE-equivalent agent share dedicated to this Market x Language segment
        fte_share = 0.0
        for agt, cnt in grp.groupby("agent_name")["order_id"].count().items():
            fte_share += cnt / max(1, agent_total_orders.get(agt, cnt))
        fte_share = max(0.35, round(fte_share, 2))

        orders_per_agent_hr = round(orders / (fte_share * elapsed_hours), 2)
        utilization_pct = round((orders_per_agent_hr / TARGET_ORDERS_PER_AGENT_HOUR) * 100.0, 1)

        curr_30m = int(((curr_df["market"] == market) & (curr_df["language"] == language)).sum())
        base_30m = round(float(((base_df["market"] == market) & (base_df["language"] == language)).sum()) / 6.0, 1)
        trend_30m = round(((curr_30m - base_30m) / base_30m) * 100.0, 1) if base_30m >= 1.0 else 0.0

        if base_30m >= 2.0 and trend_30m <= -35.0:
            status = "DROP ALERT"
            action = f"DROP ALERT ({trend_30m:+.0f}% in 30m) -> Audit {market}/{language} Intercom queue & checkout link"
        elif utilization_pct >= UTILIZATION_OVERLOADED_PCT:
            status = "OVERLOADED"
            action = f"OVERLOADED ({utilization_pct:.0f}%) -> Reallocate +1 {language} agent into {market}"
        elif utilization_pct < UTILIZATION_UNDERUTILIZED_PCT:
            status = "UNDER-UTILIZED"
            action = f"UNDER-UTILIZED ({utilization_pct:.0f}%) -> Flex {language} capacity to peak queue"
        else:
            status = "OPTIMAL LOAD"
            action = "OPTIMAL LOAD -> Maintain current staffing allocation"

        rows.append({
            "Market": market,
            "Language": language,
            "Valid Orders": orders,
            "Net Revenue ($)": rev,
            "Active Agents": active_agents,
            "FTE Share": fte_share,
            "Orders / Agent-Hr": orders_per_agent_hr,
            "Utilization %": utilization_pct,
            "Last 30m Trend %": trend_30m,
            "Capacity Status": status,
            "Recommended Coordinator Action": action,
        })

    return pd.DataFrame(rows).sort_values(["Utilization %", "Valid Orders"], ascending=False).reset_index(drop=True)


def compute_agent_leaderboard(df_valid: pd.DataFrame) -> pd.DataFrame:
    """Compute per-agent KPIs and Revenue Pace vs. Shift Average (%)."""
    if df_valid.empty:
        return pd.DataFrame()

    # Aggregate per agent (using each agent's primary assigned shift from roster for clean shift peer group)
    grouped = (
        df_valid.groupby("agent_name", as_index=False)
        .agg(
            valid_orders=("order_id", "count"),
            net_revenue_usd=("amount_usd", "sum"),
            discounted_orders=("is_discounted", "sum"),
            primary_shift_id=("shift_id", lambda s: s.mode().iloc[0]),
        )
    )
    grouped["net_revenue_usd"] = grouped["net_revenue_usd"].round(2)
    grouped["aov_usd"] = (grouped["net_revenue_usd"] / grouped["valid_orders"]).round(2)
    grouped["discount_pct"] = (grouped["discounted_orders"] / grouped["valid_orders"] * 100.0).round(1)

    # Shift average revenue & orders across active peers in same shift
    shift_avg_rev = grouped.groupby("primary_shift_id")["net_revenue_usd"].transform("mean")
    shift_avg_ord = grouped.groupby("primary_shift_id")["valid_orders"].transform("mean")

    grouped["rev_pace_vs_shift_pct"] = (
        ((grouped["net_revenue_usd"] - shift_avg_rev) / shift_avg_rev.replace(0, 1)) * 100.0
    ).round(1)
    grouped["orders_pace_vs_shift_pct"] = (
        ((grouped["valid_orders"] - shift_avg_ord) / shift_avg_ord.replace(0, 1)) * 100.0
    ).round(1)

    def _badge(pace: float) -> str:
        if pace >= 15.0:
            return "TOP CLOSER"
        if pace <= -15.0:
            return "NEEDS COACHING"
        return "ON PACE"

    grouped["Status"] = grouped["rev_pace_vs_shift_pct"].apply(_badge)
    grouped["Shift"] = grouped["primary_shift_id"].map(lambda s: SHIFTS.get(s, {}).get("short_name", s))
    grouped["Languages"] = grouped["agent_name"].map(
        lambda a: ", ".join(AGENT_LOOKUP.get(a, {}).get("languages", []))
    )

    grouped = grouped.sort_values("net_revenue_usd", ascending=False).reset_index(drop=True)
    grouped.insert(0, "Rank", range(1, len(grouped) + 1))

    return grouped[[
        "Rank",
        "agent_name",
        "Shift",
        "Languages",
        "valid_orders",
        "net_revenue_usd",
        "aov_usd",
        "discount_pct",
        "rev_pace_vs_shift_pct",
        "Status",
    ]].rename(columns={
        "agent_name": "Agent Name",
        "valid_orders": "Valid Orders",
        "net_revenue_usd": "Net Revenue ($)",
        "aov_usd": "AOV ($)",
        "discount_pct": "Discount %",
        "rev_pace_vs_shift_pct": "Pace vs Shift Avg (%)",
    })
