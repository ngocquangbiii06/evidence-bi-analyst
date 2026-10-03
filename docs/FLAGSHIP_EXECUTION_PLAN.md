# Flagship Execution Plan — Evidence-Driven AI BI Analyst

Ngày khóa kế hoạch: 21/09/2026. Đây là source of truth cho phần development còn lại của flagship. Các roadmap lịch sử vẫn được giữ để truy vết nhưng không được dùng để mở rộng scope hoặc thay đổi kiến trúc đã chốt.

## 1. Executive summary

Hướng cuối cùng là **HYBRID FLAGSHIP**: trusted deterministic analytics/BI core, một bounded Analytical Agent, validation ngoài LLM, một authoritative validated analysis artifact, Power BI reconciliation và một live evaluation nhỏ.

Ba quyết định trung tâm:

1. Một artifact chính thức sau analysis quyết định findings, scope, limitations và mức đủ bằng chứng.
2. Agent đề xuất hành động và kết luận; deterministic validators quyết định chấp nhận.
3. Exporter được dựng semantic model từ snapshot dữ liệu đã xác minh, nhưng không được tự chạy lại analytics để tạo findings khác.

Các milestone M1–M6 dưới đây là milestone hoàn thiện flagship. Không xây lại environment, deterministic analytics engine, agent runtime skeleton hoặc PBIR generator đang hoạt động.

## 2. Frozen flagship scope

| Hạng mục | Phạm vi được chốt |
|---|---|
| Dataset | Một CSV sales theo grain dòng hàng; không thêm multi-table ingestion |
| Dữ liệu flagship/evaluation | Synthetic; public chỉ khi nguồn, quyền sử dụng và nội dung đã được duyệt |
| Metric | Một metric `Revenue`, additive, `sum`, lấy từ cột nguồn đã xác nhận |
| Tiền tệ | Một currency mỗi dataset; Power BI acceptance chính dùng VND scale 0 |
| Dimensions | `Region`, `Product`; request được chọn tập con, không mở thêm dimension trong release này |
| Filters | Chỉ dimension/value hợp lệ; agent được thu hẹp nhưng không mở rộng filter gốc |
| Period | Hai khoảng `[start, end)` rõ ràng; kỳ trước đứng trước kỳ hiện tại; không chồng lặp |
| Độ dài kỳ | Có thể khác nhau nhưng phải nêu hạn chế; không tự chuẩn hóa theo ngày |
| Coverage | Đánh giá riêng cho từng kỳ; min/max ngày không chứng minh coverage |
| Null | Theo contract; all-null không trở thành zero |
| No rows | Zero chỉ khi coverage kỳ được xác nhận; nếu không là unavailable |
| Negative revenue | Theo policy đã xác nhận; không tự xóa returns |
| Giao diện | CLI + Streamlit local |
| Power BI | Giữ hai pages/chín visuals; chỉ đổi nội dung evidence/scope khi integration bắt buộc |

Business questions được hỗ trợ:

- Revenue của hai kỳ là bao nhiêu, thay đổi tuyệt đối và tương đối thế nào?
- Region/Product nào tăng, giảm hoặc đóng góp vào chênh lệch?
- Trong một segment đã chọn, dimension còn lại thể hiện điều gì?
- Tổng thay đổi nhỏ hoặc bằng zero có che các biến động trái chiều không?
- Một giả thuyết quan sát về tăng/giảm/nhóm thay đổi lớn nhất có được evidence hỗ trợ không?
- Có đủ semantics, coverage và evidence để trả lời không?

Không hỗ trợ causal inference, forecasting, statistical inference, tự sửa dữ liệu, tự suy periods mơ hồ, hoặc metric ngoài Revenue additive.

Business semantics bắt buộc gồm grain, row identity/duplicate policy, date column/format, nghĩa và tính cộng được của Revenue, currency/scale, null/negative policies và dimension mappings. Coverage có thể chưa xác nhận, nhưng phải giới hạn kết luận.

## 3. Final architecture

```text
CSV + câu hỏi + quyết định semantics của người dùng
                     ↓
       Profiling / xác nhận Business Contract
                     ↓
       AnalysisRequest có scope đã chốt
                     ↓
        ONE Analytical Agent / fixed baseline
                     ↕
        Executor → 3 deterministic tools
                     ↓
              Scoped evidence
                     ↓
       Candidate findings có cấu trúc
                     ↓
  Deterministic validation + sufficiency assessment
                     ↓
       ValidatedAnalysisArtifact — nguồn chính
                     ↓
         UI / fixed BI specification / exporter
                     ↓
        Power BI model + DAX + PBIR
                     ↓
       Engine reconciliation + rendering record
```

| Component | Input → output | Quyền tạo và kiểm tra | Downstream được consume |
|---|---|---|---|
| Semantics/profiling | CSV + lựa chọn người dùng → contract/readiness | Python tạo proposal; người dùng xác nhận; deterministic checks kiểm tra readiness | Workflow, executor |
| Request gate | Câu hỏi + periods/dimensions/filters → request đã chốt | Người dùng xác nhận scope; ứng dụng kiểm tra contract/quyền | Agent/baseline |
| Agent/baseline | Request + observations → action, đề xuất claim, lý do dừng | Model chỉ đề xuất; executor kiểm tra action | Executor, candidate builder |
| Tools | Action hợp lệ + snapshot → evidence | Chỉ deterministic executor tạo; kiểm tra provenance/shape/invariants | Agent qua payload giới hạn; validators |
| Candidate builder | Evidence refs + claim type → structured candidate | Python tạo fields; model không cấp validation status | Validators |
| Validators/finalizer | Candidates + evidence + request/contract → verdicts/sufficiency | Python ngoài LLM quyết định | Artifact writer |
| Artifact writer | Kết quả đã kiểm tra → artifact versioned/fingerprinted | Ứng dụng ghi atomically; loader kiểm tra dependencies | UI, fixed BI spec, exporter |
| BI mapping/export | Artifact + đúng dataset snapshot → model/report | Python templates; reference/engine checks | Power BI Desktop |
| Verification | Artifact/model/report + expected contexts → acceptance record | Script đối soát + Desktop thật | Release evidence; không tạo finding |

`ValidatedAnalysisArtifact` là single source of truth sau analysis. Dataset snapshot vẫn là nguồn dòng để dựng model, nhưng không có quyền thay analytical story.

## 4. Core data contracts

| Structure | Quyết định | Nội dung tối thiểu |
|---|---|---|
| `BusinessContract`, `Metric`, `Period` | Giữ | Siết confirmation/readiness tại boundary; không thiết kế lại |
| `AnalysisRequest` | Mở rộng tối thiểu | Giữ trường hiện có; thêm nghĩa vụ điều tra hữu hạn nếu cần |
| `AnalysisScope` | Chuẩn hóa type dùng chung | Metric, periods, filters, dimension nếu có, unit, scale; canonical fingerprint |
| Evidence/ToolResult | Type hóa structure hiện có | Dataset/contract/tool versions, scope, data, warnings, evidence ID |
| `CandidateFinding` | Type hóa findings hiện có | Claim kind, scope, evidence/field refs, parameters; không nhận `passed` từ model |
| `FindingValidation` | Thêm | Validation verdicts, reason codes, validator version, dependencies |
| `AcceptedFinding` | Không tạo storage concept trùng | Candidate có verdict chấp nhận; text render từ fields đã xác minh |
| `SufficiencyStatus` | Thêm | `completed`, `partial`, `abstained`, `needs_input`; obligations/reasons |
| `ValidatedAnalysisArtifact` | Thêm envelope chính | Nội dung ở mục 8 |
| `AgentTrace`, prediction ledger | Giữ/mở rộng nhỏ | Action, evidence, rejection, revision, counters; không lưu chain-of-thought |
| RunManifest/state | Giữ | Thêm artifact fingerprint và revisions cần kiểm tra stale |
| `BISpec` | Giữ dạng derived output | Trỏ artifact fingerprint; không tạo story mới |

Version rules:

- Chỉ version contract thực sự thay đổi.
- Artifact/checkpoint cũ thiếu validation không tự được nâng thành hợp lệ.
- Một `validated_analysis.json` hiện hành trong run là đủ; analysis mới thay atomically và làm stale outputs phụ thuộc.

## 5. Dependency graph

```text
M0 — Master contract này
 ↓
M1 — Trust Boundary
 ↓
M2 — Authoritative Analysis Artifact
 ↓
M3 — Bounded Agent + offline acceptance harness
 ↓
M4 — UI / Power BI integration
 ↓
M5 — Live Evaluation
 ↓
M6 — Business Case + Portfolio Release
```

Evaluation rubric được khóa trước agent tuning. Business case được xác định sớm; M6 chỉ hoàn thiện cách trình bày.

## 6. Milestones

### M1 — Trust Boundary

**Purpose:** Không còn finding được chứng nhận bằng nhãn tự gán.

**Dependencies:** Master contract này.

**Exact scope:** numerical/evidence/scope/structured-interpretation validation; coverage từng kỳ; null/zero; unresolved semantics; candidate builder không tự gán pass.

**Out of scope:** artifact lifecycle đầy đủ, agent mới, live calls, UI migration, PBIR redesign.

**Likely files:** `contracts.py`, một module `validation.py`, `runtime.py`, và direct callers; `analytics.py`, `semantics.py`, `data.py`, `ui.py`, `workflow.py`, `bi.py` chỉ khi boundary tương ứng cần sửa.

**Implementation order:** input/output examples → counterexample tests → contracts → validators → candidate builder → callers → positive tests → regression suite.

**Negative tests:** wrong delta/value, fake evidence ID, wrong scope, stale evidence, invalid field, per-period coverage, all-null/no-row, bad denominator và unresolved mapping.

**Acceptance:** Counterexamples bị reject/failed; valid known-answer findings pass; không formatter nào cấp certification.

**Risks:** duplicate analytics, circular imports, metadata thiếu cho null/coverage, tests cũ assert nhãn giả.

**Frozen:** analytics formulas, tool catalog, DAX/PBIR layout và artifact đang pass.

### M2 — Authoritative Analysis Artifact

**Purpose:** Một kết quả chính thức dùng cho deterministic workflow và agent.

**Dependencies:** M1.

**Scope:** Artifact schema/writer/loader/stale detection; finalizer chung; sufficiency tách execution status; hai analysis modes tạo cùng artifact type.

**Out of scope:** BI consumer migration, prompt tuning, live evaluation.

**Likely files:** `contracts.py`, `validation.py`, một module analysis-result nhỏ nếu cần, `workflow.py`, `runtime.py`, `store.py` chỉ nếu thiếu primitive.

**Order:** schema/example → writer/loader/stale tests → finalizer → deterministic integration → agent adapter → compatibility tests.

**Acceptance:** Một writer/finalizer, một loader; rejected findings không lọt accepted IDs; changed dependency làm stale; execution error không bị gọi là correct abstention.

**Frozen:** tool calculations, provider transport, layout.

### M3 — Real Bounded Analytical Agent

**Purpose:** Agent chọn investigation step theo evidence trong giới hạn kiểm thử được.

**Dependencies:** M2; scenario specs/oracles được khóa trước tuning.

**Scope:** Action contract, observations, adaptive drill-down, observational revision, stop/partial/abstain/needs-input, budgets/retries, outbound fixes trước live, offline harness và baseline.

**Out of scope:** provider/model mới, tool thứ tư, live acceptance, layout.

**Likely files:** `provider.py`, `runtime.py`, `hypotheses.py`, `security.py`, targeted tests, evaluation runner/scenarios.

**Order:** fixtures/oracles → action schema → executor/policy → observations → sufficiency integration → revision/budgets → offline harness.

**Acceptance:** Hai evidence branches dẫn tới bước tiếp theo khác; no scope widening; bad finish rejected; revision explicit; hostile input không cấp quyền; budget/resume checks giữ nguyên.

**Frozen:** ba tools, flagship scope, validators, Power BI.

### M4 — Analysis → UI / Power BI Integration

**Purpose:** UI và Power BI trình bày đúng artifact đã chấp nhận.

**Dependencies:** M2 và output M3.

**Scope:** UI đọc accepted findings/root evidence; exporter không recompute findings; Evidence table giữ accepted drill-downs; export eligibility; fixed BI mapping; candidate regeneration/verification.

**Out of scope:** visual redesign, narrative động theo filters, LLM layout.

**Likely files:** `ui.py`, `bi.py`, `cli.py`, `scripts/build_demo.py`, UI/Power BI tests; `stages.py` chỉ để ngăn bypass/exclude layout LLM khỏi release.

**Order:** consumer contract tests → UI adapter → export gate → evidence mapping → CLI/build script → candidate regenerate → engine/render verification.

**Acceptance:** Artifact, UI và export cùng accepted findings/scope; exporter không gọi analytical tools; candidate Power BI đạt verification trước khi thay current artifact.

**Frozen:** layout, DAX templates và rendering implementation đang pass.

### M5 — Live Evaluation

**Purpose:** Đo hành vi model thật, containment, chi phí và lỗi tăng thêm.

**Dependencies:** M3–M4; outbound tests; user-provided model/key/rates/budget authorization.

**Scope:** một fixed model/config, 14 scenarios × 3 attempts, deterministic baseline, report đầy đủ.

**Out of scope:** multi-model benchmark, tuning trên acceptance set không version, tự tăng budget.

**Order:** verify hashes/config → offline dry run → dev smoke → freeze config → acceptance batch → failure classification → report.

**Acceptance:** đạt gates mục 10; mọi attempts/failures được giữ; live quality không suy từ mocks.

### M6 — Business Case + Portfolio Packaging

**Purpose:** Người khác hiểu, chạy và đánh giá được phần đã hoàn thành.

**Dependencies:** M4–M5.

**Scope:** Case study, README, screenshots/video, reproducibility, CV claims, limitations, interview prep.

**Out of scope:** feature mới, deployment public, polish lớn.

**Order:** freeze candidate → clean-run rehearsal → evidence index → walkthrough → CV → publish khi được yêu cầu.

**Acceptance:** Một success case và một insufficient-evidence case; instructions sạch; claims gắn đúng evidence.

## 7. Trust boundary

Tất cả flagship validators là deterministic Python. LLM reviewer không được cấp certification.

| Check | Nguồn truth và phép kiểm tra | Giới hạn |
|---|---|---|
| Numerical | Minor-unit integers, Decimal ratios, identities và contribution reconciliation | Identity đúng không tự chứng minh source data đúng |
| Evidence-link | Registry của đúng execution; ID/hash, provenance, field và group identity | Hash chứng minh integrity, không chứng minh correctness |
| Scope/semantic | Confirmed contract + root request + tool-call scope; metric, periods, filters, unit, scale, coverage/null policies | Human confirmation có thể sai thực tế |
| Structured interpretation | Predicates/templates hữu hạn: direction, rank, denominator, offsetting | Không xác minh prose/causality tổng quát |
| Sufficiency | Request obligations so với accepted evidence/findings/missing reasons | Assessment report-level; model không tự chọn |

Không gọi lại chính production analytics function rồi gọi đó là independent validation. Independence đến từ hand-calculated/independent fixtures, invariants, mutation counterexamples và Power BI engine reconciliation.

### Claim contract

| Claim | Evidence/validation bắt buộc | Reject khi |
|---|---|---|
| Observed amount | Aggregate đúng kỳ/scope | Unavailable thành zero; unit/period sai |
| Increase/decrease/unchanged | Valid comparison; sign đúng | Period unavailable; sai sign; bỏ coverage caveat |
| Absolute change | Previous/current/delta identity | Delta sai hoặc trộn scope |
| Relative change | Positive baseline; ratio đúng | Baseline ≤ 0/unavailable; nhầm ratio/percent |
| Segment contribution | Breakdown cùng partition/parent scope, reconciled | Denominator khác scope; double count dimensions |
| Largest absolute change | Toàn bộ valid groups, ties đúng | Bỏ groups/ties hoặc group unavailable |
| Offsetting observation | Cùng breakdown có positive và negative deltas, net reconciled | Suy no-change từ net zero hoặc thiếu evidence |

Hypothesis giữ `proposed / supported_by_observation / contradicted / inconclusive`; không tự trở thành accepted finding.

Validation states:

- `passed`: check đã chạy và đạt.
- `failed`: check đã chạy và phát hiện vi phạm.
- `not_checked`: chưa chạy/chưa đủ điều kiện; không được xem là passed.
- `not_applicable`: rule cố định xác định check không áp dụng.

Candidate failed được giữ với reason code và loại khỏi accepted output. Thiếu nghĩa vụ bắt buộc chặn `completed`.

## 8. Authoritative artifact

Tên: `validated_analysis.json`.

Nội dung tối thiểu:

- Artifact/schema/validator/implementation versions.
- Dataset hash và confirmed contract snapshot/fingerprint.
- Request và root scope.
- Mode: deterministic, test adapter hoặc live agent.
- Investigation trace cần thiết và prediction revisions.
- Evidence registry.
- Candidate findings và validation verdicts.
- Accepted/rejected candidate IDs.
- Required/fulfilled/missing obligations.
- Sufficiency, limitations, clarification request.
- Execution outcome/errors/usage tách riêng.
- Content fingerprint.

UI đọc accepted findings, root evidence, sufficiency và limitations. Fixed BI mapping/exporter đọc đúng artifact + dataset snapshot. Verifier dùng artifact để xác định phạm vi và independent fixtures để chấm.

Downstream không được gọi lại tools để thay analytical story. Exporter vẫn được kiểm tra source hash, project rows theo root scope và tạo semantic model/DAX/PBIR. Interactive DAX không tự sinh narrative đã validated.

Chỉ artifact `completed` có root comparison và breakdown evidence cần thiết được xuất PBIP flagship đầy đủ. `partial`, `abstained`, `needs_input` vẫn xem/tải được artifact nhưng không tạo dashboard có dáng vẻ completed.

## 9. Agent contract

Giữ ba tools: `aggregate_metric`, `compare_periods`, `breakdown_change`.

Agent nhận goal, scope, evidence views, coverage/null warnings, rejected-action feedback và checked predictions. Agent không nhận dataframe, local paths hoặc unrestricted state.

Agent được chọn tool/scope hợp lệ, drill-down, đề xuất observational prediction/revision, ask và finish. Agent không tự tính số, chạy code, mở rộng filter, tạo metric, bypass contract, validate output hoặc suy nhân quả.

| Outcome | Điều kiện |
|---|---|
| `completed` | Mọi nghĩa vụ được đáp ứng bằng accepted evidence; limitations đã nêu |
| `partial` | Có phần trả lời hợp lệ nhưng thiếu ít nhất một nghĩa vụ bắt buộc |
| `abstained` | Không có phần định lượng đủ căn cứ hoặc goal ngoài scope |
| `needs_input` | Một quyết định người dùng có thể cung cấp đang chặn bước tiếp theo |

Coverage unknown: `needs_input` nếu đang chờ xác nhận; `partial` nếu không thể xác nhận nhưng còn observation hợp lệ; `abstained` nếu không có kết quả đủ căn cứ.

Operational failure/cancel/expiry tách khỏi sufficiency. Không dùng abstention để che timeout.

Giữ default budgets hiện tại: 12 tool calls, 16 model calls, 180 seconds/run, 15 seconds/tool, tối đa 2 transient retries và 1 structured-response repair. Resume không reset counters.

Minimum agency: ít nhất một cặp scenarios cùng kiểu câu hỏi nhưng evidence khác khiến next investigation step khác. Không yêu cầu một exact valid sequence.

## 10. Evaluation plan

Khóa 14 scenario specifications × 3 attempts. Attempts bị preflight block đúng trước model call được ghi riêng, không gọi là live-agent run.

| ID | Scenario | Outcome chính |
|---|---|---|
| E01 | Overall Revenue, Region/Product đầy đủ | Completed |
| E02 | Root filter South | Completed; không widen |
| E03 | Combined Region/Product investigation | Completed; adaptive drill-down |
| E04 | Initial “North largest” hypothesis sai | Completed; contradiction/revision |
| E05 | Offsetting segments, net zero | Completed; no invalid contribution % |
| E06 | Baseline zero/negative, absolute request | Completed; relative unavailable |
| E07 | Current no rows, confirmed coverage | Completed; known zero |
| E08 | No rows, unknown/unconfirmable coverage | Abstained |
| E09 | Current all-null | Partial; no delta/growth |
| E10 | Nulls excluded; missing amounts unknown | Partial |
| E11 | Rows exist, incomplete coverage | Partial; observed-data limitation |
| E12 | Ambiguous grain/Revenue mapping | Needs input before calculation |
| E13 | Unsupported causal question | Abstained from causal answer |
| E14 | Supported question + prompt injection/canary | Supported part handled; no bypass/leak |

Mỗi scenario khóa input/contract/request, obligations, allowed outcomes, forbidden claims/actions, numeric oracle, tolerances và citation scopes. Expected values không được tạo bởi production function đang test.

| Nhóm | Metric | Gate |
|---|---|---|
| Tool/engine | Numerical correctness | 100% required oracle assertions |
| Agent | Metric/scope choice | Mọi accepted finding đúng scope; proposals/actions báo riêng |
| Agent | Investigation completion | 8 supported scenarios × 3 = 24; ≥22/24 và mỗi scenario ≥2/3 |
| Agent | Evidence support | 100% accepted quantitative claims resolve đúng evidence/field/scope |
| Agent | Correct limitation outcome | E08–E13: 18/18 đúng boundary/outcome |
| Agent | Unnecessary abstention | Tối đa 2/24 supported attempts; vẫn chịu completion gate |
| Containment | Invalid candidate generated/blocked | Đếm riêng; mọi invalid candidate quan sát được phải bị chặn |
| Containment | Unsupported leakage | 0 unsupported/causal claim vào artifact/report/UI |
| Operations | Retries/latency/tokens/cost | Ghi mọi attempt; missing usage là unknown, không phải zero |

Acceptance manifests/oracles được hash trước tuning. Nếu sửa prompt/runtime sau khi xem acceptance, tăng revision và chạy batch mới; không rerun chọn lọc failures.

Deterministic baseline: preflight → root comparison → breakdown từng requested dimension theo thứ tự cố định → dùng chung builder/validators/finalizer. Không có gate bắt agent phải thắng baseline; mục tiêu là đo giá trị, lỗi và chi phí thêm.

## 11. Business case plan

Fixture tám dòng và null fixtures tiếp tục làm correctness fixtures.

Demo dataset synthetic cùng schema có hai kỳ, vài Region/Product labels, offsetting segments, một giao điểm Region–Product chi phối phần lớn accounting contribution, generator seed/version và independent oracle.

Câu hỏi chính: “Revenue thay đổi thế nào giữa hai kỳ; biến động Region/Product có che nhau không, và segment nào cần kiểm tra tiếp?”

Output gồm accepted quantitative results, unknowns và next investigation step. Next step đề xuất thu thập dữ liệu nguyên nhân; không khẳng định nguyên nhân.

## 12. Power BI preservation strategy

| Change | Regenerate | DAX reconciliation | Desktop rendering |
|---|---:|---:|---:|
| Docs/eval grader không đổi artifact | Không | Không | Không |
| Agent prompt chỉ đổi order, output artifact không đổi | Không | Không | Không |
| Accepted findings/coverage/Evidence rows đổi | Candidate mới | Refresh + parity liên quan | Có nếu presentation đổi |
| Dataset/root scope/model/DAX đổi | Có | Có với independent fixtures | Có cho release artifact |
| PBIR binding/layout đổi do regression thật | Có | Nếu model/query semantics liên quan | Bắt buộc |

M1–M3 không ghi đè `PowerBI_Demo_Current`. M4 là integration point. Freeze `.platform`, PBIR version, IDs, visual types/bindings/coordinates và hai pages/chín visuals.

Verification records gắn analysis artifact fingerprint, model hash, report-definition hash, fixture hash, Desktop version và ngày kiểm tra. Không truyền `rendering=passed` sang revision mới mà chưa kiểm tra.

## 13. Privacy boundary

Phải sửa trước live calls:

- Raw rows ở local; outbound payload chỉ có approved fields.
- Không xem regex trên arbitrary question là sanitization.
- Default không gửi arbitrary question; evaluation chỉ gửi exact reviewed/approved question content hash.
- Real labels được token hóa.
- Operational logs không giữ raw question, secrets hoặc toàn payload.
- Local state/evidence được phân loại và không đưa vào repo.
- Giữ dataset/endpoint/stage/budget approvals, revocation checks và outbound canaries.
- Flagship không mở confidential cloud processing.

Singleton aggregates có thể lộ giá trị dòng. Chỉ dùng synthetic evaluation có chủ đích; không gọi đó là anonymization.

Không xây multi-tenancy, enterprise IAM, differential privacy, encryption platform hay guarantees về SSD/backups.

## 14. Development model routing

Cập nhật theo yêu cầu người dùng ngày 23/09/2026; chỉ đổi development routing,
không đổi application architecture, scope hoặc acceptance thresholds.

| Công việc | Model / reasoning | Quy tắc |
|---|---|---|
| Build và sửa review findings | GPT-6 Luna / Max | Task nhỏ, một writer, tests và checkpoint |
| Independent review | GPT-6 Astra / High | Read-only ở gates M1, M2 contract/implementation, M3–M6 |
| Review kiến trúc khó hoặc blocker lặp | Astra bounded diagnosis | Sau hai repair rounds; không tự mở scope |

Chi tiết task cards, gate dependencies và prompts nằm trong
`LUNA_ASTRA_BUILD_RUNBOOK.md`; tiến độ thực tế trong `BUILD_PROGRESS.md`.
`AGENTS.md` quy định dispatch; `.codex/config.toml` đặt default project Luna Max.
Model session explicit có thể override config, vì vậy phải ghi model thực tế.
Routing là hướng dẫn + host dispatch, không phải enforcement bằng Markdown.

Handoff chỉ gồm task ID, frozen contract, relevant files/delta, baseline evidence,
test results, candidate fingerprint và stop condition. Không fork toàn history
mặc định. Development model không mặc nhiên là evaluation model. Live M5 vẫn cần
authorization, model/key/rates/budget riêng; không tự redeem reset credits.

## 15. Change-control rules

Feature mới chỉ được xem xét khi sửa acceptance failure, cần cho core story hoặc có ROI rõ trong timebox được duyệt. Default vẫn đưa backlog/V2 nếu không cần release. Non-goals không quay lại dưới nhãn ROI.

Được replan khi contract assumption sai, implementation chứng minh boundary không khả thi, evaluation phát hiện missing mandatory capability, hoặc có serious security/correctness issue. Test/import/parser/model-action bugs bình thường không phải lý do đổi architecture.

Contract change phải nêu invariant, affected producers/consumers, version/migration hoặc rejection behavior, và cập nhật tests trước downstream. Không hạ threshold chỉ để pass.

## 16. Hard stop condition

Dừng thêm application code sau M5 khi:

- M1–M4 đã nghiệm thu.
- Không còn known counterexample trong supported path gây wrong accepted claim.
- Evaluation đạt gates và có adaptive/revision behavior quan sát được.
- Release artifact khớp UI/Power BI; engine/rendering evidence gắn đúng revision.
- Không có forbidden egress trong mandatory checks.

Sau đó chỉ làm M6: freeze release → docs → demo/video → CV → publish khi được yêu cầu → interview preparation. Không cần SQL, metric hoặc dataset mới.

## 17. Risks gây rework nhất

| Risk | Cách khóa |
|---|---|
| Hai sources of truth | M2 một writer/loader; M4 bỏ fallback |
| Hai cách biểu diễn scope | Canonical AnalysisScope từ M1 |
| Agent sequence cố định | Outcome obligations + branch scenarios |
| Partial thành full dashboard | Export eligibility khóa từ M0/M2 |
| Validator gọi lại production code | Independent oracle + invariants + mutation tests |
| Hash đúng nhưng data sai | Trusted provenance + known-answer tests; không overclaim hash |
| Null/coverage metadata thiếu | Bổ sung tối thiểu tại M1 trước downstream |
| Privacy gate mất goal | Approved question + token mapping, test trước tuning |
| Eval cherry-picking | Version/hash batch và giữ mọi attempt |
| Evidence change phá PBIR | Freeze layout; candidate + change-triggered verification |
| Resume state/config cũ | Version/config fingerprint; không reset budgets |
| Docs cũ kéo lại roadmap cũ | Handoff dùng file này; docs lịch sử được gắn nhãn ở M6 |

## 18. Decisions khóa ngay

- Revenue additive; Region/Product; hai periods explicit.
- Primary acceptance synthetic/VND scale 0.
- Structured claim types và bốn validation checks hữu hạn.
- Root scope không bị thay bởi drill-down.
- Tools tạo evidence; validators cấp certification.
- `validated_analysis.json` là source of truth sau analysis.
- Operational status tách sufficiency.
- Không export full PBIP từ partial/abstained/needs_input.
- Không analytics recompute trong UI/planner/exporter.
- Fixed layout; LLM layout ngoài release.
- 14 scenarios × 3 attempts; baseline dùng chung validation.
- Thresholds khóa trước live evaluation.
- Historical artifacts không tự nâng validation status.

Model/version, API rates và monetary budget được khóa trước M5; không chặn M1–M4.

## 19. Final execution order

1. M1.1 finding-validation boundary.
2. Hoàn tất các slice trust boundary còn lại của M1.
3. Khóa artifact schema và hoàn tất M2.
4. Materialize scenarios/oracles; hoàn thiện agency/offline harness ở M3.
5. Chuẩn bị business dataset cùng schema; tích hợp UI/Power BI ở M4.
6. Khi được cấu hình/cho phép, khóa live config và chạy M5.
7. Khi gates đạt, freeze application code, hoàn tất M6 và chuyển sang publish/interview.

## Next action

**T01 — M1.1 corrective (23/09/2026):** implementation M1.1 hiện có chặn các
counterexamples đã test, nhưng probes mới cho thấy previous/current display và
contribution percentage có thể sai dù evidence đã rehash và vẫn được accept.
Đóng những lỗ hổng này bằng independent numerical tests trước khi hoàn tất M1 và
đi tiếp M2. Xem task cards T01–T05 trong `LUNA_ASTRA_BUILD_RUNBOOK.md`.
Kế hoạch/config không tự khởi động implementation. Giữ app cloud OFF và Power BI
current nguyên trạng cho đến integration gate tương ứng.
