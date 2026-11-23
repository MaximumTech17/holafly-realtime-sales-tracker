"""Centralized configuration constants for the Holafly Real-Time Sales Tracker MVP."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "sales_tracker.db"
SQL_VIEWS_PATH = BASE_DIR / "sql" / "views.sql"
LOGO_SVG_PATH = BASE_DIR / "static" / "holafly_logo.svg"

# Deterministic stream seeding & cadence
BASE_SEED = 20261123
INGESTION_INTERVAL_SECONDS = 120   # 2-minute micro-batch ingestion
UI_REFRESH_INTERVAL_SECONDS = 60   # 60-second UI auto-refresh
DEFAULT_BACKFILL_HOURS = 24        # Full 3-shift operational cycle stored in DB
SLA_MAX_LATENCY_MINUTES = 10.0

# Capacity & Anomaly Detection Constants
TARGET_ORDERS_PER_AGENT_HOUR = 3.50
UTILIZATION_OVERLOADED_PCT = 115.0
UTILIZATION_UNDERUTILIZED_PCT = 70.0

CURRENT_WINDOW_MINUTES = 30
BASELINE_WINDOW_MINUTES = 180
MIN_BASELINE_ORDERS_30M = 10.0

CRITICAL_DROP_PCT = -35.0
CRITICAL_DROP_Z = -2.5
CRITICAL_DROP_Z_PCT_GUARD = -25.0

WARNING_DROP_PCT = -20.0
WARNING_DROP_Z = -1.8
WARNING_DROP_Z_PCT_GUARD = -15.0

SURGE_PCT = 35.0
SURGE_Z = 2.5
SURGE_Z_PCT_GUARD = 25.0

# Official Holafly + Intercom Editorial Palette Tokens (DESIGN (1).md)
COLORS = {
    "canvas_cream": "#faf9f6",
    "linen": "#f1eee9",
    "stone": "#d3cec6",
    "hairline": "#dedbd6",
    "pure_white": "#ffffff",
    "ink": "#111111",
    "carbon": "#000000",
    "iron": "#414141",
    "graphite": "#585858",
    "smoke": "#888888",
    "silver": "#b8b8b8",
    "holafly_red": "#e63946",
    "holafly_logo": "#e6485c",
    "forest_ok": "#15803d",
    "amber_warn": "#b45309",
}

# Timezone display offsets relative to UTC
TIMEZONE_OPTIONS = {
    "COT (UTC-5 — Medellín Hub)": -5,
    "UTC (UTC+0 — Global Standard)": 0,
    "CET (UTC+1 — Madrid / EU HQ)": 1,
}

# 3-Shift Global Coverage Model (anchored to COT / UTC-5)
SHIFTS = {
    "SHIFT_1_MORNING": {
        "name": "Morning Shift (06:00-13:59 COT)",
        "short_name": "Morning (06-14 COT)",
        "cot_start_hour": 6,
        "cot_end_hour": 14,
        "utc_window": "11:00-18:59 UTC",
    },
    "SHIFT_2_AFTERNOON": {
        "name": "Afternoon Peak (14:00-21:59 COT)",
        "short_name": "Afternoon Peak (14-22 COT)",
        "cot_start_hour": 14,
        "cot_end_hour": 22,
        "utc_window": "19:00-02:59+1 UTC",
    },
    "SHIFT_3_NIGHT": {
        "name": "Night Shift (22:00-05:59 COT)",
        "short_name": "Night (22-06 COT)",
        "cot_start_hour": 22,
        "cot_end_hour": 6,
        "utc_window": "03:00-10:59 UTC",
    },
}

VALID_MARKETS = ("US_CA", "LATAM", "ES_EU", "DACH", "FR_BE", "APAC")
VALID_LANGUAGES = ("EN", "ES", "DE", "FR", "JA")

MARKETS = {
    "US_CA": {
        "display_name": "North America (US & CA)",
        "weight": 0.26,
        "price_tiers": [19.00, 34.00, 54.00, 69.00],
        "tier_weights": [0.20, 0.45, 0.25, 0.10],
        "languages": {"EN": 0.90, "ES": 0.10},
    },
    "LATAM": {
        "display_name": "Latin America",
        "weight": 0.22,
        "price_tiers": [19.00, 29.00, 44.00, 59.00],
        "tier_weights": [0.25, 0.45, 0.20, 0.10],
        "languages": {"ES": 0.92, "EN": 0.08},
    },
    "ES_EU": {
        "display_name": "Spain & Southern EU",
        "weight": 0.20,
        "price_tiers": [19.00, 34.00, 49.00, 64.00],
        "tier_weights": [0.25, 0.45, 0.20, 0.10],
        "languages": {"ES": 0.78, "EN": 0.22},
    },
    "DACH": {
        "display_name": "DACH (DE/AT/CH)",
        "weight": 0.13,
        "price_tiers": [27.00, 39.00, 54.00, 79.00],
        "tier_weights": [0.20, 0.40, 0.25, 0.15],
        "languages": {"DE": 0.82, "EN": 0.18},
    },
    "FR_BE": {
        "display_name": "France & Benelux",
        "weight": 0.11,
        "price_tiers": [27.00, 39.00, 49.00, 69.00],
        "tier_weights": [0.20, 0.45, 0.25, 0.10],
        "languages": {"FR": 0.85, "EN": 0.15},
    },
    "APAC": {
        "display_name": "Asia-Pacific (JP/AU/SEA)",
        "weight": 0.08,
        "price_tiers": [29.00, 47.00, 64.00, 89.00],
        "tier_weights": [0.15, 0.40, 0.30, 0.15],
        "languages": {"EN": 0.55, "JA": 0.45},
    },
}

AGENTS = [
    {"agent_id": "AGT-01", "agent_name": "Valeria Montoya", "shift_id": "SHIFT_1_MORNING", "languages": ["ES", "EN"], "markets": ["ES_EU", "US_CA"], "weight": 1.15},
    {"agent_id": "AGT-02", "agent_name": "Mateo Restrepo", "shift_id": "SHIFT_1_MORNING", "languages": ["ES", "EN"], "markets": ["LATAM", "ES_EU"], "weight": 1.05},
    {"agent_id": "AGT-03", "agent_name": "Lukas Weber", "shift_id": "SHIFT_1_MORNING", "languages": ["DE", "EN"], "markets": ["DACH", "US_CA"], "weight": 1.00},
    {"agent_id": "AGT-04", "agent_name": "Camille Laurent", "shift_id": "SHIFT_1_MORNING", "languages": ["FR", "EN"], "markets": ["FR_BE", "ES_EU"], "weight": 0.95},
    {"agent_id": "AGT-05", "agent_name": "Santiago Giraldo", "shift_id": "SHIFT_1_MORNING", "languages": ["EN", "ES"], "markets": ["US_CA", "LATAM"], "weight": 0.85},
    {"agent_id": "AGT-06", "agent_name": "Mariana Duque", "shift_id": "SHIFT_2_AFTERNOON", "languages": ["EN", "ES"], "markets": ["US_CA", "LATAM"], "weight": 1.20},
    {"agent_id": "AGT-07", "agent_name": "Andrés Ospina", "shift_id": "SHIFT_2_AFTERNOON", "languages": ["ES", "EN"], "markets": ["LATAM", "ES_EU"], "weight": 1.10},
    {"agent_id": "AGT-08", "agent_name": "Jonas Fischer", "shift_id": "SHIFT_2_AFTERNOON", "languages": ["DE", "EN"], "markets": ["DACH", "US_CA"], "weight": 0.95},
    {"agent_id": "AGT-09", "agent_name": "Chloé Dubois", "shift_id": "SHIFT_2_AFTERNOON", "languages": ["FR", "EN"], "markets": ["FR_BE", "US_CA"], "weight": 0.90},
    {"agent_id": "AGT-10", "agent_name": "Sebastián Mejía", "shift_id": "SHIFT_2_AFTERNOON", "languages": ["EN", "ES", "JA"], "markets": ["US_CA", "APAC"], "weight": 0.85},
    {"agent_id": "AGT-11", "agent_name": "Kenji Takahashi", "shift_id": "SHIFT_3_NIGHT", "languages": ["JA", "EN"], "markets": ["APAC", "US_CA"], "weight": 1.15},
    {"agent_id": "AGT-12", "agent_name": "Sofía Arango", "shift_id": "SHIFT_3_NIGHT", "languages": ["ES", "EN"], "markets": ["ES_EU", "LATAM"], "weight": 1.05},
    {"agent_id": "AGT-13", "agent_name": "Hannah Becker", "shift_id": "SHIFT_3_NIGHT", "languages": ["DE", "EN"], "markets": ["DACH", "APAC"], "weight": 1.00},
    {"agent_id": "AGT-14", "agent_name": "Lucas Moreau", "shift_id": "SHIFT_3_NIGHT", "languages": ["FR", "EN"], "markets": ["FR_BE", "ES_EU"], "weight": 0.95},
    {"agent_id": "AGT-15", "agent_name": "Daniela Vélez", "shift_id": "SHIFT_3_NIGHT", "languages": ["EN", "ES", "JA"], "markets": ["APAC", "US_CA"], "weight": 0.85},
]

AGENT_LOOKUP = {a["agent_name"]: a for a in AGENTS}

DISCOUNT_CODES = {
    "NONE": {"pct": 0.00, "weight": 0.62, "description": "Full retail price (no promo code)"},
    "HOLA5": {"pct": 0.05, "weight": 0.14, "description": "Affiliate / referral 5% discount"},
    "TRAVEL10": {"pct": 0.10, "weight": 0.11, "description": "Chat agent closing incentive (10% off)"},
    "VIP15": {"pct": 0.15, "weight": 0.06, "description": "Repeat traveler / multi-eSIM bundle"},
    "FLASH20": {"pct": 0.20, "weight": 0.05, "description": "Seasonal flash campaign code"},
    "WELCOME10": {"pct": 0.10, "weight": 0.02, "description": "Cart recovery / WhatsApp welcome"},
}

SAFE_FAKE_DOMAINS = (
    "example.com",
    "example.net",
    "travelmail.invalid",
    "nomadsim.invalid",
)

EMAIL_FIRST_TOKENS = (
    "alex", "sam", "jordan", "clara", "lucas", "sofia", "mateo", "elena",
    "noah", "emma", "liam", "mia", "hiro", "yuki", "chloe", "leo",
    "diego", "paula", "felix", "anna", "marc", "julia", "tomas", "nina",
)

SCENARIO_MODES = {
    "DEFAULT_LIVE": "Live Stream (Default — Active Mid-Shift Drop Alert)",
    "NORMAL_BASELINE": "Normal Baseline Traffic (Healthy Pacing)",
    "CRITICAL_OUTAGE": "Critical Payment/Queue Outage (-62% Drop)",
    "SURGE_CAMPAIGN": "Flash Campaign Surge (+67% FLASH20 Spike)",
}
