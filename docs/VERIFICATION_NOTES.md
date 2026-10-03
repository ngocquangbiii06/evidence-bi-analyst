# Verification notes

Detailed verification records for the Power BI artifact and the Streamlit UI. Revision labels
(R2, R3, R19) are internal build revisions; R19 is the current one.

## Power BI artifact (R19)

The artifact to open is
[`deliverables/PowerBI_Demo_Refresh_R19_allcorrect_scopeinvert_tmdl/EvidenceBI.pbip`](../deliverables/PowerBI_Demo_Refresh_R19_allcorrect_scopeinvert_tmdl/EvidenceBI.pbip).
Open it in Power BI Desktop and Refresh (the model loads embedded data; no cloud connection).

- **Format**: PBIP with PBIR report and TMDL semantic model (same semantic model as R3).
- **Engine verification (2026-09-29)**: **7/7 DAX contexts / 35 values**, reconciliation passed, on the running R19 Desktop session.
- **Native Desktop check (2026-09-29, observed via screen automation)**: both pages render; negative bars red, positive bars teal; technical scope metadata hidden; clicking any Region, Product or month keeps the KPI cards, the other breakdown, the monthly chart and the narrative at root values; root reset works. Screenshots: [`page 1`](../deliverables/verification/dashboard_refresh_r3/media_r19_20260929/r19_page1_business_overview.jpg), [`page 2`](../deliverables/verification/dashboard_refresh_r3/media_r19_20260929/r19_page2_evidence_scope.jpg); record: [`v1_native_20260929_attempt9_r19_native.json`](../deliverables/verification/v1_final_public/v1_native_20260929_attempt9_r19_native.json).
- **Package open + Refresh (2026-09-29)**: the R19 folder from the release ZIP (no local cache) was opened in Power BI Desktop, refreshed, and verified again: both pages render and the engine reconciles 7/7 contexts / 35 values. Record: [`v1_final_c04_package_refresh_20260929.json`](../deliverables/verification/v1_final_public/v1_final_c04_package_refresh_20260929.json).
- **Known limitation**: page-2 table widths still truncate long cells.

R3, R2, Candidate, R1 and Current artifacts are historical baselines. R3 is superseded because its
native check found three presentation defects that R19 fixes.

## Browser smoke (Streamlit, 2026-09-29)

Observed in a local browser: completed analysis and Power BI export; the semantic-confirmation guard; a new session clears the previous result; unconfirmed coverage keeps observed results with an explicit `COVERAGE_UNKNOWN` limitation; causal questions in English **and Vietnamese** ("Vì sao…", "Tại sao…", "Nguyên nhân…") abstain with export disabled. The causal gate is keyword-based: some rephrasings are not caught, and a few descriptive questions containing the same words abstain (fail-safe). Record: [`v1_browser_20260929.json`](../deliverables/verification/v1_final_public/v1_browser_20260929.json).
