"""Deterministic Mock Data Generator for Holafly Conversational Commerce Sales.

Supports:
  - 24-hour full 3-shift deterministic backfill (anchored to UTC 2-minute buckets)
  - Live wall-clock catch-up (`sync_live_orders_to_now`) for 24/7 autonomous cloud operation
  - Manual micro-batch injection (`inject_manual_micro_batch`) for interactive demo
  - CLI modes: `--mode backfill`, `--mode step`, `--mode daemon --interval 120`
"""

from __future__ import annotations

import argparse
import math
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import (
    AGENTS,
    BASE_SEED,
    DB_PATH,
    DEFAULT_BACKFILL_HOURS,
    DISCOUNT_CODES,
    EMAIL_FIRST_TOKENS,
    INGESTION_INTERVAL_SECONDS,
    MARKETS,
    SAFE_FAKE_DOMAINS,
)
from src.db import (
    get_max_bucket_id,
    init_schema,
    insert_raw_orders,
    reset_raw_orders,
)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _shift_id_for_utc(dt_utc: datetime) -> str:
    hour_cot = (dt_utc - timedelta(hours=5)).hour
    if 6 <= hour_cot < 14:
        return "SHIFT_1_MORNING"
    if 14 <= hour_cot < 22:
        return "SHIFT_2_AFTERNOON"
    return "SHIFT_3_NIGHT"


def _weighted_choice(rng: random.Random, items: list, weights: list[float]):
    total = sum(weights)
    pick = rng.random() * total
    upto = 0.0
    for item, weight in zip(items, weights):
        upto += weight
        if pick <= upto:
            return item
    return items[-1]


def _pick_agent(rng: random.Random, shift_id: str, language: str, market: str) -> str:
    """Select an agent from the active shift who speaks the customer's language."""
    # 10% cross-shift handoff spillover for realism
    if rng.random() < 0.10:
        pool = [a for a in AGENTS if language in a["languages"]]
    else:
        pool = [a for a in AGENTS if a["shift_id"] == shift_id and language in a["languages"]]
        if not pool:
            pool = [a for a in AGENTS if a["shift_id"] == shift_id]
    if not pool:
        pool = AGENTS

    weights = []
    for agent in pool:
        w = agent["weight"]
        if market in agent["markets"]:
            w *= 1.35
        weights.append(w)
    return _weighted_choice(rng, pool, weights)["agent_name"]


def _poisson_sample(rng: random.Random, lam: float) -> int:
    """Deterministic Knuth Poisson draw for realistic organic per-bucket order arrivals."""
    if lam <= 0.0:
        return 0
    limit = math.exp(-lam)
    k = 0
    p = 1.0
    while p > limit:
        k += 1
        p *= rng.random()
    return k - 1


def _bucket_scenario_profile(
    bucket_id: int,
    now_bucket: int,
    scenario_mode: str,
) -> tuple[str, int, dict[str, float] | None, float]:
    """Return (scenario_tag, valid_order_count, market_weight_override, flash20_override_prob).

    Uses a deterministic intraday diurnal wave + Poisson dispersion so 10-minute counts
    fluctuate organically between ~8 and ~17 around the ~12.0 baseline mean (~36 / 30m).
    """
    buckets_ago = now_bucket - bucket_id
    vol_rng = random.Random((BASE_SEED * 31) ^ (bucket_id * 2654435761))

    # Smooth multi-hour diurnal cadence (~+/-12% around 2.40 orders per 2-min bucket)
    diurnal = (
        1.0
        + 0.11 * math.sin(2.0 * math.pi * bucket_id / 180.0)
        + 0.06 * math.cos(2.0 * math.pi * bucket_id / 48.0)
    )
    lam_base = 2.42 * diurnal
    base_count = max(1, min(5, _poisson_sample(vol_rng, lam_base)))

    if scenario_mode == "NORMAL_BASELINE":
        # Keep the active 30-min evaluation window centered cleanly on baseline mean with organic variance
        if 0 <= buckets_ago <= 14:
            norm_pattern = (2, 3, 2, 1, 3, 3, 2, 3, 2, 2, 3, 4, 2, 2, 2)
            return ("BASELINE", norm_pattern[buckets_ago], None, 0.05)
        return ("BASELINE", base_count, None, 0.05)

    # Historical Flash Campaign Surge at [NOW - 240 min, NOW - 210 min] (buckets_ago 106..120)
    if scenario_mode == "DEFAULT_LIVE" and 106 <= buckets_ago <= 120:
        surge_count = max(3, min(6, _poisson_sample(vol_rng, 4.15)))
        return ("SURGE_CAMPAIGN", surge_count, None, 0.45)

    # Active latest 30-minute window (buckets_ago 0..14)
    if 0 <= buckets_ago <= 14:
        if scenario_mode in ("DEFAULT_LIVE", "CRITICAL_OUTAGE"):
            # Organic drop averaging ~0.87 orders/2m (~13 orders/30m vs ~36 baseline = -62% drop)
            drop_pattern = (1, 0, 1, 1, 2, 0, 1, 1, 0, 1, 2, 1, 0, 1, 1)
            drop_count = drop_pattern[buckets_ago]
            drop_market_weights = {
                "US_CA": 0.08,
                "LATAM": 0.34,
                "ES_EU": 0.09,
                "DACH": 0.21,
                "FR_BE": 0.16,
                "APAC": 0.12,
            }
            return ("DROP_ANOMALY", drop_count, drop_market_weights, 0.05)

        if scenario_mode == "SURGE_CAMPAIGN":
            # Organic surge averaging ~4.07 orders/2m (~61 orders/30m vs ~36 baseline = +69% surge)
            surge_pattern = (4, 5, 3, 4, 5, 4, 3, 5, 4, 4, 5, 3, 4, 4, 4)
            return ("SURGE_CAMPAIGN", surge_pattern[buckets_ago], None, 0.45)

    return ("BASELINE", base_count, None, 0.05)


def generate_bucket_events(
    bucket_id: int,
    now_bucket: int,
    scenario_mode: str = "DEFAULT_LIVE",
    tag_override: str | None = None,
) -> list[tuple]:
    """Deterministically generate raw order tuples for one 2-minute UTC bucket."""
    rng = random.Random(BASE_SEED + bucket_id)
    bucket_start = datetime.fromtimestamp(bucket_id * INGESTION_INTERVAL_SECONDS, tz=timezone.utc)
    scenario_tag, valid_count, market_weights_override, flash20_prob = _bucket_scenario_profile(
        bucket_id, now_bucket, scenario_mode
    )
    if tag_override:
        scenario_tag = tag_override

    market_keys = list(MARKETS.keys())
    if market_weights_override:
        market_weights = [market_weights_override[m] for m in market_keys]
    else:
        market_weights = [MARKETS[m]["weight"] for m in market_keys]

    discount_keys = list(DISCOUNT_CODES.keys())
    if flash20_prob > 0.10:
        discount_weights = [0.30, 0.09, 0.09, 0.05, flash20_prob, 0.02]
    else:
        discount_weights = [DISCOUNT_CODES[k]["weight"] for k in discount_keys]

    rows: list[tuple] = []
    date_prefix = bucket_start.strftime("%Y%m%d")

    # 1. Generate core valid sales + deterministic duplicate webhook retries (~4.0%)
    for seq in range(valid_count):
        offset_sec = rng.randint(2, INGESTION_INTERVAL_SECONDS - 10)
        event_dt = bucket_start + timedelta(seconds=offset_sec)
        ingest_delay_sec = rng.randint(3, 18)
        ingest_dt = event_dt + timedelta(seconds=ingest_delay_sec)

        market = _weighted_choice(rng, market_keys, market_weights)
        m_cfg = MARKETS[market]
        lang_keys = list(m_cfg["languages"].keys())
        lang_weights = [m_cfg["languages"][k] for k in lang_keys]
        language = _weighted_choice(rng, lang_keys, lang_weights)

        shift_id = _shift_id_for_utc(event_dt)
        agent_name = _pick_agent(rng, shift_id, language, market)

        base_price = _weighted_choice(rng, m_cfg["price_tiers"], m_cfg["tier_weights"])
        discount_code = _weighted_choice(rng, discount_keys, discount_weights)
        disc_pct = DISCOUNT_CODES[discount_code]["pct"]
        net_amount = round(base_price * (1.0 - disc_pct), 2)

        token = rng.choice(EMAIL_FIRST_TOKENS)
        email_hash = rng.randint(1000, 9999)
        domain = rng.choice(SAFE_FAKE_DOMAINS)
        customer_email = f"{token}.{email_hash}@{domain}"

        global_seq = (bucket_id % 100000) * 10 + seq
        order_id = f"ORD-{date_prefix}-{global_seq:06d}"

        valid_row = (
            _utc_iso(event_dt),
            order_id,
            agent_name,
            discount_code,
            market,
            language,
            customer_email,
            net_amount,
            _utc_iso(ingest_dt),
            bucket_id,
            scenario_tag,
        )
        rows.append(valid_row)

        # Deterministic Duplicate Webhook Retry (~4.0% single retry, ~0.5% double retry)
        slot_index = bucket_id * 5 + seq
        if slot_index % 25 == 0:
            retry_dt = ingest_dt + timedelta(seconds=25)
            rows.append((
                _utc_iso(event_dt),
                order_id,
                agent_name,
                discount_code,
                market,
                language,
                customer_email,
                net_amount,
                _utc_iso(retry_dt),
                bucket_id,
                scenario_tag,
            ))
            if slot_index % 200 == 0:
                retry_dt_2 = ingest_dt + timedelta(seconds=55)
                rows.append((
                    _utc_iso(event_dt),
                    order_id,
                    agent_name,
                    discount_code,
                    market,
                    language,
                    customer_email,
                    net_amount,
                    _utc_iso(retry_dt_2),
                    bucket_id,
                    scenario_tag,
                ))

    # 2. Deterministic Injected Data Quality Noise (separate order_ids so they never collide)
    # Invalid Amount: Zero capture (~1/12 buckets), Negative refund (~1/18 buckets), Outlier >$500 (~1/65 buckets)
    noise_dt = bucket_start + timedelta(seconds=rng.randint(15, 105))
    noise_ingest = noise_dt + timedelta(seconds=rng.randint(4, 15))
    noise_shift = _shift_id_for_utc(noise_dt)
    noise_agent = _pick_agent(rng, noise_shift, "EN", "US_CA")

    if bucket_id % 12 == 3:
        rows.append((
            _utc_iso(noise_dt),
            f"ORD-{date_prefix}-Z{bucket_id % 100000:05d}",
            noise_agent,
            "NONE",
            "US_CA",
            "EN",
            f"capture.fail.{bucket_id % 9999}@example.com",
            0.00,
            _utc_iso(noise_ingest),
            bucket_id,
            scenario_tag,
        ))

    if bucket_id % 18 == 7:
        rows.append((
            _utc_iso(noise_dt + timedelta(seconds=3)),
            f"ORD-{date_prefix}-R{bucket_id % 100000:05d}",
            noise_agent,
            "HOLA5",
            "ES_EU",
            "ES",
            f"refund.user.{bucket_id % 9999}@travelmail.invalid",
            -34.00 if (bucket_id % 2 == 0) else -19.00,
            _utc_iso(noise_ingest + timedelta(seconds=3)),
            bucket_id,
            scenario_tag,
        ))

    # Legitimate high-value corporate / group multi-eSIM order (> $500.00, counted as VALID sale)
    if bucket_id % 65 == 19:
        rows.append((
            _utc_iso(noise_dt + timedelta(seconds=6)),
            f"ORD-{date_prefix}-B{bucket_id % 100000:05d}",
            noise_agent,
            "VIP15",
            "DACH",
            "DE",
            f"corp.travel.{bucket_id % 9999}@example.net",
            640.00,
            _utc_iso(noise_ingest + timedelta(seconds=6)),
            bucket_id,
            scenario_tag,
        ))

    # Internal QA / Staging / Test Emails (~1/14 buckets)
    if bucket_id % 14 == 5:
        test_emails = (
            f"qa.test+{bucket_id % 10000}@holafly.internal",
            f"test_checkout_{bucket_id % 10000}@staging.holafly.com",
            "admin.probe@testmail.invalid",
            "loadtest.bot@example.org",
        )
        rows.append((
            _utc_iso(noise_dt + timedelta(seconds=8)),
            f"ORD-{date_prefix}-T{bucket_id % 100000:05d}",
            noise_agent,
            "TRAVEL10",
            "US_CA",
            "EN",
            test_emails[bucket_id % len(test_emails)],
            30.60,
            _utc_iso(noise_ingest + timedelta(seconds=8)),
            bucket_id,
            scenario_tag,
        ))

    # Missing Required Dimension (~1/32 buckets)
    if bucket_id % 32 == 11:
        corrupt_kind = bucket_id % 3
        rows.append((
            _utc_iso(noise_dt + timedelta(seconds=10)),
            f"ORD-{date_prefix}-M{bucket_id % 100000:05d}",
            None if corrupt_kind == 0 else noise_agent,
            "NONE",
            "" if corrupt_kind == 1 else "LATAM",
            None if corrupt_kind == 2 else "ES",
            f"bot.fallback.{bucket_id % 9999}@nomadsim.invalid",
            29.00,
            _utc_iso(noise_ingest + timedelta(seconds=10)),
            bucket_id,
            scenario_tag,
        ))

    return rows


def current_utc_bucket(reference_dt: datetime | None = None) -> int:
    dt = reference_dt or datetime.now(timezone.utc)
    return int(dt.timestamp() // INGESTION_INTERVAL_SECONDS)


def initialize_or_reset_db(
    db_path: Path | str = DB_PATH,
    scenario_mode: str = "DEFAULT_LIVE",
    hours_back: int = DEFAULT_BACKFILL_HOURS,
    reference_dt: datetime | None = None,
) -> int:
    """Reset the SQLite DB and generate deterministic historical backfill up to now."""
    reset_raw_orders(db_path)
    now_bucket = current_utc_bucket(reference_dt)
    total_buckets = int((hours_back * 3600) // INGESTION_INTERVAL_SECONDS)
    start_bucket = now_bucket - total_buckets + 1

    all_rows: list[tuple] = []
    for b_id in range(start_bucket, now_bucket + 1):
        all_rows.extend(generate_bucket_events(b_id, now_bucket, scenario_mode=scenario_mode))

    return insert_raw_orders(all_rows, db_path=db_path)


def sync_live_orders_to_now(
    db_path: Path | str = DB_PATH,
    scenario_mode: str = "DEFAULT_LIVE",
    hours_back: int = DEFAULT_BACKFILL_HOURS,
    reference_dt: datetime | None = None,
) -> int:
    """Catch up raw_orders deterministically to the current UTC 2-minute bucket.

    If the database is empty or stale by > hours_back, performs a clean backfill.
    Otherwise appends only newly elapsed 2-minute buckets.
    """
    init_schema(db_path)
    now_bucket = current_utc_bucket(reference_dt)
    max_bucket = get_max_bucket_id(db_path)
    total_buckets = int((hours_back * 3600) // INGESTION_INTERVAL_SECONDS)

    if max_bucket is None or (now_bucket - max_bucket) > total_buckets:
        return initialize_or_reset_db(
            db_path=db_path,
            scenario_mode=scenario_mode,
            hours_back=hours_back,
            reference_dt=reference_dt,
        )

    if max_bucket >= now_bucket:
        return 0

    new_rows: list[tuple] = []
    for b_id in range(max_bucket + 1, now_bucket + 1):
        new_rows.extend(generate_bucket_events(b_id, now_bucket, scenario_mode=scenario_mode))
    return insert_raw_orders(new_rows, db_path=db_path)


def inject_manual_micro_batch(
    db_path: Path | str = DB_PATH,
    scenario_mode: str = "DEFAULT_LIVE",
) -> int:
    """Immediately append one fresh 2-minute micro-batch stamped at UTC NOW() for demo testing."""
    init_schema(db_path)
    now_dt = datetime.now(timezone.utc)
    now_bucket = current_utc_bucket(now_dt)
    max_bucket = get_max_bucket_id(db_path) or (now_bucket - 1)
    next_bucket = max(now_bucket, max_bucket) + 1

    # Generate using next_bucket seed, but anchor timestamps strictly to current UTC second
    raw_rows = generate_bucket_events(
        next_bucket,
        next_bucket,
        scenario_mode=scenario_mode,
        tag_override="MANUAL_BATCH",
    )
    stamped_rows: list[tuple] = []
    for idx, row in enumerate(raw_rows):
        ev_dt = now_dt - timedelta(seconds=max(0, 10 - idx * 2))
        ing_dt = now_dt
        stamped_rows.append((
            _utc_iso(ev_dt),
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            row[6],
            row[7],
            _utc_iso(ing_dt),
            next_bucket,
            "MANUAL_BATCH",
        ))
    return insert_raw_orders(stamped_rows, db_path=db_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Holafly Real-Time Sales Tracker — Deterministic Mock Data Generator"
    )
    parser.add_argument(
        "--mode",
        choices=("backfill", "step", "daemon"),
        default="backfill",
        help="Execution mode: backfill (rebuild 24h DB), step (catch up once), daemon (loop every interval).",
    )
    parser.add_argument(
        "--scenario",
        choices=("DEFAULT_LIVE", "NORMAL_BASELINE", "CRITICAL_OUTAGE", "SURGE_CAMPAIGN"),
        default="DEFAULT_LIVE",
        help="Operational traffic & anomaly scenario to simulate.",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=DEFAULT_BACKFILL_HOURS,
        help="Historical backfill window in hours (default: 24).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=INGESTION_INTERVAL_SECONDS,
        help="Daemon loop interval in seconds (default: 120).",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(DB_PATH),
        help="Target SQLite database file path.",
    )
    args = parser.parse_args()

    if args.mode == "backfill":
        inserted = initialize_or_reset_db(
            db_path=args.db,
            scenario_mode=args.scenario,
            hours_back=args.hours,
        )
        print(f"[BACKFILL COMPLETE] Inserted {inserted} raw events into {args.db} (scenario={args.scenario}, hours={args.hours})")
    elif args.mode == "step":
        inserted = sync_live_orders_to_now(
            db_path=args.db,
            scenario_mode=args.scenario,
            hours_back=args.hours,
        )
        print(f"[STEP COMPLETE] Appended {inserted} new raw events into {args.db}")
    elif args.mode == "daemon":
        print(f"[DAEMON STARTED] Syncing {args.db} every {args.interval}s (scenario={args.scenario}). Press Ctrl+C to stop.")
        while True:
            inserted = sync_live_orders_to_now(
                db_path=args.db,
                scenario_mode=args.scenario,
                hours_back=args.hours,
            )
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"[{now_str}] Sync tick complete — appended {inserted} raw events.")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
