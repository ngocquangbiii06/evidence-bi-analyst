# Architecture Conformance Audit — Evidence-Driven AI BI Analyst

Audit completed: 21 September 2026. This records the final repository audit; recommendations are not implemented fixes. Code links use repository-relative paths for portability, with source line references corresponding to the audited version.

**The repository partially conforms to the intended architecture. The main failures are validation, scope preservation, and the handoff from analysis to BI—not excessive use of agents.**

I inspected the implementation, all test modules, documentation, and the current Power BI export. I reran the existing suite in a temporary environment: **93 tests passed in 10.10 seconds**. Targeted counterexamples exposed defects that those tests do not catch.

**No repository code or documentation was modified during the audit. No live LLM requests were made.** This audit and the handoff update were subsequently saved at the user's request; no fixes were implemented.

“Implemented” below means implemented within the current single-user, CSV/additive-metric scope. It does not imply production readiness or live-model acceptance.

| Requirement | Status | Evidence in code | Problem | Recommended fix |
|---|---|---|---|---|
| **1. LLM decides; deterministic tools calculate** | Implemented in agent mode | [Action schema](../src/bi_analyst/provider.py#L24), [tool dispatcher](../src/bi_analyst/runtime.py#L20) | The default workflow is fixed Python orchestration, not autonomous analysis. Live-agent behavior remains untested. | Keep deterministic and agent modes explicitly distinguished. |
| **2. Raw rows stay local by default** | Implemented by default | [local ingestion/storage](../src/bi_analyst/workflow.py#L32), [egress authorization](../src/bi_analyst/security.py#L39) | Power BI exports intentionally contain selected row-level data. Local-only does not make exported files anonymous. | Preserve the default and treat exports as sensitive data artifacts. |
| **3. LLM receives only sanitized metadata and aggregates** | **Partial; exception violates the strict requirement** | [payload construction](../src/bi_analyst/security.py#L180), [semantic payload](../src/bi_analyst/stages.py#L146) | `allow_question=True` sends arbitrary question text after a narrow regex check. A question containing an entire CSV row passes. Singleton aggregates expose individual values. | Use structured intent or explicitly reviewed/redacted text. Retain the confidential-data cloud prohibition until query-disclosure controls exist. |
| **4. Initially one autonomous Analytical Agent** | Implemented structurally | [AgentRunner](../src/bi_analyst/runtime.py#L125) | One loop exists; its analytical quality has only been exercised through scripted adapters. | Add behavioral acceptance evaluations without adding agents. |
| **5. Profiling and numerical analysis remain deterministic Python** | Implemented | [loader/profiler](../src/bi_analyst/data.py#L179), [analytics](../src/bi_analyst/analytics.py#L30) | No LLM calculation path found. | Retain this boundary. |
| **6. Every quantitative finding traces to deterministic evidence** | **Partial** | [evidence generation](../src/bi_analyst/analytics.py#L122), [finding construction](../src/bi_analyst/runtime.py#L75) | Normal findings contain evidence IDs and field paths, but the finding builder does not verify either. UI scope can also differ from the scope implied by its KPI presentation. | Resolve and validate evidence references before accepting or rendering findings. |
| **7. Separate numerical, linkage, and interpretation validation** | **Partial in structure; validators missing** | [hardcoded validation labels](../src/bi_analyst/runtime.py#L83) | All three statuses are assigned `"passed"` unconditionally. Three labels are not three validation processes. | Implement independent checks and records with method, scope, result, and failure reason. |
| **8. Explicit Business Contract** | Implemented within MVP scope | [BusinessContract](../src/bi_analyst/contracts.py#L45), [confirmation gate](../src/bi_analyst/data.py#L190) | The contract captures grain, metrics, dates, nulls, duplicates, currency, and coverage. Confirmation is an assertion, not proof that those semantics are correct. | Preserve human confirmation and record its provenance. |
| **9. Surface unknown semantic assumptions** | Partial | [unknowns and proposals](../src/bi_analyst/semantics.py#L60), [confirmation UI](../src/bi_analyst/ui.py#L195) | Proposals expose unknowns, but the form substitutes the first column for missing mappings and supplies default grain/currency/date format. A generic checkbox can accept these defaults. | Keep unresolved fields explicitly unset; require their resolution and preserve the decisions. |
| **10. Additive metrics first** | Implemented | [metric rejection](../src/bi_analyst/analytics.py#L38) | Non-additive types exist in the schema but are rejected by analytics. | Document them as unsupported, as the README currently does. |
| **11. BI Planner is structured generation, not another agent** | Implemented | [BIChoice](../src/bi_analyst/stages.py#L29), [single-call generation](../src/bi_analyst/stages.py#L104) | It is a constrained layout selector. However, it recomputes analytics rather than consuming validated findings. | Retain one-call generation; change its input boundary. |
| **12. DAX states: GENERATED → STATIC_VALIDATED → EXECUTED → RECONCILED** | **Partial** | [DAX validation fields](../src/bi_analyst/bi.py#L287), [verification script](../scripts/verify_powerbi.ps1#L49) | There is no enforced lifecycle. Reference validation is assigned `"passed"` without a separate checker. Engine results are separate files, not integrated transitions. | Implement artifact-bound validation records and controlled state transitions. |
| **13. Unexecuted DAX never described as fully validated** | Implemented for execution claims | [export manifest status](../src/bi_analyst/bi.py#L575), [README qualification](../README.md#L112) | Execution/reconciliation remain `not_checked`. However, “verified templates” and unconditional reference-pass labels overstate static assurance. | Keep execution qualifications; narrow the static-validation wording. |
| **14. Distinguish observation, contribution, hypothesis** | Implemented in a limited form | [finding types](../src/bi_analyst/runtime.py#L91), [prediction ledger](../src/bi_analyst/hypotheses.py#L13) | Formal findings distinguish observations and contributions; hypotheses are separate proposals/predictions. Arbitrary hypothesis prose is not validated. | Keep unsupported prose visibly separate from validated findings throughout downstream outputs. |
| **15. Abstain when evidence is insufficient** | Partial | [missing-value handling](../src/bi_analyst/analytics.py#L100), [ask/finish handling](../src/bi_analyst/runtime.py#L304) | `ask` produces `NEEDS_INPUT`; missing values are not fabricated. But there is no explicit abstention outcome or claim-specific sufficiency gate. Deterministic analysis can finish and export despite unavailable comparisons. | Add explicit abstention reasons and distinguish execution completion from answer sufficiency. |
| **16. Privacy applies to logs/state/evidence** | Partial | [RunStore](../src/bi_analyst/store.py#L69), [trace/report persistence](../src/bi_analyst/runtime.py#L360) | State and reports retain raw question text, real filter labels, results, and free-text model output. CLI prints full reports. POSIX permissions are not Windows ACL enforcement. | Separate sensitive analytical artifacts from minimized operational logs; define platform-specific storage protection and lifecycle rules. |
| **17. No arbitrary LLM-generated Python execution** | Implemented | [fixed dispatch](../src/bi_analyst/runtime.py#L20), [allowed action types](../src/bi_analyst/provider.py#L24) | No model-accessible `eval`, `exec`, shell, or arbitrary-code tool found. Worker processes are not an OS security sandbox, but no arbitrary model code is dispatched. | Preserve the fixed tool boundary. |
| **18. Hypothesis → plan → tool → validate → execute → observe → revise → stop/abstain** | Partial | [agent loop](../src/bi_analyst/runtime.py#L211), [prediction evaluation](../src/bi_analyst/hypotheses.py#L53) | Tool validation, observations, and revision exist. Hypotheses are optional; no explicit plan object exists; “overall first” is incompletely enforced; abstention is incomplete. | Add a short structured plan, enforce scope prerequisites, and evaluate stopping/abstention behavior. |

## 1. Current actual architecture

```text
CSV
 └─ Deterministic loader + local schema profiling
     ├─ Rule-based semantic proposal
     └─ Optional policy-gated, single-call LLM semantic proposal
          ↓
     Human-confirmed Business Contract
          ↓
     Ingested local run: raw CSV + contract + policy + profile
          ↓
     Deterministic Analytics Engine
          ├─ Fixed Python workflow
          └─ Optional Analytical Agent
               ↔ sanitized payload builder / provider
               ↔ aggregate / compare / breakdown tools
               → results + predictions + trace
               → template findings with automatic “passed” labels

Separately:
Ingested run → recompute analytics → optional one-call BI layout choice
Ingested run → recompute analytics → template findings → Power BI export
```

The important discrepancy is the **separate downstream branches**.

[BI planning](../src/bi_analyst/stages.py#L233) and [export](../src/bi_analyst/bi.py#L491) reopen the dataset and calculate new results. Neither requires a validated analysis report. Agent-selected drill-downs, revised hypotheses, and sufficiency decisions are not the authoritative input to BI.

**No responsibilities were unnecessarily implemented as autonomous agents.** Semantic review and BI planning are single-call structured generation. Python worker processes and the UI executor are execution mechanisms, not additional agents.

## 2. Intended architecture

```text
Raw data
 → deterministic loading / profiling / validation
 → privacy and policy enforcement
 → semantic discovery + explicit human decisions
 → Business Contract
 → deterministic analytics ↔ one Analytical Agent
 → candidate findings linked to evidence
 → numerical validation
 → evidence-linkage validation
 → interpretation-support validation
 → accepted findings / qualified partial answer / abstention
 → structured BI Planner
 → Power BI artifact
 → static validation → execution → reconciliation
```

Policy enforcement should apply at every relevant boundary, not only at one position in this diagram.

The missing architectural component is an **authoritative validated analysis artifact** that downstream consumers must use.

## 3. Gap analysis

### Validation can certify incorrect or unchecked content

I reproduced two distinct cases:

- Changing a comparison to claim `1000 → 600`, with a difference of `999999` and an invented evidence ID, still produced all three `"passed"` statuses.
- With the repository’s null-data fixture, the breakdown reported `numerical_validation="not_checked"`, while its generated contribution finding reported `numerical="passed"`.

The first is a direct finding-builder counterexample—not evidence that an external LLM can currently inject arbitrary findings. The second occurs with ordinary deterministic tool output.

Both demonstrate that [build_findings()](../src/bi_analyst/runtime.py#L75) is a formatter that presents itself as a validator.

Consequently, **normal findings are structurally traceable, but their correctness and interpretation are not independently certified**. A content hash establishes identity/integrity; it does not establish numerical truth.

### Scope is not preserved reliably in presentation

The agent can perform a filtered comparison before an overall comparison. The finish check eventually requires overall evidence, but the UI selects the **first** comparison using [this code](../src/bi_analyst/ui.py#L32).

I reproduced:

| Overall request | Expected overall KPIs | Displayed when North comparison comes first |
|---|---|---|
| Previous / current / change / growth | `1000 / 600 / -400 / -40%` | `300 / 150 / -150 / -50%` |

The loop also accepted a final action citing only the earlier narrowed evidence, although overall results existed. Evidence existence and evidence sufficiency are different checks.

Another confirmed scope error: when coverage includes January only, a February comparison correctly reports coverage as false, but exported `AnalysisInfo` still says **“Coverage: Confirmed”** because it uses the contract-wide Boolean. See [bi.py:264](../src/bi_analyst/bi.py#L264).

The Power BI Evidence table is also disconnected and contains static findings. It does not recalculate or select findings according to changing dashboard filters.

### The analysis-to-BI validation gate is absent

I successfully exported a run whose status was only `READY`, with no analysis report.

This is deterministic recomputation, not invented arithmetic. Nevertheless, it bypasses the intended sequence:

> findings → validation → BI Planner → Power BI

It also means BI export can omit the agent’s narrower investigative results and any decision to request more information.

A related boundary defect: a policy approving only `bi_planning` fails with:

> `STAGE_DENIED: Analysis is not approved for cloud processing.`

`plan_bi()` uses `PayloadBuilder.build()`, which additionally requires `analysis` approval. The stages are therefore not as independently authorized as their configuration suggests.

### Raw rows and sensitive information: the precise answer

- **Default application flow:** cloud calls are disabled. Raw dataframe rows are not serialized into LLM payloads.
- **Approved cloud flow:** category labels are tokenized; metadata and selected aggregate fields are reconstructed.
- **Free-text exception:** with `allow_question=True`, this text survived unchanged in the outbound payload:

  ```text
  Business data: 0001,O001,2026-01-05,C001,North,A,100
  ```

- **Aggregate disclosure:** a permitted North/Product A comparison sent `100` and `50`, each with `row_count=1`. These aggregates reveal individual record values.
- **Storage:** questions and real labels remain in local reports/state regardless of whether question transmission is permitted. CLI output can copy them into terminal/session logs.

These probes constructed payloads locally; they did **not** transmit them to a provider.

The synthetic/public dataset restriction materially limits the current exposure. It is not a general sensitive-data detector, and the README’s unqualified “raw rows … are not sent” wording is too broad.

### Power BI export is more than a specification, but execution is unproven

The current artifact contains:

- PBIP entry point and PBIR report definitions.
- `model.bim` with six tables and relationships.
- Embedded M data partitions, including eight fact rows.
- Five generated DAX measures.
- Report pages and visual bindings.

Therefore, the accurate classification is:

> **A generated Power BI project intended for execution, with execution and reconciliation not yet demonstrated.**

It is neither merely a JSON layout proposal nor a proven working Power BI report.

The schema validator’s [extension filter](../scripts/validate_powerbi.py#L21) excludes `.bim`. In a temporary copy, I replaced `model.bim` with invalid text. Validation still returned:

> **17 files checked, 0 failures.**

The prepared engine-verification script also needs auditing before being trusted:

- [Line 70](../scripts/verify_powerbi.ps1#L70) casts values to `double`, which cannot guarantee exact large-integer reconciliation.
- It hardcodes `Revenue` measures.
- An empty case list can produce a passing aggregate verdict.
- It copies the manifest fingerprint into the result without recomputing it from the model.
- It does not drive an application-level DAX validation lifecycle.

### What the existing tests actually establish

They test deterministic fixture arithmetic, several parsing failures, null/zero handling, filter restrictions, owner checks, policy revocation, malformed actions, worker timeout cleanup, structured proposals, and export file structure.

They do **not** establish complete architecture conformance.

| Test or test group | What it proves | Misleading or insufficient aspect |
|---|---|---|
| [Agent-loop test](../tests/test_agent_security.py#L120) | Scripted adapter exercises the loop and real workers | Its evidence-linkage assertion checks the hardcoded `"passed"` value. It does not independently validate linkage. |
| [Template causality test](../tests/test_agent_security.py#L202) | Expected number, field paths, and ID appear | Despite the name, it contains no substantive causality or interpretation-support assertion. |
| [Outbound aggregate test](../tests/test_agent_security.py#L86) | Particular fixture identifiers are absent | Does not test row text in questions, singleton disclosure, or all serialized fields at the transport boundary. |
| [Offline end-to-end test](../tests/test_store_workflow.py#L14) | Parent-process socket connection calls are blocked | The monkeypatch is not inherited by spawned Python workers. This is not process-wide proof of zero egress. |
| [Power BI schema test](../tests/test_powerbi.py#L37) | Selected JSON files satisfy vendored schemas | Does not validate `model.bim`, execute M/DAX, or check rendering. Its name is reasonable; treating it as model acceptance is not. |
| [Power BI null-context test](../tests/test_powerbi.py#L66) | Python produces expected null/zero semantics | Does not demonstrate those semantics in Power BI. |
| [Resume assertion](../tests/test_agent_security.py#L133) | A completed report can be retrieved again | Does not test recovery from an interrupted partial run or changed implementation version. |
| [Prediction revision fixture](../tests/test_hypotheses.py#L80) | The ledger preserves scripted contradiction/revision | Does not prove a real model notices contradictory evidence or revises appropriately. |
| [Local UI flow](../tests/test_ui.py#L9) | Default synthetic workflow renders expected KPIs and creates export | Misses agent-first narrowed scopes, insufficient-evidence presentation, and Windows execution. |
| [Date/null/negative/currency test](../tests/test_data.py#L139) | Several data-validation flags work | Despite “currency” in the name, it does not exercise currency mismatch. |

Important missing coverage includes independent finding-validation failures, wrong-but-existing citations, unsupported interpretation, abstention, budget exhaustion/retry sequences, interrupted resume, downstream validation gates, and Windows/native Power BI acceptance.

### Windows migration has an actual blocker

[default_root()](../src/bi_analyst/store.py#L22) calls `os.getuid()`, which is unavailable on Windows.

The call occurs while evaluating the default argument to `os.environ.get()`, so setting `BI_ANALYST_RUNTIME` does not avoid it. The UI calls `RunStore()` without an explicit root and therefore reaches this path.

CI currently targets [Ubuntu only](../.github/workflows/tests.yml#L5). The successful Mac tests do not establish Windows compatibility.

### Documentation claims requiring correction

- [README:82](../README.md#L82): “raw rows and real group labels are not sent” needs qualification for the free-text question path.
- [Generated Evidence status](../src/bi_analyst/bi.py#L247): “Numerically checked” is emitted unconditionally.
- [Generated BI specification](../src/bi_analyst/bi.py#L289): `deterministic_verified_templates` and `references="passed"` imply checks that are not independently performed.
- [Evidence-page title](../src/bi_analyst/bi.py#L476): “select EvidenceID to trace the calculation” overstates the interaction. It is a table column; no evidence-resolution/drillthrough implementation was found.
- [Implementation-status coverage table](IMPLEMENTATION_STATUS.md#L69): some claimed test coverage, including currency, is broader than the assertions.
- The planning documents describe validation records and broader failure handling as targets. Their “design requirements” disclaimers matter: those descriptions must not be cited as implemented behavior.

The README does explicitly disclaim live-LLM acceptance and Power BI execution. Those disclaimers should remain.

## 4. Top five highest-priority fixes

1. **Replace automatic validation labels with actual validation.**
   Validate arithmetic invariants, resolve evidence IDs/field paths, and check claim support separately. Unchecked or insufficient evidence must never become `"passed"` during formatting.

2. **Make a scope-aware validated analysis artifact authoritative downstream.**
   UI, planner, and export should consume that artifact. Fix first-comparison KPI selection, per-period coverage, citation sufficiency, and partial/abstained report handling. Preserve agent drill-downs rather than silently recomputing a different report.

3. **Close the free-text privacy exception and separate sensitive storage from operational logs.**
   Do not describe regex-checked questions as sanitized business context. Keep confidential cloud processing blocked; explicitly govern text, aggregate granularity, and retained content.

4. **Implement the DAX lifecycle and native acceptance gate.**
   Validate model structure/references, then execute and reconcile against independent fixtures. Bind results to model and fixture fingerprints. Fix the verifier’s numeric comparison and empty-suite behavior before using it as evidence.

5. **Make Windows execution and platform protection real, then test them.**
   Remove the Unix-only startup dependency, define Windows storage/ACL behavior, and add Windows tests. Run the actual PBIP through Refresh, DAX contexts, and visual checks before declaring the project operational on the destination laptop.
