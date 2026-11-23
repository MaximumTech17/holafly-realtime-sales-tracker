# Holafly Real-Time Sales Tracker — One-Page Operational Guide

**Author:** Gabriel Andrés Salazar Espinosa | **Role:** Workforce / Sales Ops Data Analyst  
**Live Tracker:** [https://holafly-realtime-sales-tracker.streamlit.app/](https://holafly-realtime-sales-tracker.streamlit.app/)  
**SLA Target:** ≤ 10-minute data latency (**Actual MVP Latency:** 1–3 minutes via 2-min ingestion + 60s live UI refresh)

---

## 1. Architecture & How Auto-Refresh Works (Solving the 3–5h Looker Delay)

* **Why Looker Studio currently lags 3–5 hours:** Legacy reporting stacks three delays: (1) multi-hour batch ETL syncs from checkout/Intercom, (2) scheduled full-table SQL rebuilds, and (3) Looker Studio's default 12-hour data freshness cache.
* **How this MVP works:** A Python deterministic stream engine (`src/mock_generator.py`) ingests new eSIM sales micro-batches every **2 minutes** into an ACID SQLite WAL database (`raw_orders`). ANSI SQL window views (`sql/views.sql`) clean and deduplicate every event in `< 15 ms`, and the Streamlit dashboard (`app.py`) refreshes automatically every **60 seconds** via `@st.fragment(run_every="60s")`.
* **Cloud Autonomy (Runs 24/7 with Local PC Off):** Hosted on Streamlit Community Cloud, the app uses deterministic UTC time-bucket seeding (`BASE_SEED + floor(epoch / 120)`). Every 60-second tick—or whenever an evaluator opens the URL—automatically catches up the stream to `UTC NOW()`.
* **Production Mapping at Holafly:** Replace the mock generator with **Checkout/Intercom Webhooks → Pub/Sub → BigQuery Storage Write API (Streaming Inserts)**, run the exact same 4-gate SQL inside an **Incremental BigQuery Materialized View** scanning only the trailing 24h partition (`< 5 MB/run`), and serve via **BI Engine / Looker Studio** or a **Cloud Run tactical cockpit**.

---

## 2. How Each Role Uses the Tracker During a Shift

| Role | Primary Tab | Key Shift Decisions Supported |
| :--- | :--- | :--- |
| **Sales Managers** | **Sales Manager View** | Monitor top-line **Net Revenue, Valid Orders, AOV, Discount Penetration %, and Revenue/Shift Hour**. Read the live **Anomaly Banner** (`CRITICAL DROP`, `WARNING`, `SURGE`, `NORMAL`) comparing the last 30m against the trailing 3-hour baseline (`Z-score` + `% delta`) to spot checkout outages or `FLASH20` campaign spikes immediately. |
| **Coordinators (WFM)** | **Coordinator View (Workforce & Capacity)** | Inspect the **Market × Language Capacity Heatmap** benchmarked at **3.50 orders/agent-hour**. Reallocate bilingual agents in real time from `UNDER-UTILIZED (< 70%)` queues into `OVERLOADED (>= 115%)` or `DROP ALERT` queues without waiting 4 hours for Looker. |
| **Agents & Team Leads** | **Agent View** | Track the live **Shift Leaderboard** (`Orders`, `Net Revenue`, `AOV`, `Discount %`, and **Pace vs. Shift Average %** — `TOP CLOSER >= +15%`, `ON PACE`, `NEEDS COACHING <= -15%`) plus the live ticker of the latest 25 confirmed orders. |

---

## 3. "What Counts as a Sale?" (4-Gate Data Quality Standard)

Every incoming record in `raw_orders` passes through four ordered SQL validation gates (`v_classified_orders` → `v_valid_sales`); rejected rows remain auditable in `v_quarantined_orders` and the top Telemetry Strip:

1. **Gate 1 — Required Dimensions (`MISSING_DIMENSION`):** Must have non-empty `Order ID`, `Agent`, valid `Market` (`US_CA`, `LATAM`, `ES_EU`, `DACH`, `FR_BE`, `APAC`), and valid `Language` (`EN`, `ES`, `DE`, `FR`, `JA`).
2. **Gate 2 — Test Account Exclusion (`TEST_EMAIL`):** Excludes internal QA/staging addresses (`@holafly.internal`, `@staging.holafly.com`, `@testmail.invalid`, `qa.*`, `test_*`, `loadtest.*`).
3. **Gate 3 — Monetary Rule (`INVALID_AMOUNT`):** Strictly `amount_usd > $0.00` (excludes `$0.00` failed captures and negative refunds/chargebacks; any positive amount counts as a valid sale, with no arbitrary upper cap so high-value B2B/group bundles are counted).
4. **Gate 4 — Exact Deduplication (`DUPLICATE`):** Keeps only the first arrival per Order ID via `ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY ingested_at_utc ASC, raw_event_id ASC) = 1`, neutralizing webhook retries.

---

## 4. Operational Guardrails & Known Refresh Limitations

* **Timezone & Shift Standard:** All timestamps are stored in **ISO-8601 UTC** and displayed in **COT (`UTC-5`, Medellín Hub)** by default (toggleable to `UTC` or `CET`) across three 8-hour shifts: **Morning (`06–14 COT`)**, **Afternoon Peak (`14–22 COT`)**, and **Night (`22–06 COT`)**.
* **Alert False-Positive Guard:** Anomaly banners suppress alerts when the trailing 3-hour baseline averages fewer than **10 valid orders per 30 minutes** (e.g., when filtering down to a single agent).
* **Free-Tier Cloud Limitation:** Streamlit Community Cloud free containers hibernate after 12+ hours of zero visitors; the next visit takes ~15–25s to wake, after which the deterministic catch-up engine restores live data in `< 200 ms`. Moving to **Google Cloud Run (`min-instances=1`)** removes cold starts entirely in production.
