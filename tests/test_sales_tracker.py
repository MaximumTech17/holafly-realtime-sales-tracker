"""Automated Acceptance Test Suite (T-01 through T-10) per spec.md Section 8."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pymupdf
import pytest

from src.analytics import (
    compute_elapsed_hours,
    compute_executive_kpis,
    compute_pipeline_health,
    compute_timeseries_10m,
    evaluate_anomaly_status,
    get_current_shift_bounds_utc,
)
from src.config import BASE_DIR, VALID_LANGUAGES, VALID_MARKETS
from src.db import (
    get_connection,
    load_classified_orders,
    load_quarantined_orders,
    load_valid_sales,
)
from src.mock_generator import (
    initialize_or_reset_db,
    inject_manual_micro_batch,
    sync_live_orders_to_now,
)

FIXED_REF_UTC = datetime(2026, 11, 23, 15, 30, 0, tzinfo=timezone.utc)


@pytest.fixture()
def seeded_db(tmp_path: Path) -> Path:
    db_file = tmp_path / "test_sales_tracker.db"
    initialize_or_reset_db(
        db_path=db_file,
        scenario_mode="DEFAULT_LIVE",
        hours_back=24,
        reference_dt=FIXED_REF_UTC,
    )
    return db_file


def test_t01_backfill_volume_and_schema(seeded_db: Path) -> None:
    """T-01: Backfill covers all 3 shifts, 6 markets, 5 languages, 15 agents; >=450 rows in trailing 8h."""
    since_8h = (FIXED_REF_UTC - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    df_all = load_classified_orders(db_path=seeded_db)
    df_8h = load_classified_orders(db_path=seeded_db, since_utc=since_8h)
    df_valid = load_valid_sales(db_path=seeded_db)

    assert len(df_8h) >= 450, f"Expected >=450 raw records in trailing 8h, got {len(df_8h)}"
    assert df_valid["shift_id"].nunique() == 3
    assert set(df_valid["market"].unique()) == set(VALID_MARKETS)
    assert set(df_valid["language"].unique()) == set(VALID_LANGUAGES)
    assert df_valid["agent_name"].nunique() == 15

    with get_connection(seeded_db) as conn:
        raw_cols = [r[1] for r in conn.execute("PRAGMA table_info(raw_orders);").fetchall()]
        view_cols = [r[1] for r in conn.execute("PRAGMA table_info(v_classified_orders);").fetchall()]
    assert len(raw_cols) == 12
    assert len(view_cols) >= 19
    assert len(df_all) > len(df_8h)


def test_t02_deduplication_exact_uniqueness(seeded_db: Path) -> None:
    """T-02: v_valid_sales has zero duplicate order_ids; duplicates are quarantined with rank > 1."""
    df_valid = load_valid_sales(db_path=seeded_db)
    df_quar = load_quarantined_orders(db_path=seeded_db)

    assert len(df_valid) == df_valid["order_id"].nunique()
    dups = df_quar[df_quar["dq_status"] == "DUPLICATE"]
    assert len(dups) >= 15
    assert (dups["occurrence_rank"] > 1).all()


def test_t03_invalid_amount_exclusion(seeded_db: Path) -> None:
    """T-03: Valid sales strictly obey amount_usd > 0.00 (no upper cap); <=0.00 rows are quarantined."""
    df_valid = load_valid_sales(db_path=seeded_db)
    df_quar = load_quarantined_orders(db_path=seeded_db)

    assert float(df_valid["amount_usd"].min()) > 0.00
    # Verify legitimate high-value B2B/group bundles (> $500.00) ARE counted as valid sales
    assert float(df_valid["amount_usd"].max()) > 500.00

    invalid_amt = df_quar[df_quar["dq_status"] == "INVALID_AMOUNT"]
    assert len(invalid_amt) >= 20
    assert (invalid_amt["amount_usd"] <= 0.00).all()


def test_t04_test_email_exclusion(seeded_db: Path) -> None:
    """T-04: Zero internal QA/staging/test emails leak into v_valid_sales."""
    df_valid = load_valid_sales(db_path=seeded_db)
    df_quar = load_quarantined_orders(db_path=seeded_db)

    forbidden_substrings = ("@holafly.internal", "@staging.holafly.com", "@testmail.invalid")
    for sub in forbidden_substrings:
        assert not df_valid["customer_email"].str.contains(sub, regex=False).any()
    assert not df_valid["customer_email"].str.startswith(("test_", "qa.", "loadtest.")).any()

    test_email_rows = df_quar[df_quar["dq_status"] == "TEST_EMAIL"]
    assert len(test_email_rows) >= 15


def test_t05_missing_dimension_exclusion(seeded_db: Path) -> None:
    """T-05: Zero missing/blank Agent, Market, or Language rows in v_valid_sales."""
    df_valid = load_valid_sales(db_path=seeded_db)
    df_quar = load_quarantined_orders(db_path=seeded_db)

    assert (df_valid["agent_name"].str.len() > 0).all()
    assert df_valid["market"].isin(VALID_MARKETS).all()
    assert df_valid["language"].isin(VALID_LANGUAGES).all()

    missing_dim_rows = df_quar[df_quar["dq_status"] == "MISSING_DIMENSION"]
    assert len(missing_dim_rows) >= 10


def test_t06_dq_partition_conservation(seeded_db: Path) -> None:
    """T-06: Raw == Valid + Duplicate + Invalid_Amount + Test_Email + Missing_Dimension."""
    health = compute_pipeline_health(db_path=seeded_db, reference_now_utc=FIXED_REF_UTC)
    reconstructed = (
        health["valid_count"]
        + health["duplicate_count"]
        + health["invalid_amount_count"]
        + health["test_email_count"]
        + health["missing_dimension_count"]
    )
    assert health["raw_count"] == reconstructed
    assert health["reconciled"] is True


def test_t07_kpi_and_aov_reconciliation(seeded_db: Path) -> None:
    """T-07: KPI & AOV reconcile identically with direct SQL aggregates."""
    df_valid = load_valid_sales(db_path=seeded_db)
    kpis = compute_executive_kpis(df_valid)

    with get_connection(seeded_db) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt, ROUND(SUM(amount_usd), 2) AS rev FROM v_valid_sales;"
        ).fetchone()

    assert kpis["valid_orders_count"] == int(row["cnt"])
    assert kpis["total_revenue_usd"] == pytest.approx(float(row["rev"]), abs=0.01)
    assert kpis["aov_usd"] == round(kpis["total_revenue_usd"] / kpis["valid_orders_count"], 2)
    assert 0.0 <= kpis["discount_penetration_pct"] <= 100.0


def test_t08_anomaly_detector_states(tmp_path: Path) -> None:
    """T-08: Fires CRITICAL DROP on drop, NORMAL on baseline, SURGE on campaign, suppresses <10 sample."""
    # 1. Default live drop -> CRITICAL DROP
    db_drop = tmp_path / "drop.db"
    initialize_or_reset_db(db_drop, scenario_mode="DEFAULT_LIVE", hours_back=8, reference_dt=FIXED_REF_UTC)
    res_drop = evaluate_anomaly_status(load_valid_sales(db_drop), reference_now_utc=FIXED_REF_UTC)
    assert res_drop["state"] == "CRITICAL DROP", f"Expected CRITICAL DROP, got {res_drop}"
    assert res_drop["delta_pct"] <= -35.0

    # 2. Normal baseline -> NORMAL
    db_norm = tmp_path / "norm.db"
    initialize_or_reset_db(db_norm, scenario_mode="NORMAL_BASELINE", hours_back=8, reference_dt=FIXED_REF_UTC)
    res_norm = evaluate_anomaly_status(load_valid_sales(db_norm), reference_now_utc=FIXED_REF_UTC)
    assert res_norm["state"] == "NORMAL", f"Expected NORMAL, got {res_norm}"
    assert res_norm["sufficient_sample"] is True

    # 3. Flash campaign surge -> SURGE
    db_surge = tmp_path / "surge.db"
    initialize_or_reset_db(db_surge, scenario_mode="SURGE_CAMPAIGN", hours_back=8, reference_dt=FIXED_REF_UTC)
    res_surge = evaluate_anomaly_status(load_valid_sales(db_surge), reference_now_utc=FIXED_REF_UTC)
    assert res_surge["state"] == "SURGE", f"Expected SURGE, got {res_surge}"
    assert res_surge["delta_pct"] >= 35.0

    # 4. Minimum sample guard (single agent slice with mu_base < 10.0) -> NORMAL + sufficient_sample=False
    df_tiny = load_valid_sales(db_drop)
    single_agent = df_tiny["agent_name"].iloc[0]
    res_tiny = evaluate_anomaly_status(
        df_tiny[df_tiny["agent_name"] == single_agent],
        reference_now_utc=FIXED_REF_UTC,
    )
    assert res_tiny["state"] == "NORMAL"
    assert res_tiny["sufficient_sample"] is False


def test_t09_live_incremental_ingestion_and_latency(tmp_path: Path) -> None:
    """T-09: Live catch-up & manual batch append orders and keep Freshness Lag <= 3.0m (SLA <= 10m)."""
    db_live = tmp_path / "live.db"
    now_utc = datetime.now(timezone.utc)
    initialize_or_reset_db(
        db_path=db_live,
        scenario_mode="DEFAULT_LIVE",
        hours_back=8,
        reference_dt=now_utc - timedelta(minutes=6),
    )
    before_cnt = len(load_classified_orders(db_live))
    appended = sync_live_orders_to_now(db_path=db_live, scenario_mode="DEFAULT_LIVE", reference_dt=now_utc)
    assert appended > 0
    assert len(load_classified_orders(db_live)) == before_cnt + appended

    manual_added = inject_manual_micro_batch(db_path=db_live, scenario_mode="DEFAULT_LIVE")
    assert manual_added > 0

    health = compute_pipeline_health(db_path=db_live, reference_now_utc=datetime.now(timezone.utc))
    assert health["freshness_lag_minutes"] <= 3.0
    assert health["sla_pass"] is True


def test_t10_deliverable_pdfs_exist_and_one_page() -> None:
    """T-10: Both Deliverable 3 (One-Page Guide) and Deliverable 4 (AI Note) exist, are strictly 1 page, and have 0 emojis."""
    guide_pdf = BASE_DIR / "deliverables" / "03_One_Page_Guide_Real_Time_Sales_Tracker.pdf"
    ai_pdf = BASE_DIR / "deliverables" / "04_AI_Usage_and_Validation_Note.pdf"
    emoji_pattern = re.compile(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200D]")

    for pdf_path in (guide_pdf, ai_pdf):
        assert pdf_path.exists(), f"Missing PDF deliverable: {pdf_path}"
        assert pdf_path.stat().st_size > 2000
        with pymupdf.open(str(pdf_path)) as doc:
            assert len(doc) == 1, f"{pdf_path.name} must be strictly 1 page, found {len(doc)}"
            text = "".join(page.get_text() for page in doc)
            assert not emoji_pattern.findall(text), f"Emoji detected in {pdf_path.name}"


def test_t11_midnight_crossing_night_shift(tmp_path: Path) -> None:
    """T-11: SHIFT_3_NIGHT (22:00-05:59 COT) spans midnight cleanly on full UTC timestamps."""
    # Case A: Pre-midnight COT -> 2026-11-23 23:15 COT == 2026-11-24 04:15 UTC
    pre_mid_utc = datetime(2026, 11, 24, 4, 15, 0, tzinfo=timezone.utc)
    start_a, end_a, shift_a = get_current_shift_bounds_utc(pre_mid_utc)
    assert shift_a == "SHIFT_3_NIGHT"
    assert start_a == datetime(2026, 11, 24, 3, 0, 0, tzinfo=timezone.utc)  # 22:00 COT Nov 23
    assert end_a == datetime(2026, 11, 24, 11, 0, 0, tzinfo=timezone.utc)   # 06:00 COT Nov 24

    # Case B: Post-midnight COT -> 2026-11-24 02:30 COT == 2026-11-24 07:30 UTC
    post_mid_utc = datetime(2026, 11, 24, 7, 30, 0, tzinfo=timezone.utc)
    start_b, end_b, shift_b = get_current_shift_bounds_utc(post_mid_utc)
    assert shift_b == "SHIFT_3_NIGHT"
    assert start_b == start_a  # Must anchor to previous day 22:00 COT without splitting at 00:00 COT
    assert end_b == end_a

    # Verify full backfill + filtering across midnight captures BOTH pre-midnight (22:00-23:59 COT)
    # and post-midnight (00:00-02:30 COT) orders, and H_elapsed + anomaly engine work cleanly.
    db_night = tmp_path / "night_shift.db"
    initialize_or_reset_db(
        db_path=db_night,
        scenario_mode="DEFAULT_LIVE",
        hours_back=12,
        reference_dt=post_mid_utc,
    )
    df_all = load_valid_sales(db_night)
    start_iso = start_b.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = end_b.strftime("%Y-%m-%dT%H:%M:%SZ")
    df_night_shift = df_all[
        (df_all["event_timestamp_utc"] >= start_iso) & (df_all["event_timestamp_utc"] < end_iso)
    ]

    assert not df_night_shift.empty
    assert (df_night_shift["shift_id"] == "SHIFT_3_NIGHT").all()
    # Both pre-midnight (hour_cot >= 22) and post-midnight (hour_cot < 6) must be present
    assert (df_night_shift["hour_cot"] >= 22).any()
    assert (df_night_shift["hour_cot"] < 6).any()
    # Elapsed span should be ~4.5 hours (22:00 COT to 02:30 COT), strictly positive
    elapsed = compute_elapsed_hours(df_night_shift)
    assert 4.0 <= elapsed <= 5.0
    # Anomaly detector across midnight must fire CRITICAL DROP on DEFAULT_LIVE
    anom = evaluate_anomaly_status(df_all, reference_now_utc=post_mid_utc)
    assert anom["state"] == "CRITICAL DROP"


def test_t12_ephemeral_boot_resilience(tmp_path: Path) -> None:
    """T-12: Missing data/ directory and missing DB file auto-initialize seamlessly."""
    nested_db = tmp_path / "ephemeral_data_dir" / "sales_tracker.db"
    assert not nested_db.parent.exists()
    inserted = sync_live_orders_to_now(db_path=nested_db, scenario_mode="DEFAULT_LIVE")
    assert nested_db.exists()
    assert nested_db.stat().st_size > 0
    assert inserted >= 450


def test_t13_zero_emojis_across_codebase() -> None:
    """T-13: Zero emojis or decorative Unicode pictographs remain in code, SQL, LaTeX, config, or docs."""
    emoji_pattern = re.compile(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F\u200D]")
    offenders: list[str] = []
    for ext in ("*.py", "*.sql", "*.md", "*.tex", "*.toml"):
        for path in sorted(BASE_DIR.rglob(ext)):
            if ".git" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                hits = emoji_pattern.findall(line)
                if hits:
                    offenders.append(f"{path.relative_to(BASE_DIR)}:{lineno}: {hits}")
    assert not offenders, f"Emojis/pictographs found: {offenders}"


def test_t14_organic_intraday_variance(tmp_path: Path) -> None:
    """T-14: Baseline 10-min valid order counts exhibit realistic non-flat organic variation."""
    db_norm = tmp_path / "organic.db"
    initialize_or_reset_db(
        db_path=db_norm,
        scenario_mode="NORMAL_BASELINE",
        hours_back=8,
        reference_dt=FIXED_REF_UTC,
    )
    df_valid = load_valid_sales(db_norm)
    ts_10m = compute_timeseries_10m(df_valid, tz_offset_hours=-5)
    # Exclude first/last partial 10-min edge buckets
    core = ts_10m.iloc[1:-1]["valid_orders"]
    assert core.std() >= 1.2, f"Baseline curve looks too flat (std={core.std():.2f})"
    assert core.nunique() >= 4, f"Expected >=4 distinct 10m bucket counts, got {core.nunique()}"
    assert int(core.min()) >= 5
    assert int(core.max()) <= 22


def test_t15_app_renders_logo_and_zero_raw_html() -> None:
    """T-15: App renders official Holafly SVG logo, 0 st.metric widgets, and zero raw HTML code-block leakage."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(BASE_DIR / "app.py"), default_timeout=25).run()
    assert not at.exception, f"Streamlit AppTest raised exceptions: {at.exception}"
    assert len(at.metric) == 0, "Default st.metric should not be used (truncates values)"

    # Verify official Holafly logo is embedded as base64 SVG data URI
    all_md = [m.value for m in at.markdown]
    assert any("data:image/svg+xml;base64," in val and "alt=\"Holafly\"" in val for val in all_md), (
        "Official Holafly SVG logo not found in rendered header"
    )
    # Verify ZERO markdown blocks start with 4-space indented HTML (which leaks raw <div> tags as code blocks)
    for val in all_md:
        for line in val.splitlines():
            assert not line.startswith("    <div"), f"Indented HTML leak detected: {line[:80]}"
            assert not line.startswith("    <span"), f"Indented HTML leak detected: {line[:80]}"
    # Verify no st.code block contains kpi-card HTML
    for code_blk in at.code:
        assert "kpi-card" not in code_blk.value
