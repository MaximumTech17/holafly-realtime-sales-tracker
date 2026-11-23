-- Holafly Real-Time Sales Tracker MVP
-- SQLite ANSI SQL Schema & 4-Gate Data Quality Classification Views

CREATE TABLE IF NOT EXISTS raw_orders (
    raw_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_timestamp_utc TEXT NOT NULL,
    order_id TEXT NOT NULL,
    agent_name TEXT,
    discount_code TEXT,
    market TEXT,
    language TEXT,
    customer_email TEXT NOT NULL,
    amount_usd REAL NOT NULL,
    ingested_at_utc TEXT NOT NULL,
    bucket_id INTEGER NOT NULL,
    scenario_tag TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_orders_bucket ON raw_orders(bucket_id);
CREATE INDEX IF NOT EXISTS idx_raw_orders_event_ts ON raw_orders(event_timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_raw_orders_order_id ON raw_orders(order_id);

DROP VIEW IF EXISTS v_quarantined_orders;
DROP VIEW IF EXISTS v_valid_sales;
DROP VIEW IF EXISTS v_classified_orders;

CREATE VIEW v_classified_orders AS
WITH ranked_raw AS (
    SELECT
        r.raw_event_id,
        r.event_timestamp_utc,
        strftime('%Y-%m-%d %H:%M:%S', r.event_timestamp_utc, '-5 hours') AS event_timestamp_cot,
        strftime('%Y-%m-%d', r.event_timestamp_utc, '-5 hours') AS shift_date_cot,
        CAST(strftime('%H', r.event_timestamp_utc, '-5 hours') AS INTEGER) AS hour_cot,
        CASE
            WHEN CAST(strftime('%H', r.event_timestamp_utc, '-5 hours') AS INTEGER) >= 6
             AND CAST(strftime('%H', r.event_timestamp_utc, '-5 hours') AS INTEGER) < 14
                THEN 'SHIFT_1_MORNING'
            WHEN CAST(strftime('%H', r.event_timestamp_utc, '-5 hours') AS INTEGER) >= 14
             AND CAST(strftime('%H', r.event_timestamp_utc, '-5 hours') AS INTEGER) < 22
                THEN 'SHIFT_2_AFTERNOON'
            ELSE 'SHIFT_3_NIGHT'
        END AS shift_id,
        CASE
            WHEN CAST(strftime('%H', r.event_timestamp_utc, '-5 hours') AS INTEGER) >= 6
             AND CAST(strftime('%H', r.event_timestamp_utc, '-5 hours') AS INTEGER) < 14
                THEN 'Morning Shift (06:00-13:59 COT)'
            WHEN CAST(strftime('%H', r.event_timestamp_utc, '-5 hours') AS INTEGER) >= 14
             AND CAST(strftime('%H', r.event_timestamp_utc, '-5 hours') AS INTEGER) < 22
                THEN 'Afternoon Peak (14:00-21:59 COT)'
            ELSE 'Night Shift (22:00-05:59 COT)'
        END AS shift_name,
        TRIM(COALESCE(r.order_id, '')) AS order_id,
        TRIM(COALESCE(r.agent_name, '')) AS agent_name,
        CASE
            WHEN r.discount_code IS NULL OR TRIM(r.discount_code) = '' THEN 'NONE'
            ELSE UPPER(TRIM(r.discount_code))
        END AS discount_code,
        CASE
            WHEN r.discount_code IS NULL
              OR TRIM(r.discount_code) = ''
              OR UPPER(TRIM(r.discount_code)) = 'NONE' THEN 0
            ELSE 1
        END AS is_discounted,
        UPPER(TRIM(COALESCE(r.market, ''))) AS market,
        UPPER(TRIM(COALESCE(r.language, ''))) AS language,
        LOWER(TRIM(COALESCE(r.customer_email, ''))) AS customer_email,
        ROUND(CAST(COALESCE(r.amount_usd, 0.0) AS REAL), 2) AS amount_usd,
        r.ingested_at_utc,
        r.bucket_id,
        r.scenario_tag,
        ROW_NUMBER() OVER (
            PARTITION BY TRIM(COALESCE(r.order_id, ''))
            ORDER BY r.ingested_at_utc ASC, r.raw_event_id ASC
        ) AS occurrence_rank
    FROM raw_orders r
)
SELECT
    raw_event_id,
    event_timestamp_utc,
    event_timestamp_cot,
    shift_date_cot,
    hour_cot,
    shift_id,
    shift_name,
    order_id,
    agent_name,
    discount_code,
    is_discounted,
    market,
    language,
    customer_email,
    amount_usd,
    ingested_at_utc,
    bucket_id,
    scenario_tag,
    occurrence_rank,
    CASE
        WHEN order_id = ''
          OR agent_name = ''
          OR market NOT IN ('US_CA', 'LATAM', 'ES_EU', 'DACH', 'FR_BE', 'APAC')
          OR language NOT IN ('EN', 'ES', 'DE', 'FR', 'JA')
            THEN 'MISSING_DIMENSION'
        WHEN customer_email NOT LIKE '%@%'
          OR customer_email LIKE '%@holafly.internal%'
          OR customer_email LIKE '%@staging.holafly.com%'
          OR customer_email LIKE '%@testmail.invalid%'
          OR customer_email LIKE 'test_%'
          OR customer_email LIKE 'qa.%'
          OR customer_email LIKE 'loadtest.%'
            THEN 'TEST_EMAIL'
        WHEN amount_usd <= 0.00
            THEN 'INVALID_AMOUNT'
        WHEN occurrence_rank > 1
            THEN 'DUPLICATE'
        ELSE 'VALID'
    END AS dq_status,
    CASE
        WHEN order_id = ''
          OR agent_name = ''
          OR market NOT IN ('US_CA', 'LATAM', 'ES_EU', 'DACH', 'FR_BE', 'APAC')
          OR language NOT IN ('EN', 'ES', 'DE', 'FR', 'JA')
            THEN 'Missing or invalid required dimension (Agent, Market, or Language)'
        WHEN customer_email NOT LIKE '%@%'
          OR customer_email LIKE '%@holafly.internal%'
          OR customer_email LIKE '%@staging.holafly.com%'
          OR customer_email LIKE '%@testmail.invalid%'
          OR customer_email LIKE 'test_%'
          OR customer_email LIKE 'qa.%'
          OR customer_email LIKE 'loadtest.%'
            THEN 'Internal QA, staging, or synthetic test email excluded'
        WHEN amount_usd <= 0.00
            THEN 'Zero or negative amount (failed payment capture or refund)'
        WHEN occurrence_rank > 1
            THEN 'Duplicate webhook retry for existing Order ID'
        ELSE 'Valid Sale'
    END AS dq_reason
FROM ranked_raw;

CREATE VIEW v_valid_sales AS
SELECT * FROM v_classified_orders WHERE dq_status = 'VALID';

CREATE VIEW v_quarantined_orders AS
SELECT * FROM v_classified_orders WHERE dq_status != 'VALID';
