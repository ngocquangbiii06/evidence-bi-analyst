# Release evidence index — Evidence-Driven AI BI Analyst

Checkpoint: 2026-09-29 (Windows), V1 final candidate. This index binds the release candidate to
the frozen scope in `docs/FLAGSHIP_EXECUTION_PLAN.md`. It is an evidence map,
not permission to publish, push, deploy, or enable application cloud LLM.

## Frozen product boundary

- One additive metric: `Revenue`.
- Two explicit non-overlapping periods; no implicit “last month” semantics.
- Dimensions: `Region` and `Product`.
- One bounded analytical-agent loop with three deterministic read-only tools.
- Findings are evidence-linked and independently validated; causal claims are
  out of scope.
- Power BI uses a fixed PBIP/PBIR layout; LLM layout selection is out of scope.
- Application cloud LLM default is `local_only`/OFF. The R6 live evaluation is a
  separately authorized synthetic evaluation path and is not application default
  behavior.

## Gate matrix

| Gate | Evidence | Result / boundary |
|---|---|---|
| R1 numerical/scope validation | `tests/test_finding_validation.py` | Accepted; wrong delta, fake ID, and wrong-scope evidence reject; known-answer positive cases pass. Detailed internal checkpoint records are not bundled. |
| R2 contracts/provenance/finalization | `README.md`; this index | Accepted historical contract; detailed internal checkpoint records are not bundled. |
| R3 bounded agent/offline harness | `README.md`; this index | Accepted historical offline harness; detailed readiness packet is internal-only. |
| R4 native Power BI candidate | Historical internal evidence | Accepted only for the exact historical Candidate revision; it is not transferred to R3 or R19. |
| R5 live evaluation revision R6 | Historical internal evidence | Historical synthetic evaluation record is preserved; it is not application default behavior. |
| Windows regression | `README.md`; this index | V1 final clean package run (2026-09-29): 440 passed, 2 documented Windows symlink-privilege skips; Ruff pass; pip check clean. Historical R3 package run: 404 passed, 2 skipped. |
| T19 reproducibility/learning | `README.md`; this index | Public quickstart and evidence boundaries are included; internal walkthrough records remain outside the public bundle. |
| R06/R07 Refresh_R3 (historical, superseded) | Internal records not bundled (`r06_build_r3_…`, `r07_engine_r3.json`, `r07_native_r3_reported.json`) | R3 static/build and engine checks passed (7/7 / 35 values); its later native check found three presentation defects, fixed in R19. Click/browser checks were `not_checked` for R3 and are now covered for R19 below. |
| R08 provisional package (historical) | Internal records not bundled (`docs/RELEASE_FILESET_R3.json`, `deliverables/evidence-bi-release-r3.zip`) | 236-file R3 package; superseded by the V1 final package. |
| V1-C02 native R19 (2026-09-29) | `deliverables/verification/v1_final_public/v1_native_20260929_attempt9_r19_native.json`; engine report `deliverables/verification/v1_final_public/v1_native_20260929_engine_attempt9_pid12816.json`; `media_r19_20260929/` | Observed via screen automation: 2 pages, signed colors, hidden scope metadata, 8 click cases + reset pass; engine 7/7 / 35 values. That check used cached data; the packaged artifact was then opened without cache, refreshed and re-verified (7/7 / 35 values): `deliverables/verification/v1_final_public/v1_final_c04_package_refresh_20260929.json`. |
| V1-C03 browser smoke (2026-09-29) | `deliverables/verification/v1_final_public/v1_browser_20260929.json` | Success/export, confirmation guard, stale-run clearing, coverage limitation, English+Vietnamese causal abstention observed. Vietnamese causal gate added (fix 1/1b, tests red→green). NEEDS_INPUT/PARTIAL covered by unit tests only. |
| V1-C04 final package | `deliverables/evidence-bi-release-v1final.zip` + sibling manifest `docs/RELEASE_FILESET_V1FINAL.json` | Built from exact tracked files + `docs/RELEASE_PUBLIC_EXTRA_FILES_V1FINAL.json` (R19 replaces R3; internal AGENTS.md excluded). The file/hash manifest cannot contain its own hash, so it is delivered **next to** the ZIP (not inside it); verify every archive entry against it. Built by calling `write_fileset_manifest`/`create_release_zip` from `scripts/package_release.py` with `PUBLIC_EXTRA_MANIFEST` pointed at the V1 final extras file; the script's own defaults (extras file and `release_id`) still name R3, so running it unmodified reproduces the historical R3 selection. R19 trees in the package equal the natively checked trees file-for-file once the local `.pbi/` folders (settings and data cache) are excluded; per-file hashes, the tree algorithm, the exclusion rule and the comparison result are in `deliverables/verification/v1_final_public/v1_final_c04_r19_identity.json`. `scripts/validate_powerbi.py` cannot validate R19 directly (Desktop saved report schema 3.3.0; bundled vendor schemas are 3.0.0). Not published. |

## V1 final candidate (R19)

The artifact to open is [`deliverables/PowerBI_Demo_Refresh_R19_allcorrect_scopeinvert_tmdl/EvidenceBI.pbip`](../deliverables/PowerBI_Demo_Refresh_R19_allcorrect_scopeinvert_tmdl/EvidenceBI.pbip). It keeps the R3 semantic model and fixes the three presentation defects found in the R3 native check (cross-highlight blanking, signed bar colors, visible scope metadata). Page-2 table-width readability remains a user-approved deferral.

## Superseded local dashboard refresh candidate (R3)

The superseded R3 artifact (`deliverables/PowerBI_Demo_Refresh_R3/EvidenceBI.pbip`, kept in the workspace and in the historical R3 archive, not in the V1 final package) was generated with the same semantic model. The R3 PBIR keeps the frozen model, bindings, visual IDs, pages, and canvas while applying the presentation-level projection formats confirmed by the offline review. Engine execution and reconciliation pass 7/7 contexts / 35 values.

The user reported `R3 pass` after opening and refreshing the artifact in Power BI Desktop. This is recorded as reported evidence, not a native Computer Use capture. For R3, native click-through cases, browser smoke and screenshot linkage were `not_checked` (now covered for R19 above). The historical R3 archive `deliverables/evidence-bi-release-r3.zip` is an internal record, not bundled with the V1 final package.

## Historical local dashboard refresh candidate (R2)

The dashboard presentation refresh R2 is retained as a historical comparison artifact. Its historical record describes the formatting, truncation, title-length and interaction-isolation changes observed at that time; those claims are not substituted for R3 or R19 native acceptance. The exact artifact is [`deliverables/PowerBI_Demo_Refresh_R2/EvidenceBI.pbip`](../deliverables/PowerBI_Demo_Refresh_R2/EvidenceBI.pbip); its native evidence is [`native-rendering-v2.json`](../deliverables/verification/dashboard_refresh_r2/native-rendering-v2.json).

Key verification results:
- **Engine verification**: [`engine.json`](../deliverables/verification/dashboard_refresh_r2/engine.json) passes **7/7 DAX contexts / 35 values** (reconciliation passed).
- **Static verification**: the historical static result confirms 21 schema files, 6 tables, 3 relationships, 5 measures, 12 bindings, and the PBIR allowlist; the internal static-verification record is not part of the provisional public bundle.
- **Native Power BI Desktop rendering**: 2 pages / 13 visuals observed and verified in Power BI Desktop (Version 2.157.1354.0 Store App).
  - Page 1 Overview screenshot: [`native-page1.png`](../deliverables/verification/dashboard_refresh_r2/native-page1.png) (SHA-256: `893823be4976a62734fcf54de9ffa1690c90f85d691ee6f2291fb52fafa99ac0`).
  - Page 2 Findings & Scope screenshot: [`native-page2.png`](../deliverables/verification/dashboard_refresh_r2/native-page2.png) (SHA-256: `66fb730b108c76e69bc5e7ee208539407cf37a54fdb7b0c1d8248fb167a0e4f1`).
  - Consolidated export PDF: [`EvidenceBI_Dashboard_R2.pdf`](../deliverables/verification/dashboard_refresh_r2/EvidenceBI_Dashboard_R2.pdf).
- **R2 historical improvements recorded (not R3 or R19 acceptance)**:
  - Monthly chart title shortened to concise `"Doanh thu quan sát theo tháng"`.
  - Narrative caveat regarding time-series observation clearly rendered in text box T02 without overflow or truncation.
  - The historical R2 record reports `wordWrap: true` on Findings (`E01`) and Scope (`S01`) headers/cells; this does not prove R3 or R19 table readability.
  - Page-level `visualInteractions` configured with `"NoFilter"` across data visuals to isolate selection clicks from altering overall KPI baselines.

### Historical dashboard refresh candidate (R1)

The superseded R1 candidate and its native evidence remain historical workspace records outside the provisional public bundle. It demonstrated 13 objects but retained truncation and title issues later addressed in the historical R2 revision. Neither R1 nor R2 overwrites `PowerBI_Demo_Current` or `PowerBI_Demo_Candidate`.


## R6 identity and hashes

| Artifact | SHA256 |
|---|---|
| `examples/evaluation/live_config.m5_20260925_r6_live.json` | `F31FCB4F5553269616FC0ED0DA67F9FEE3334F6B4783C37CE1400090F2724B0E` |
| R6 config identity | `727095713126DD543283B471640C7A5AE1DD86E275A8236B59D72592F90EBB58` |
| `deliverables/verification/t18_live_evaluation_r6_live/smoke.json` | `213DC09DD2F820A337E71C15F73846107D6AA79B3A4EDD4C9F21CB82F70F0ABE` |
| `deliverables/verification/t18_live_evaluation_r6_live/batch-report.json` | `EEC035DD63869A6EDA7A891344303A7CF5FB330EB1D61615B44C2EE638F9AA03` |
| `deliverables/verification/t18_live_evaluation_r6_live/attempts.json` | `1C08CDE11F1C2763DCB415005134BEC8E523BA575C59533F1EE27FA08D4014E6` |
| `deliverables/verification/t18_live_evaluation_r6_live/session.json` | `222541C176FB95DD27E2D0C73251EC809CD8C628CC0F57766873328D9FEF194F` |
| Local-only R6 bridge (not in public bundle) | Internal checkpoint only | The operational bridge remains outside the publish set. |

The R6 batch metrics are: agent choice **81/81**, tool numeric **276/276**,
evidence support **39/39**, investigation completion **24/24**, limitation
outcome **18/18**, required abstention **6/6**, unnecessary abstention **24/24**,
and unsupported-claim leakage **0/81 leaked**. Measured provider usage was
`$0.0327146`; durable reserved total was `$1.1124754` of the `$4.50` cap.
The local grader replay matched the stored report. This does not certify
exactly-once delivery at the provider.

## Reproducibility commands

From the project root in Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m pytest -q --tb=short
.venv\Scripts\ruff.exe check src scripts tests
```

The **359-node public collection** is a historical checkpoint (357 public tests
plus 2 documented Windows symlink-privilege skips). The historical extracted R3
package ran **404 passed, 2 skipped** with Ruff passing; the extracted worktree
used the existing project interpreter, not a newly provisioned `.venv`.

The current V1 final result: the clean run of the extracted V1 final package on
2026-09-29 (after the Vietnamese causal-gate fix) is **440 passed, 2 skipped**,
Ruff passing, pip check clean. The current artifact to open is
`deliverables/PowerBI_Demo_Refresh_R19_allcorrect_scopeinvert_tmdl/EvidenceBI.pbip`
(native check and engine reconciliation recorded 2026-09-29).

## Unresolved findings and explicit non-claims

- Historical R5 live batch remains `failed` and is preserved; R6 is the accepted
  fresh revision, not a rewrite of that record.
- R6 evidence proves unique local attempt/run records and write-once guards, not
  provider-side exactly-once delivery.
- R6 E04/E05 pass proves the new batch result; it does not prove that the
  prediction-recovery or Windows storage-retry branch was exercised in that run.
- Data is synthetic. Observed changes and segment contributions are not causal
  explanations.
- No production/SaaS/auth/multi-tenant/deployment claim is made.
- Screenshot archives are internal evidence by default; the eight R19 captures bundled in `media_r19_20260929/` were checked (Power BI window only, signed out, no account, email, machine path or taskbar; see `public_media_note` in the public native record). Redact local account chrome before any other public use.
- A scoped pattern scan over `README.md`, `docs`, `examples`, `src`, `scripts`,
  `deliverables/verification/t18_live_evaluation_r6_live`, and
  `tmp/m5_live_20260924` returned no `sk-...` matches. This is evidence that no
  secret pattern was found in those reviewed paths; it is not a proof about
  clipboard history, OS backups, or provider-side state.

## Hard stop condition

Stop application coding for V1 at this checkpoint. The frozen acceptance
contract, independent validators, bounded agent evaluation, Windows regression,
native R19 and browser evidence, and the V1 final package are recorded above. Do
not add SQL, metrics, datasets, agents, RAG, new orchestration, or Power BI
automation under this release candidate. Remaining: final package review, and
publication only when explicitly authorized.
