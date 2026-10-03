# Hướng dẫn build flagship bằng Luna 6 Max, review bằng Astra

Ngày: 23/09/2026. Trạng thái: kế hoạch thực thi; không chứng nhận code đã hoàn tất.

## 1. Mục tiêu và thẩm quyền

Source of truth về sản phẩm vẫn là `FLAGSHIP_EXECUTION_PLAN.md`. Tài liệu này chia
nhỏ chính M1–M6, không thêm feature hoặc thay architecture. Nếu có xung đột, dừng
slice đó và đối chiếu master plan cùng yêu cầu mới nhất của người dùng.

Quyết định mới duy nhất về quy trình: **GPT-6 Luna / Max build; GPT-6 Astra / High
review độc lập**. High cho Astra là default tiết kiệm; không tự nâng Max/Ultra.
Đây là coding assistants, không phải agent được thêm vào ứng dụng BI.

Cho phép học sâu sau khi build: mỗi milestone phải để lại trace, test evidence và
giải thích quyết định ngắn để người dùng học lại. Không yêu cầu người dùng tự debug.

Đợt này chỉ đóng gói kế hoạch/config/docs. Build application chỉ bắt đầu khi người
dùng ra lệnh execute. Sau khi được giao cả batch, tiếp tục tuần tự qua các slice
đã đủ điều kiện; không hỏi xin phép lại ở từng slice.

## 2. Baseline cần hiểu đúng

- Theo lượt test trước: 105 passed, 2 skipped; hai skip là Windows symlink. Đây là
  kết quả lịch sử, không phải test được chạy lại trong lượt lập kế hoạch này.
- Power BI hiện hành đã được xác minh 2 pages/9 visuals, Refresh, 5 measures và
  reconciliation. Evidence cụ thể ở `POWER_BI_VERIFICATION.md`.
- M1.1 có candidate/validation types và validator, nhưng chưa đủ để khóa M1.
- Probe ngày 23/09 xác nhận: sửa `previous.amount` thành `999999`, giữ minor units
  rồi rehash evidence vẫn được accept; sửa `net_contribution_pct` thành `999999`
  rồi rehash cũng được accept. Đây là evidence nội bộ lỗi/giả lập, không phải
  bằng chứng model hiện có quyền ghi evidence. Hash chứng minh integrity, không
  chứng minh numerical correctness hoặc nguồn phát sinh đáng tin.
- Workspace chuyển máy hiện không có `.git`. Không dùng `git diff` làm điều kiện
  duy nhất để review. Chưa khởi tạo Git hoặc tạo commit trong lượt này.

## 3. Routing tự động: phần đã có và giới hạn

`.codex/config.toml` đặt default project mới là `gpt-6-luna` + `max`. Codex chỉ
load project config khi project được trust; lựa chọn model của session/CLI có
thể ghi đè default. File này không đổi model của lượt đang chạy.

`AGENTS.md` yêu cầu gọi reviewer Astra ở các gate bên dưới. Với host hiện tại,
dispatch hỗ trợ model/effort cụ thể. Reviewer nhận context mới, task packet và
file liên quan; không nhận toàn bộ lịch sử nhiều lượt theo mặc định.

Đây là orchestration theo hướng dẫn + dispatch của Codex, **chưa phải một runner
phần mềm cưỡng chế state machine**. Không claim rằng một file Markdown bảo đảm
mọi lần review đều chạy. Mỗi gate phải có reviewer thực tế, fingerprint và kết quả.
Không xây một framework orchestration mới chỉ để chạy project này.

Một phiên Luna Max có thể làm build trực tiếp rồi gọi Astra review; không cần mở
thêm một builder cho cùng việc. Nếu model của phiên không đúng, dùng Luna subagent
được pin rõ hoặc báo blocker. Không fallback sang API trả phí hoặc tự đổi model.

Đã kiểm tra CLI tại máy: `codex-cli 0.155.0-alpha.9.2`, có `exec --model`, `--config`,
`--skip-git-repo-check` và `--output-last-message`. Chưa chạy build bằng CLI.
CLI có thể chọn model rõ khi cần fallback; không cần tạo profile toàn tài khoản.
Không dùng hướng dẫn profile cũ `[profiles.name]` cho phiên bản này.

Nguồn OpenAI đã kiểm tra ngày 23/09/2026:

- [Chọn model, Luna hỗ trợ Max](https://learn.chatgpt.com/docs/models).
- [Subagents và delegation qua AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/subagents).
- [Project config, precedence và profiles](https://learn.chatgpt.com/docs/config-file/config-advanced).

Không cam kết tiết kiệm một tỷ lệ quota cụ thể hoặc hoàn thành trong đúng hai
reset. Reset Codex không thay cho permission/budget API của M5. Không tự redeem.

## 4. Giao thức áp dụng cho MỌI task card

1. Đọc checkpoint, task card, mục master plan liên quan; mở source đúng vùng cần.
2. Ghi pre-change hashes cho các file sẽ sửa và surfaces bị freeze. Nếu không có
   Git, tạo bản sao trước sửa của đúng file cần sửa trong local checkpoint riêng;
   không copy secrets/runtime dataset vào tài liệu review. Manifest liệt kê rõ
   file mới/cũ. Không dùng terminal log hoặc lời builder làm bằng chứng duy nhất.
3. Bug task: viết counterexample có oracle độc lập, ghi red result, rồi fix.
   Nếu test đã pass, kiểm tra vì sao; không cố tạo red giả.
4. Khóa representation/input/output tối thiểu trước consumer. Không tạo abstraction
   trùng `AnalysisScope`, `CandidateFinding`, `FindingValidation` hiện tại.
5. Implement nhỏ, positive và negative tests; targeted test sau mỗi slice.
6. Full pytest + Ruff tại gate milestone, không chạy full suite lặp sau mỗi edit.
7. Ghi task packet và chuyển gate; chỉ một writer, không sửa code khi Astra review.
8. Astra đưa finding có repro/file/ảnh hưởng; Luna sửa, test lại và Astra kiểm lại
   phần liên quan. Hai repair rounds tối đa trước bounded diagnosis; không tự loop
   vô hạn, tự thay contract hoặc hạ acceptance threshold.
9. Gate pass cần test evidence + review đóng issues + hash candidate khớp. Chỉ
   thay docs/status không làm mất code review; mọi thay đổi code liên quan làm gate
   stale và cần kiểm lại phần ảnh hưởng.

Trạng thái task: `pending → in_progress → tested → review_pending → accepted`;
thêm `blocked`, `changes_requested`, `stale` khi cần. Slice nằm trong một gate
chỉ được coi accepted khi gate đó đóng. Không dùng validation state của ứng dụng
để biểu diễn tiến độ development.

Files trong card là dự kiến được sửa, không phải yêu cầu phải sửa tất cả. Được
thêm test đúng slice. Mở rộng sang module khác chỉ khi có direct dependency cụ thể,
ghi lý do; redesign hoặc đổi contract đã khóa phải dừng để xử lý riêng.

## 5. Chuỗi thực thi và review gates

| Batch | Tasks | Gate Astra | Kết quả cần có |
|---|---|---|---|
| M1 | T01–T05 | R1 | Finding/semantics boundary đầy đủ trong scope |
| M2 contract | T06 | R2a trước downstream | Khóa schema, obligations, stale rules |
| M2 implementation | T07–T08 | R2b | Một finalizer/writer/loader cho cả hai modes |
| M3 | T09–T12 | R3 | Frozen fixtures, bounded agent, offline harness |
| M4 | T13–T16 | R4 | Artifact/UI/Power BI parity, native verification |
| M5 | T17–T18 | R5 | Live evidence khi được phép; nếu chưa thì blocked |
| M6 | T19–T20 | R6 | Reproducible release candidate và tài liệu học |

R0 là review bản kế hoạch hiện tại, không nghiệm thu implementation. Có thể
chuẩn bị nội dung T19 khi chờ M5, nhưng không close M6/full flagship trước R5.

### T01 — M1.1 corrective: amount/display và numerical identity

Đọc/sửa dự kiến: `src/bi_analyst/finding_validation.py`, `contracts.py` khi cần;
`tests/test_finding_validation.py`. Đọc `analytics.py`, `data.py` chỉ để hiểu output.

- Viết red tests cho previous/current display sai nhưng minor đúng và evidence
  rehash; delta display sai; candidate value sai trong khi evidence giữ nguyên.
- Kiểm cả previous/current/delta theo scale bằng phép kiểm độc lập; boolean,
  non-finite hoặc malformed numeric không được lặng lẽ coi là hợp lệ.
- Kiểm các giá trị mà finding thực sự phát biểu, không chỉ `delta`.
- Không gọi lại production compare để tạo expected answer. Không đổi công thức
  analytics hoặc template DAX.
- Positive oracle: 1000 → 600, delta -400; filter North: 300 → 150, -150;
  scale 2: 1.23 → 2.34, 1.11. Không chỉ assert “có records”.
- DONE: cả rehashed corruption lẫn candidate corruption bị reject, known answers
  pass; malformed input có typed failure/reason hoặc validation error được caller
  xử lý fail-closed, không crash toàn report hoặc biến thành accepted.

### T02 — M1.1 corrective: provenance/scope/linkage

Files: validator/contracts, direct `runtime.py` caller; finding/security tests.

- Counterexamples ID không tồn tại, field/index không tồn tại, wrong tool/group,
  wrong metric/period/filter/unit/scale/dimension; stale dataset/contract context.
- So sánh với trusted execution context truyền từ caller, không chỉ so candidate
  và evidence cùng tự khai một scope. Fingerprint tự rehash không phải authentication.
- Cho phép drill-down là subset root filters; phân biệt exact evidence scope với
  request root. Không reject mọi narrowed finding chỉ vì khác root.
- Chốt duplicate-ID semantics: cùng ID/cùng body có thể deduplicate; cùng ID khác
  body phải reject. Không để registry last-write-wins.
- Candidate không nhận certification; legacy report hoặc formatter không bypass
  validator. Chỉ sửa caller trực tiếp cần cho boundary; full UI migration ở T13.
- DONE: negative cases có reason, root và valid drill-down pass, context thiếu không
  thành passed. Không claim chống được người có toàn quyền sửa local files.

### T03 — M1 numerical contribution/structured claims

Files: validator/contracts, candidate builder hiện có, finding tests.

- Red test `net_contribution_pct=999999` với evidence rehash; sai overall denominator,
  thiếu group, sums không reconcile, trộn partition/filter, double count dimensions.
- Kiểm ratio với Decimal precision/tolerance được ghi rõ theo output tool hiện có;
  net=0/unavailable không sinh percentage. Growth chỉ khi positive baseline.
- Frozen claim predicates: amount, sign, delta, relative change, segment contribution,
  largest absolute change (ties), offsetting. Thêm representation tối thiểu chỉ khi
  type hiện tại không biểu diễn được; không thêm generic prose validator.
- Rank cần toàn bộ valid groups; offsetting cần hai dấu cùng partition và net
  reconciliation. Không gộp Region contribution + Product contribution thành tổng.
- Positive oracle: South -250/overall -400 = 62.5%; offsets +100/-100, net 0,
  tỷ lệ unavailable nhưng offsetting observation hợp lệ; ties không tự chọn winner.
- DONE: không còn field định lượng được accepted chỉ vì copy từ evidence, không
  đổi production formulas; limitation/interpretation rule được ghi theo claim.

### T04 — M1 coverage/null correctness

Files: validator/contracts; metadata tối thiểu trong `analytics.py`/`data.py` nếu
chứng minh đang thiếu; `test_analytics.py`, `test_data.py`, finding tests.

- Oracle matrix: rows hợp lệ/full coverage; rows/incomplete coverage; no rows với
  confirmed coverage; no rows/unknown; all-null; exclude-null với missing amounts.
- Check coverage theo cả hai period, không lấy boolean contract-wide thay thế.
  Không suy full coverage từ min/max ngày.
- Giữ distinction known-zero/unavailable. Observation partial phải mang limitation;
  không cấp complete-comparison claim khi dữ liệu không hỗ trợ.
- Giá trị hợp lệ vẫn có thể accept theo scope observed data, kèm limitation;
  report sufficiency để T06–T08 quyết định, không lặp finalizer tại đây.
- DONE: no-row confirmed có zero đúng; all-null không thành zero; warning bỏ mất
  không còn qua boundary; tests kiểm state/value/limitation, không chỉ text.

### T05 — M1 unresolved semantics và đóng R1

Files: `semantics.py`, `contracts.py`, `data.py`, `workflow.py`; chỉ form fields
liên quan trong `ui.py` nếu cần; semantics/data/UI tests.

- Missing grain/Revenue/date/dimension mapping không được auto-confirm bằng default
  first column + checkbox. Proposal không phải user decision.
- Preserve existing valid confirmed contract; unknown coverage không phải cùng lỗi
  với thiếu metric mapping. Unknown mà user giải quyết được → clarification.
- Tests: missing mapping dù confirmed flag true; stale mapping/dataset; valid known
  contract; không gọi analytics khi semantics bắt buộc chưa resolved.
- DONE R1: T01–T05 targeted + full regression + Ruff; Astra review numerical trust,
  scope, null/coverage, limitations và minimal contracts. Không regenerate Power BI.

### T06 — M2 contract/finalization design, R2a

Files: `contracts.py`, artifact examples/tests mới trong tests; cập nhật packet.

- Khóa `ValidatedAnalysisArtifact` đúng master §8: versions/context, root request,
  evidence registry, candidate+verdicts, accepted/rejected IDs, obligations, sufficiency,
  execution/errors/usage, fingerprint. Giữ một authoritative file mỗi run.
- Accepted không do caller truyền bool quyết định; finalizer lấy verdict thực tế.
- Khóa truth table completed/partial/abstained/needs_input riêng execution failure.
  E09 all-null current còn previous valid → partial; E08 không có phần trả lời hợp lệ
  và coverage không thể xác nhận → abstained; E12 unresolved mapping → needs_input.
- Obligations được tạo từ request/goal được approve trước investigation; không được
  tự thu hẹp sau khi thấy evidence. Unsupported causal goal không thành completed.
- Loader behavior cho legacy/stale/missing artifact phải explicit, không silently
  recompute hoặc upgrade. Fingerprint không self-reference; canonical fields rõ.
- Fixtures: completed, partial, abstained, needs_input, operational failure.
- DONE R2a: Astra review schema/producer-consumer examples trước writer/UI/export.

### T07 — M2 writer/loader và stale detection

Files: một module artifact/finalization nhỏ nếu cần; `store.py`, contracts; store tests.

- Atomic write bằng primitive hiện có; một writer/loader. Kiểm dataset, contract,
  request, implementation/validator versions cùng artifact hash theo dependency rule.
- Mutation tests từng dependency; old schema; interrupted write không phá bản cũ;
  accepted ID không tồn tại, rejected bị đưa vào accepted list phải bị phát hiện.
- Không coi content hash đủ chứng nhận verdict do file tự khai; loader áp dụng
  trusted manifest/version rules, revalidation khi cần theo T06.
- DONE: đúng snapshot load được; tampered/stale bị từ chối có reason; không có
  fallback tạo report mới ở loader.

### T08 — M2 common finalizer cho deterministic và agent, R2b

Files: artifact module, `workflow.py`, `runtime.py`; workflow/agent/finding tests.

- Cả hai modes dùng một finalizer; giữ rejected candidates và reasons. Không chỉ
  filter accepted rồi bỏ diagnostics như convenience `build_findings` hiện tại.
- Root evidence ID explicit; drill-down có own scope; enforce obligations và report
  outcome bằng deterministic rules. Model finish không tự chứng nhận completed.
- Legacy completed checkpoint thiếu artifact/version phải bị nhận diện, không
  bypass finalizer bằng return old agent_report.
- Tests: finalizer parity, missing required dimension, narrowed comparison đến trước
  root, only narrowed finish citations, timeout/cancel không bị gọi correct abstention.
- DONE R2b: clean/partial outputs có cùng schema, existing callers hoạt động;
  targeted + full regression + Ruff + Astra review dependency/acceptance boundary.

### T09 — M3 freeze scenarios và independent oracles

Files: evaluation specs/fixtures/tests nhỏ; chưa sửa prompt/runtime ở slice này.

- Materialize đúng E01–E14 master §10; 3 attempts mỗi scenario. Khóa obligations,
  allowed outcomes/actions, expected numbers, forbidden claims, hashes, tolerance.
- Supported set E01–E07 + E14 = 24 attempts. Boundary E08–E13 = 18 attempts.
- Chốt trường hợp ambiguous trước model call ghi preflight result; không đếm nó
  thành một live model success. Metrics tách preflight và model-exposed attempts.
- Development fixtures tách acceptance revisions. E03/paired development evidence
  kiểm adaptive branch; không thêm scenario ID để đổi denominator acceptance.
- DONE: oracle có phép tính tay/fixture độc lập; manifest hash khóa trước tuning;
  không lấy production function làm expected-value generator.

### T10 — M3 bounded actions/finish/revision

Files: `provider.py`, `runtime.py`, `hypotheses.py`; agent/hypothesis tests.

- Đúng ba tools; allowlisted dimensions/filters; cannot widen; deterministic executor
  tính số; model nhận rejected-action feedback và evidence views đủ để chọn tiếp.
- Làm observational hypothesis revision hữu hạn; free prose không lên accepted.
- Hai evidence branches cùng dạng question phải cho phép next step khác; scripted
  test chứng minh cơ chế runtime, không được gọi là live agency proof.
- Preserve 12 tools/16 model calls/180s/15s-tool, 2 transient retries/1 repair;
  resume không reset counters; changed config/version làm checkpoint stale.
- DONE: inappropriate finish, unsupported metric/code/causality, wrong evidence,
  scope widening, budget exhaustion đều xử lý rõ; không bắt exact tool sequence
  nếu alternative sequence đáp ứng obligations.

### T11 — M3 outbound prerequisites trước live

Files: `security.py`, `provider.py`, relevant trace/state writes trong runtime;
security/provider tests. Không build enterprise privacy platform.

- App default local-only giữ nguyên. Evaluation opt-in cần exact reviewed synthetic
  question hash/config, dataset/endpoint/stage/model/budget; arbitrary free text
  không được gọi sanitized vì đã chạy regex.
- Tokenized labels, approved aggregates/fields; hostile label/question không thành
  instruction; raw rows/secrets không có trong outbound/log.
- Kiểm approved question vẫn truyền đủ goal/metric intent, không bỏ goal để pass
  privacy tests. Canary tests ở transport và relevant process boundary; ghi rõ
  giới hạn test, không overclaim no-egress toàn hệ thống.
- Synthetic singleton aggregate không được quảng cáo anonymous. Revocation và
  missing rates/budget tiếp tục block. Không gửi confidential data.
- DONE: local/mocked tests pass, không live provider call.

### T12 — M3 offline harness/baseline, R3

Files: eval runner/graders/specs, relevant integration tests; runtime chỉ khi bug.

- Fixed workflow baseline dùng cùng tools/validators/finalizer, không LLM.
- Tách tool numeric, agent choice, evidence support, invalid proposal vs blocked vs
  leaked, abstention required/unnecessary, investigation, retry, latency, tokens/cost.
- Missing usage là unknown, không zero. Empty cases/zero executed assertions không
  tạo passing report. Attempt failures và timeouts có mặt trong denominator.
- Mocked transport/harness tests: malformed reply, retries, budget, unavailable model,
  interrupted batch/resume; không gọi mocked result là live eval.
- DONE R3: full offline E01–E14 baseline và scripted coverage; full tests/Ruff;
  Astra review oracle validity, metrics, privacy prerequisite, adaptive capability.

### T13 — M4 UI đọc artifact

Files: `ui.py`, `cli.py`, UI/workflow tests.

- KPI lấy explicit root evidence, không first comparison. UI findings chỉ từ accepted
  artifact; không `report.get('findings') or build_findings(results)` fallback.
- Hiện limitation, partial/abstained/needs_input, errors; download đúng artifact.
- Partial có accepted observation vẫn xem được; export PBIP completed bị chặn.
- Tests đặt narrowed North evidence trước root 1000/600/-400; root vẫn đúng.
- DONE: UI không tự recompute story, legacy/missing artifact hướng dẫn rõ; giữ layout
  Streamlit hiện có ngoài thay đổi cần cho correctness, không redesign.

### T14 — M4 exporter/BI mapping consume artifact

Files: `bi.py`, `stages.py` để đóng bypass, `cli.py`, `scripts/build_demo.py`;
Power BI/stage/workflow tests.

- Require eligible completed artifact và matching source snapshot; keep accepted
  drill-downs, scope/limitations và fingerprint trong Evidence/BISpec.
- Exporter được materialize model rows nhưng không gọi compare/breakdown để tạo
  findings. Test patch analytical tools thành failure khi export để bắt recompute.
- Missing/stale/partial/abstained/needs_input bị chặn full PBIP, không chỉ hide UI.
- Exclude LLM layout path khỏi flagship release; giữ fixed 2 pages/9 visuals.
- DONE: fixture evidence rows khớp authoritative accepted IDs/text/scope; old normal
  DAX contexts/model formulas không thay đổi không có lý do.

### T15 — M4 candidate demo và verification preparation

Files: synthetic demo fixture/generator cùng schema + independent oracle,
`scripts/build_demo.py`, relevant Power BI schema/reference verification scripts.

- Giữ 8-row fixture làm regression; synthetic business case cùng schema, seeded,
  có offsets và một intersection Region–Product nổi bật theo master §11.
- Export candidate riêng, ví dụ `deliverables/PowerBI_Demo_Candidate`, không ghi đè
  current. Lưu trước/sau manifest; PBIR page/visual IDs/types/positions/bindings freeze.
- Kiểm schema kể cả model structure, DAX references thật; không gán static passed
  tự động. Empty reconciliation cases phải fail; monetary comparisons exact theo
  oracle, growth tolerance explicit; model/report/fixture hashes được recompute.
- DONE: schema/reference checks + independent expected contexts chuẩn bị xong;
  execution/rendering mới vẫn not_checked cho đến T16.

### T16 — M4 Power BI Desktop thật, R4

Files: candidate và verification evidence; verifier scripts chỉ khi bug chứng minh.

- Mở candidate đúng Desktop instance; Full Refresh, 5 measures Ready; DAX contexts
  so independent oracle gồm root, dimension, intersection, date/no-row/null case
  liên quan. Không dùng port/model fingerprint của session cũ.
- Kiểm Business performance 8 visuals và Evidence & scope 1 visual, đúng numbers,
  labels/scope, không error. Bằng chứng native UI gắn candidate revision/Desktop version.
- Nếu không thể tự nhìn/tương tác UI, hoàn tất phần tự làm và đưa tối đa một thao
  tác manual; giữ rendering not_checked, không dùng schema pass thay thế.
- Chỉ promote candidate khi engine/reconciliation/rendering của revision đó pass;
  preserve recoverable current trước thay. User authorization build batch không
  đồng nghĩa quyền publish public.
- DONE R4: targeted/full tests/Ruff, native proof, Astra review UI/export parity
  và binding của evidence. M4 chưa done nếu native gate chưa kiểm chứng.

### T17 — M5 readiness (OFFLINE, làm được ngay khi dependencies đạt)

Files: evaluation config example/runner/docs, no credentials.

- Validate E01–E14 hashes, model/config versions, 3 attempts, cost estimator/ceiling,
  output path, local dry run, explicit opt-in và OFF mặc định.
- Phân biệt dev Codex Luna/Astra với model đánh giá của ứng dụng: không tự chọn
  evaluation model theo builder; không lấy Codex reset làm API budget.
- DONE: ready-to-run và blocked-live lý do rõ nếu chưa có model/key/rates/budget,
  không đọc/echo secret để chứng minh setup.

### T18 — M5 live run, CHỈ SAU AUTHORIZATION, R5

- Một approved model/config, dev smoke rồi freeze batch; 14 × 3 attempts; baseline.
- Gates: oracle 100%; accepted evidence/value/scope 100%; supported completion ≥22/24
  và mỗi scenario ≥2/3; boundary E08–E13 18/18; unnecessary abstention ≤2/24;
  unsupported/causal leakage 0. Preflight và live denominators báo riêng.
- Record mọi attempt, retries/failure/latency/tokens/cost, missing=unknown. Không
  rerun chọn lọc để cải thiện score; sửa runtime/prompt sau acceptance → revision
  và batch mới trong budget được phép, không tự tăng budget.
- DONE R5: gates đạt và Astra review evidence/denominators/claims; hoặc report
  failed/not_checked trung thực. M5 không được close bằng mocks hay đọc prompt.

### T19 — M6 reproducibility, learning pack, portfolio draft

Files: README, existing docs phù hợp, một walkthrough/learning guide; scripts chỉ
khi clean-run blocker được tái hiện. Không viết thêm app feature.

- Windows clean-run rehearsal theo dependencies/lock hiện có; không xóa environment
  đang dùng. Chứng minh một success và một insufficient-evidence case.
- Bộ học gồm: sơ đồ file có vai trò; trace question→tool→evidence→candidate→verdict
  →artifact→BI; 5 quyết định kèm lý do; walkthrough 10 phút; bài tập sửa small bug
  có đáp án; câu hỏi phỏng vấn và câu trả lời gắn code/test. Không yêu cầu thuộc code.
- README demo/screenshots/business case/limits, instructions tái lập và evidence index.
  Draft trước M5 được phép nhưng đánh dấu chưa có live acceptance.
- DONE: không copied claims 9/10, không production-ready/SaaS claim; mọi CV bullet
  khớp bằng chứng đã chạy; docs lịch sử ghi rõ superseded portions.

### T20 — M6 final release gate, R6 và STOP

- Astra review release-sized delta/evidence index và unresolved findings, không audit
  lại toàn repo. Chạy clean end-to-end + full regression/Ruff trên release candidate.
- Phải R1–R5 accepted; native evidence khớp hashes; cloud defaults OFF; no secret
  trong publish set; documented skips có lý do, không hidden failing tests.
- DONE: release candidate + học liệu hoàn chỉnh. Publish/push chỉ khi người dùng
  yêu cầu. Dừng thêm application code và chuyển học/interview; SQL/connectors,
  metrics mới, SaaS/auth/deployment vẫn ngoài scope.

## 6. Task packet và review contract

Mỗi handoff tối đa những gì cần thiết:

```text
Task ID / gate:
Model + effort yêu cầu / host-reported model:
Scope, dependencies, frozen invariants:
Files changed + before/after hashes (hoặc Git diff nếu có):
Contract/examples có thay đổi:
Counterexample trước/sau + independent expected values:
Lệnh test, exit/result, skips và hạn chế:
Open issues / stop condition / next task:
```

Astra trả `accepted` / `changes_requested` / `blocked`, theo gate chứ không theo
ấn tượng tổng quát. Mỗi finding có severity, file/line, trigger/input, expected vs
actual, impact và test nên thêm. P0/P1 và correctness issue trong scope phải được
đóng trước dependent milestone. Style-only hoặc V2 suggestions không chặn release.
Không dùng nhận xét “looks good” thiếu bằng chứng thay cho review record.

Review các gates nhắm đúng rủi ro: R1 numerical/scope; R2a contract; R2b provenance,
stale/sufficiency; R3 agency/egress/eval oracle; R4 consumer/native parity; R5 validity
của live measurements; R6 reproducibility và claims.

## 7. Prompts dùng trực tiếp

### Khởi động build liên tục

> Tiếp tục Evidence-Driven AI BI Analyst theo docs/FLAGSHIP_EXECUTION_PLAN.md và
> docs/LUNA_ASTRA_BUILD_RUNBOOK.md. Đọc docs/BUILD_PROGRESS.md để chọn task pending
> đầu tiên có đủ dependencies. Dùng GPT-6 Luna Max build và GPT-6 Astra High review
> đúng các gate trong AGENTS.md; ghi model thực tế, không tự đổi model. Tôi cho phép
> triển khai tuần tự T01–T17 và chuẩn bị T19 trong scope đã khóa, không hỏi lại sau
> từng slice. Không execute T18 live LLM, không redeem reset, không publish. Hoàn tất
> tests và review trước dependent milestone. Khi native UI thật sự cần tôi, đưa tối
> đa một thao tác manual; khi thiếu live authorization, ghi blocked-live và hoàn tất
> học liệu/portfolio draft làm được. Không claim toàn flagship done khi R5 chưa đạt.

### Astra review gate (handoff từ builder)

> Read-only review gate [R...] trên candidate có fingerprint [..]. Đọc task packet,
> relevant master contract và changed files/direct dependencies; không re-audit.
> Tìm false acceptance, scope loss, stale evidence, wrong null/coverage, evaluation
> contamination và test tự lặp implementation trong phạm vi gate. Reproduce cục bộ
> nếu cần; không sửa application, không live call. Trả verdict với concrete findings,
> line references và expected behavior. Không spawn thêm agents. Review code/evidence,
> không tin kết luận builder hoặc chỉ đếm test pass.

### Luna sửa sau review

> Xử lý findings có ID [..] của gate [..], giữ frozen contract. Reproduce mỗi bug
> bằng test, fix nhỏ nhất, chạy targeted và regression theo impact, cập nhật packet
> và fingerprint. Không sửa acceptance thresholds; không tự đóng review. Gửi lại
> Astra kiểm phần changed/affected trước chuyển milestone. Sau hai vòng còn lỗi,
> báo blocker cụ thể và xin bounded diagnosis, không loop vô hạn.

## 8. Định nghĩa hoàn tất và tối ưu quota

- Một task nhỏ có đầu vào/đầu ra và oracle rõ; không giao Luna “build toàn project”
  trong một lần context lớn. Parent giữ checkpoint, child chỉ nhận packet cần dùng.
- Không để Astra viết lại từng slice hoặc đọc toàn bộ repository; dùng review gate
  có mục tiêu, re-review affected changes. Không song song hai writer cùng source.
- Test evidence và immutable candidate giúp reviewer đọc ít hơn mà kết luận có căn cứ.
- Khi quota gián đoạn, lưu checkpoint/file hashes/test state; lượt sau tiếp tục đúng
  task, không audit lại. `tested` khác `accepted`, plan review khác code review.
- Completion là các gates được chứng minh; “đã sinh hết code” hoặc “hết reset” không
  phải điều kiện chuyển trạng thái. Cloud OFF cho đến T18 authorization; release
  candidate có thể sẵn sàng trước nhưng không tự nhận live evaluation pass.
