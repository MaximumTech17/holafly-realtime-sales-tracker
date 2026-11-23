# Short Note: AI Tools Used & Output Validation Protocol

**Author:** Gabriel Andrés Salazar Espinosa | **Assessment:** Holafly Real-Time Sales Tracker MVP

---

## 1. AI Tools Used & Human-in-the-Loop Division of Labor

I used **Antigravity IDE (powered by Claude & Gemini coding models)** under a strict **Spec-First Engineering** workflow to deliver a production-grade MVP within the 3–4 hour budget:

| Component | Human Analyst Ownership (My Decisions) | AI Acceleration Role |
| :--- | :--- | :--- |
| **Architecture & WFM Domain Model** | Selected SQLite WAL + Streamlit Cloud over Google Sheets to guarantee `≤ 3m` latency without Apps Script quota limits; defined Holafly's 3 shifts (`COT`), 6 markets, 5 languages, 15-agent skill roster, and `3.50 orders/agent-hr` capacity benchmark. | Drafted structured trade-off matrix and production BigQuery Streaming Inserts / Materialized View mapping in `spec.md`. |
| **SQL Data Quality & Anomaly Math** | Specified the formal 4-gate definition of a **Valid Sale**, exact deduplication window function (`ROW_NUMBER()`), and the 30m-vs-180m anomaly formula with the `mu_base >= 10` minimum sample guard. | Generated `sql/views.sql`, `src/analytics.py`, and deterministic bucket-seeded `src/mock_generator.py` matching the spec 1-to-1. |
| **UI, Charts & Documentation** | Defined the 3-persona layout (Sales Manager, Coordinator, Agent) + Data Quality Audit tab, Holafly visual hierarchy, and evaluator simulation controls (`+ Simulate 2m Batch` & Scenario Selector). | Scaffolded Streamlit `@st.fragment(run_every="60s")` layout, Plotly charts (`app.py`), `pytest` suite, and ReportLab PDF builder (`scripts/build_pdfs.py`). |

---

## 2. Exact Validation Checks Performed on All AI-Generated Outputs

AI output was **never trusted blindly**. Every SQL rule, metric formula, UI render, and edge case was validated via an automated 15-test `pytest` verification suite (`tests/test_sales_tracker.py`) plus live end-to-end inspection:

1. **Deduplication & Uniqueness Audit (`T-02`):** Verified `COUNT(*) == COUNT(DISTINCT order_id)` on `v_valid_sales` and confirmed that injected 2nd and 3rd webhook retries are quarantined with `occurrence_rank > 1` and `dq_status = 'DUPLICATE'`.
2. **Real Sale Monetary Rule & Test-Account Exclusions (`T-03`, `T-04`, `T-05`):** Asserted `MIN(amount_usd) > 0.00` in valid sales (confirming `$0.00` failed captures and negative refunds are excluded) while verifying legitimate high-value B2B/group orders (`$640.00 > $500.00`) are accepted with no arbitrary upper cap; confirmed zero internal QA/staging emails and zero missing dimensions.
3. **Partition Conservation Reconciliation (`T-06` & `T-07`):** Verified exact row conservation (`Raw Records == Valid + Duplicates + Invalid_Amount + Test_Email + Missing_Dimension`, delta = `0`) and reconciled `Total Net Revenue / Valid Orders == AOV` directly against raw SQLite queries.
4. **Anomaly Detector True-Positive, False-Positive Guard & Organic Baseline (`T-08`, `T-14`):** Programmatically tested all four operational scenarios: verified `CRITICAL DROP` fires on the active mid-shift drop, `SURGE` fires on the `FLASH20` campaign spike, `NORMAL` holds on healthy organic baseline traffic (`std >= 1.2`), and alerts are suppressed when filtering to small slices (`mu_base < 10.0`).
5. **Latency SLA, Midnight Shift, Cloud Boot, UI HTML Integrity & PDF Audit (`T-09`–`T-15`):** Verified live sync achieves `Freshness Lag <= 3.0 minutes`, validated `SHIFT_3_NIGHT` (`22:00–05:59 COT`) across midnight on full UTC timestamps, verified ephemeral container boot recovery, caught and fixed a Markdown 4-space HTML indentation bug so zero raw HTML leaks to the UI (`T-15`), and programmatically asserted via `PyMuPDF` that both LaTeX PDFs render at **strictly 1 page** with **0 emojis**.
