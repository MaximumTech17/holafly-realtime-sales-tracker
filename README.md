# Holafly Real-Time Sales Tracker MVP

> **Workforce / Sales Ops Data Analyst Technical Assessment — Conversational Commerce**  
> **Author:** Gabriel Andrés Salazar Espinosa (`gabrielandressalazarespinosa@gmail.com`)  
> **Live Dashboard:** [https://holafly-realtime-sales-tracker.streamlit.app/](https://holafly-realtime-sales-tracker.streamlit.app/)  
> **SLA Target:** ≤ 10 minutes refresh latency (**Actual:** 2-minute ingestion + 60-second UI refresh = **1–3 min max latency**)

---

## Live Architecture Overview

This MVP replaces legacy 3–5 hour Looker Studio batch delays with an autonomous real-time operational cockpit designed for **Sales Managers**, **Workforce Coordinators**, and **Conversational Sales Agents**:

```text
Mock Stream Generator (2-min UTC deterministic micro-batches)
   └──► SQLite WAL Database (raw_orders)
           └──► 4-Gate ANSI SQL Views (v_classified_orders -> v_valid_sales / v_quarantined_orders)
                   └──► Analytics, Capacity & Anomaly Engine (30m vs 3h Baseline Z-Score)
                           └──► Multi-Persona Streamlit Cockpit (@st.fragment 60s Live Auto-Refresh)
```

### Key Features
- **Zero-Local-PC Cloud Autonomy:** Uses deterministic UTC time-bucket seeding (`BASE_SEED + floor(epoch / 120)`), so the Streamlit Community Cloud deployment automatically catches up to `UTC NOW()` on every 60-second refresh or evaluator page load—with zero external credentials or local PC uptime required.
- **Formal 4-Gate "What Counts as a Sale?" SQL Layer (`sql/views.sql`):**
  1. Required Dimension validation (`Agent`, `Market`, `Language`, `Order ID`)
  2. Internal QA/Staging test email exclusion (`@holafly.internal`, `@staging.holafly.com`, `@testmail.invalid`, `qa.*`, `test_*`, `loadtest.*`)
  3. Positive monetary rule (`amount_usd > $0.00` — filters refunds/failed captures; no arbitrary upper cap)
  4. Exact webhook retry deduplication via `ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY ingested_at_utc ASC, raw_event_id ASC) = 1`
- **3 Operational Persona Views + Data Quality Audit Tab:**
  - **Sales Manager View:** Executive KPIs, 10-min revenue/orders time-series with shaded expected baseline band, live Anomaly Alert Banner (`CRITICAL DROP`, `WARNING`, `SURGE`, `NORMAL`), Market pacing attribution, and Discount Code margin mix.
  - **Coordinator View (Workforce & Capacity):** Market × Language utilization heatmap (benchmarked at `3.50 orders/agent-hr`), live shift reallocation actions, and Agent × Shift coverage matrix.
  - **Agent View:** Shift leaderboard with **Pace vs. Shift Average (%)** and live ticker of the latest 25 valid orders.
  - **Data Quality & SQL Audit View:** 4-gate reconciliation funnel, quarantined record inspector, and production BigQuery Streaming Inserts mapping.

---

## Quickstart (Local Execution)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Generate deterministic 24-hour backfill (or run live 2-min daemon)
python -m src.mock_generator --mode backfill
# Optional standalone daemon mode:
# python -m src.mock_generator --mode daemon --interval 120

# 3. Launch the Real-Time Sales Tracker
streamlit run app.py

# 4. Run the automated 10-test verification suite
pytest tests/test_sales_tracker.py -v
```

---

## Assessment Deliverables Included

| # | Assessment Deliverable | File / Artifact |
| :- | :--- | :--- |
| **1** | Working tracker + automation | [Live App](https://holafly-realtime-sales-tracker.streamlit.app/) (`app.py`, `sql/views.sql`, `src/analytics.py`) |
| **2** | Mock data generator script | `src/mock_generator.py` + `src/config.py` |
| **3** | One-page operational guide | `deliverables/03_One_Page_Guide_Real_Time_Sales_Tracker.pdf` (Verified 1 page, LaTeX) |
| **4** | Short AI usage & validation note | `deliverables/04_AI_Usage_and_Validation_Note.pdf` (Verified 1 page, LaTeX) |
| **Bonus** | Executive presentation deck (Beamer) | `deliverables/05_Executive_Presentation_Real_Time_Sales_Tracker.pdf` (8 slides, 16:9 LaTeX Beamer) |
