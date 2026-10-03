# Release repair — runbook chi tiết cho model nhỏ

Ngày lập: 26/09/2026. Cập nhật sau review Gemini: **CHANGES REQUESTED**.
Lượt cập nhật này chỉ sửa tài liệu; không thực hiện application build.
Mục tiêu: hoàn tất regression, chất lượng dashboard và khả năng tải repo về chạy
được; sau đó dừng phát triển. Lượt lập kế hoạch chỉ tạo tài liệu và chạy diagnostics.

## Checkpoint hiện hành sau lượt repair offline — 26/09/2026

Đây là trạng thái dùng để giao task tiếp theo; các mô tả cũ bên dưới chỉ là
history/reference và không được dùng thay cho checkpoint.

- R00–R03 và OFFLINE đã được kiểm bằng evidence mới và Astra High chấp nhận.
  Workspace và clean package đều đạt **404 passed, 2 skipped**; package có 194
  entry khớp manifest/hash; Ruff và `pip check` đạt. Native Power BI, browser
  smoke và publication vẫn chưa được chứng nhận.
- R04 **blocked / not_checked** vì Computer Use trả
  `Trusted RPC service is not configured: sky`. Chưa có Desktop-saved
  known-good reference nên không được bắt đầu R05a/R05b presentation repair.
- Route đã chốt: builder **gpt-5.6-luna/max** cho bounded implementation; reviewer
  độc lập **gpt-6-astra/high**, read-only, context mới. Host identity phải ghi là
  `unknown` nếu runtime không cung cấp; không tự nhận primary edit là Luna-host.
- Bước kế tiếp không phải thêm feature: hoàn tất một thao tác native tối đa một
  lần để đưa scratch PBIP vào foreground; sau khi có reference mới giao R05a →
  R05b cho Luna theo allowlist. Nếu UI connector vẫn thiếu, giữ R04 blocked và
  không reset repair-round counter.

## Bản cập nhật đang có hiệu lực — đọc trước các C-cards lịch sử

- Đọc [RELEASE_REPAIR_R3_ADDENDUM.md](RELEASE_REPAIR_R3_ADDENDUM.md) và
  `RELEASE_REPAIR_PROGRESS.md` (tài liệu nội bộ, không phân phối). Đây là đường thực thi
  hiện hành R00–R08; C00–C11 bên dưới chỉ còn là acceptance/reference chi tiết.
- Không chạy lại C01/C02 như lỗi chưa sửa: review mới xác nhận master hash đúng,
  UTF-8/inventory đã sửa; full workspace suite **389 passed, 2 skipped**, Ruff pass.
- Còn sáu findings: public ZIP không sạch; CI collection lỗi; formatting/readability
  chưa đạt; interaction guards thiếu; native hash linkage chưa đủ; gate claims
  mạnh hơn bằng chứng. Xem addendum cho repro, allowlists và task tests.
- R2 và evidence R2 hiện có được giữ read-only để đối chiếu. Artifact sửa mới dùng
  **Refresh_R3**, không chạy các lệnh C07 cũ vào R2 đang tồn tại.
- Hai review gates hiện hành: **OFFLINE**, **FINAL**. Native reference là prerequisite
  phải có trước sửa presentation, không phải quyền tự bỏ qua review hoặc UI.
- Không lấy mục “complete/ready_for_publication” trong checkpoint lịch sử làm
  prerequisite. Acceptance hiện hành là `changes_requested`; chỉ execute khi user giao.

## 0. Cách dùng và thẩm quyền

- Product contract: `FLAGSHIP_EXECUTION_PLAN.md` cho analytical invariants.
- Presentation amendment: `DASHBOARD_REFRESH_LUNA_PLAN.md`, đặc biệt §3 và §V1.
- Runbook này xử lý acceptance còn thiếu; không mở lại M1–M6, không redesign.
- Checkpoint ngắn cho batch mới: `RELEASE_REPAIR_PROGRESS.md`. Đọc thêm phần cuối
  `BUILD_PROGRESS.md` để biết lịch sử; không đưa cả file 3.000 dòng vào mỗi task.
- Chỉ khi người dùng giao **execute** mới sửa source/tests/artifacts theo task cards.
  Kế hoạch này không tự cho phép push/publish, chạy live LLM hoặc overwrite lịch sử.
- Sau execute, một writer làm tuần tự. Reviewer đọc candidate đã đóng băng.
- Builder mặc định `gpt-5.6-luna/max`, reviewer `gpt-6-astra/high`. Host phải báo
  identity thực tế; prompt/config không chứng minh đã đổi model.
- Có thể giao cùng cards cho Gemini bằng host người dùng chọn. Tên chính xác
  “Gemini 3.8”, quyền dùng, tools và mức reasoning **chưa được xác minh** trong
  phiên này. Không tự thay alias, không cài provider/SDK vào project để đổi builder.
  Không suy từ việc đổi coding assistant sang việc đổi application LLM/evaluation.
- Nếu dùng host Gemini không có Astra delegation: builder dừng ở `review_pending`,
  giao packet cho một phiên Astra riêng. Không tự viết verdict thay reviewer.
- Sau **hai repair rounds cho cùng failure mode** vẫn fail: dừng card, giữ diff,
  ghi trigger/expected/actual và diagnosis request. Không tự đổi Sol hay hạ tiêu chí.

Hướng dẫn OpenAI đã tra ngày 26/09/2026 xác nhận Luna 5.6 hỗ trợ `max`:
[model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna).
Đây không phải bảo đảm tốc độ, chi phí tài khoản hay khả năng sửa mọi lỗi.

## 1. Baseline lịch sử trước Gemini — không phải checkpoint hiện hành

### 1.1 Regression thực tế

Lệnh từ workspace Windows:

```powershell
.\.venv\Scripts\python.exe -m pytest -q --tb=short
```

Kết quả mới ngày 26/09: **367 passed, 2 skipped, 19 failed; 96,42 giây**.
Tổng 388 test instances; hai skip do Windows symlink privilege.
Đây là workspace, không phải public archive hoặc CI mới.

| Nhóm | Số failures | Nguyên nhân đã xác minh | Kết luận sửa |
|---|---:|---|---|
| Evaluation harness | 1 | Frozen master-plan hash khác manifest | Khôi phục tài liệu frozen, giữ amendment riêng |
| Evaluation scenarios | 1 | Cùng mismatch master plan | Không đổi expected hash để làm xanh |
| Live readiness | 3 | Offline integrity gate fail từ cùng mismatch | Giữ trong default offline suite |
| Live evaluation tests | 13 | Cohort/preflight bị block bởi cùng mismatch | Đây là mock/offline tests, không cần API key |
| Stages | 1 | `read_text()` dùng cp1252 đọc PBIR tiếng Việt | Explicit UTF-8; còn assertion cũ phía sau |

Probe riêng đã chạy:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests/test_stages.py::test_llm_layout_stage_and_export_bypass_are_disabled -q --tb=short
```

Kết quả **1 failed**, ở `assert len(visuals) == 9`, actual **13**. `-X utf8`
chỉ dùng chẩn đoán để lộ lỗi tiếp theo; không phải fix thay cho encoding explicit.
Không quy 19 test failures thành 19 application bugs độc lập.

### 1.2 Bản frozen có thể phục hồi mà không sửa evaluator

- `examples/evaluation/acceptance_manifest.json` chứa 16 entries.
- Chỉ một entry mismatch: `docs/FLAGSHIP_EXECUTION_PLAN.md`.
- Expected SHA256: `d176b0172ee8465155fd4eb2a4c5d96c8e5e72340704f3aa2200577871b89a67`.
- Actual SHA256: `d76e62b2398c373e5fab2ee5514c84ca691ff3b58c418f72c58f83714a7d9196`.
- `git show HEAD:docs/FLAGSHIP_EXECUTION_PLAN.md` có đúng expected bytes/hash.
- Diff chỉ là appendix `## Post-v1 — Yêu cầu chỉnh dashboard (25/09/2026)`.
  Probe cắt đúng appendix đó trong memory cho expected hash; chưa sửa file.
- Tất cả 16 frozen inputs hiện dùng LF, không CRLF; `core.autocrlf=true`.
- Canonical manifest SHA giữ nguyên:
  `1b69d5d301dd2e750f36ec11ce94c0e94b42f1d4ca1578021968ee1c9691994e`.

Default đã chốt: chuyển appendix sang tài liệu amendment riêng, rồi restore
frozen master bytes bằng patch có kiểm tra hash. Không thay manifest/runtime
pin/test oracle, không sửa lại kết quả live R6. Historical development-routing
text trong frozen docs được supersede bởi AGENTS/config hiện hành.

### 1.3 Rendering có dữ liệu chưa phải full V1 acceptance

Hai ảnh người dùng gửi chứng minh hai trang đã populated và KPI đúng số.
Engine record chứng minh 7/7 contexts, 35 values. Tuy nhiên:

- Growth đang hiển thị `6.4%`, thiếu dấu + và chưa đạt 2 decimal theo mẫu.
- Positive change/bar labels chưa có dấu +; bars giảm vẫn cùng teal với tăng.
- Tiêu đề monthly bị ellipsis, làm mất caveat về hai điểm quan sát.
- Bảng page 2 chưa wrap: Finding/ScopeLabel bị cắt, Status nằm ngoài viewport.
- Scope table vẫn hiện dataset hash, fingerprint, raw root-scope JSON.
- Footer page 2 bị crop trong ảnh; ảnh chưa chứng minh toàn bộ footer đọc được.
- `interactions=not_checked`; layout manifest có `pbir_static_encoding=null`.
- Người dùng gửi ảnh, **không có câu xác nhận Refresh hoàn tất** hoặc ảnh Refresh
  dialog. Trường `completed_as_reported` và `refresh_warnings_after_completion=false`
  trong record cũ mạnh hơn evidence thực có. DAX trả được kết quả không chứng minh
  thao tác Home→Refresh cụ thể đã được quan sát hay 5 measures UI Ready.
- Chưa có public archive/clean install regression của revision refresh, PDF R1
  đầy đủ, README canonical mới. Không thể gọi whole V1 hoặc batch là DONE.

Review Astra trước đó accepted **visible rendering/packet consistency**;
không dùng verdict đó thay toàn bộ acceptance §V1. Giữ ảnh/record R1 làm lịch sử,
tạo correction note mới có scope rõ. Không lặng lẽ chỉnh evidence cũ thành pass/fail mới.

### 1.4 Public packaging cần sửa thật

- `.git` hiện tồn tại, HEAD local `c58df7a1b58497489a8ee2f6452cc5ae5093458f`.
  AGENTS vẫn có câu “lacks .git”; sửa câu đó trong housekeeping, không init lại Git.
- Workspace dirty: source/dashboard/docs/CI đã sửa; tests bridge lịch sử có
  tracked deletion chủ đích. Không reset, checkout --, git add . hoặc clean.
- `examples/evaluation/live_config.example.json` tồn tại nhưng **untracked**,
  trong khi offline tests trực tiếp cần nó.
- `.gitignore` hiện bỏ qua `deliverables/verification/dashboard_refresh_r1/`.
  Đưa link vào README không tự làm file có trong public archive.
- Nhiều run_store/baseline/live configs local tồn tại dưới đường dẫn khác nhau;
  không copy cả deliverables hoặc git add -f cả verification.
- CI hiện chỉ Ubuntu. Windows encoding/line endings phải được kiểm riêng.

## 2. Phạm vi đóng băng và quyết định mặc định

Giữ Revenue additive; Region/Product; hai periods explicit; ba tools; một agent;
independent validators; no causal claims; cloud OFF; synthetic fixtures.
Không sửa `analytics.py`, finding validators, finalizer, runtime/provider/security,
evaluation thresholds, DAX expressions/formatString hoặc semantic relationships.

Read-only surfaces, trừ task card nêu rõ:

- `deliverables/PowerBI_Demo_Current/`, `PowerBI_Demo_Candidate/` và `PowerBI_Demo_Refresh_R1/`.
- R1 screenshots/static/engine/native records; mọi historical R5/R6 live evidence.
- Acceptance manifest + scenarios/oracles/16 pinned files; exception duy nhất là
  restore master-plan bytes đã chứng minh ở C02.
- Hai repair rounds P1 cũ đã hết; batch mới sửa failure modes cụ thể được ghi ở
  đây, không dùng nó để lặp lại vô hạn các P1 stale-provenance repairs đã accepted.

Các default giúp builder khỏi hỏi lại:

1. Bản sửa dashboard mới: `deliverables/PowerBI_Demo_Refresh_R2/`.
2. Evidence mới: `deliverables/verification/dashboard_refresh_r2/`.
3. Public-facing default chỉ chuyển sang R2 **sau gates pass**. Giữ Candidate
   cũ làm baseline cho comparator/tests; không đổi tên hay overwrite Current.
4. 2 pages, 9 data visuals + 4 text objects; giữ IDs/roles/bindings đã khóa.
5. Tiếng Việt cho labels giao diện, tên Region/Product values giữ đúng data.
6. Money đủ chữ số và VND theo contract; delta có dấu; growth 2 decimals.
   `+6.36%` hoặc `+6,36%` theo locale đều chấp nhận, không scale ratio hai lần.
7. Page 2 ưu tiên đầy đủ scope/findings, cho cuộn **dọc** nếu cần. Không co font
   bé để ép hết, không dùng tooltip làm cách duy nhất đọc ScopeLabel.
8. Không triển khai mới translation engine/narrative AI. Có thể giữ findings
   tiếng Anh đã validated; chuyển prose tự do sang tiếng Việt là V2.
9. Bộ phát hành có ảnh, PDF đầy đủ và PBIP; sample PBIX là optional, không block.
10. Không chạy lại live evaluation để sửa documentation/presentation bugs.

## 3. Quy trình tiết kiệm context và quota

Mỗi card là một context/task packet. Không giao “sửa tất cả lỗi project”.
Một slice nên chạm tối đa 1–3 source/test files; docs/checkpoint có thể thêm.
Nếu vượt allowlist, chỉ đọc direct dependency để nêu lý do; không tự refactor.

Mẫu vòng làm việc:

1. Đọc Cxx + progress ngắn + đúng source region/test. Kiểm tra prerequisites.
2. Ghi requested/actual model, pre-change file hashes, test node IDs.
3. Chạy reproduction hiện có. Nếu không fail, kiểm tra revision và giải thích;
   không thêm assertion giả để tạo red.
4. Sửa minimum; giữ các negative tests vẫn reject và positive tests pass.
5. Chạy targeted tests. Full suite chỉ ở gates hoặc khi lỗi mới cần điều tra.
6. Ghi diff summary, commands/exit codes, before/after, limitations, next card.
7. Ở gate: freeze candidate, Astra read-only; writer không sửa khi review chạy.
8. Finding cụ thể → tối đa 2 repair rounds → targeted rerun → re-review phần đổi.

Status: `pending → in_progress → tested → review_pending → accepted`, hoặc
`blocked`, `changes_requested`, `stale`. Code/style/schema passed không tự cấp
native rendering/interaction acceptance. `not_checked` không bao giờ là pass.

Reviewer phải nhận card, diff/hashes, lệnh/repro và artifacts liên quan; không
fork toàn history. Native UI và docs/CI không cần trả tiền application API.

## 4. Dependency và review gates

| Card | Nội dung | Phụ thuộc | Gate |
|---|---|---|---|
| C00 | Baseline + correction phạm vi nghiệm thu | Không | Kiểm hồ sơ |
| C01 | UTF-8 + assertion đúng inventory | C00 | A cùng C02/C03 |
| C02 | Restore frozen master, tách amendment | C00 | A |
| C03 | Public inputs + LF + test reproducibility | C01,C02 | Astra A |
| C04 | Desktop-saved reference cho formatting/interactions | C00 | B contract trước code |
| C05 | Fix readability/formatting generator | C04 | B |
| C06 | Fix interaction isolation generator | C04,C05 | B |
| C07 | R2 build, invariant checks, regression | C03,C05,C06 | Astra B |
| C08 | Native R2 + Streamlit acceptance | C07 accepted | Native subgates |
| C09 | Public media + canonical README/evidence | C08 đạt | C |
| C10 | Clean distribution + Windows/Linux CI config | C09 | C |
| C11 | Final independent review, release handoff | C10 | Astra C |

C04 nếu thiếu native UI thì ghi dependency, vẫn hoàn tất C01–C03 trước.
Được chuẩn bị allowlist/docs skeleton của C09–C10 trong lúc chờ UI; không ghi pass.
Không chốt release khi C08 blocked dù offline tasks đã xong.

## C00 — Baseline, preserve và correction note

Đọc: progress hiện tại, runbook này §1–4, dashboard plan §3/§V1.
Được ghi: `RELEASE_REPAIR_PROGRESS.md`, append `BUILD_PROGRESS.md`,
`deliverables/verification/dashboard_refresh_r2/planning-baseline.json` mới.
Không sửa source/old verification ở card này.

Thực hiện:

1. `git status --short`, `git rev-parse HEAD`; liệt kê dirty files là baseline
   người dùng đã có, không nhận chúng là thay đổi của batch này.
2. Ghi SHA256 source sẽ chạm, pinned master/manifest, Candidate/Current/R1 trees,
   source PNGs và native R1 record. Dùng `scripts/build_demo.py::_tree_sha256`
   cho tree hash, nêu thuật toán; phân biệt `.pbi` cache phát sinh với source.
3. Ghi baseline mới nếu source đã thay so với plan. Không ép số 388 khi tests mới.
4. Append correction: `visible_content_observed=true`, whole V1 còn pending,
   readability có failures; interaction, Refresh completion/Ready còn thiếu proof.
   Nêu rõ user screenshots không phải user statement về Refresh.
5. Mark build instructions không tự đổi historical R1 record. Correction reference
   được dẫn từ progress/release index ở C09, giữ provenance của record cũ.

DONE: baseline rõ, không mất user changes; next C01/C02. Không lặp full suite nếu
source hash chưa đổi từ lần diagnostics trong plan, chỉ ghi reference kết quả đó.

## C01 — Fix test reader UTF-8 và obsolete layout expectation

Đọc/sửa: `tests/test_stages.py` test
`test_llm_layout_stage_and_export_bypass_are_disabled` (~72–109).
Đọc-only: `bi.py::build_report`, `tests/test_powerbi.py` inventory assertion.

Repro 2 tầng đã có ở §1.1. Sửa:

1. Dùng `read_text(encoding="utf-8")` cho PBIR JSON trong test này.
2. Giữ tất cả asserts về `STAGE_DISABLED`, không gọi adapter, không có `bi_plan`,
   `BI_LAYOUT_DISABLED` khi cố bypass. Đây là mục đích security test.
3. Thay assertion 9 tổng bằng inventory đúng của fixture có cả 2 dimensions:
   13 objects = 9 data visuals + 4 textboxes; không chỉ `len >= 9`.
   Phân loại bằng `visualType`/query; không tính expected bằng chính builder.
4. Không replace mọi số 9 toàn repository: legacy Candidate vẫn 9 data visuals.

Kiểm tra:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_stages.py -q --tb=short
.\.venv\Scripts\ruff.exe check tests/test_stages.py
```

Không giữ `-X utf8` trong lệnh acceptance để che reader bug. Không sửa application
writer vốn đã xuất UTF-8, không đổi Windows locale toàn máy.
DONE: test thông thường pass, assertions bảo vệ bypass nguyên nghĩa.

## C02 — Restore frozen input integrity, giữ amendment

Được sửa: `docs/FLAGSHIP_EXECUTION_PLAN.md` đúng appendix cuối; tạo
`docs/DASHBOARD_PRESENTATION_AMENDMENT.md`; cập nhật reference trong progress.
Đọc-only: manifest, evaluator verifier, scenario tests, git version master.
**Cấm sửa** `acceptance_manifest.json`, `FROZEN_EVALUATION_MANIFEST_SHA256`,
`tests/test_evaluation_scenarios.py`, scenarios/requests/contracts và live R6.

Trình tự khóa:

1. So git diff; chỉ tiếp tục default này khi khác đúng appendix đã nêu. Nếu khác
   cả frozen analytical scope thì dừng card và báo diff cụ thể.
2. Chép nguyên nội dung appendix sang amendment mới bằng apply_patch; thêm
   authority/date/link đến dashboard plan và runbook này ngoài frozen file.
3. Patch xóa đúng appendix trong master, giữ LF/UTF-8/final newline. Không dùng
   `git checkout --` hoặc ghi đè toàn file từ HEAD làm mất thay đổi chưa xem.
4. Hash master phải đúng `d176...1b89a67`, canonical manifest giữ `1b69...1994e`;
   tất cả 16 entries phải match. Không thêm backlink vào master sau khi restore.
5. Negative tamper checks sẵn có vẫn reject; không monkeypatch integrity gate
   để chạy baseline. Nếu cần regression mới, dùng file test mới không nằm trong
   16 pinned files, chạy mutation trên bản sao tạm, không sửa fixture gốc.

Chạy:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation_scenarios.py tests/test_evaluation_harness.py tests/test_live_eval_readiness.py tests/test_live_evaluation.py -q --tb=short
```

Nhóm tests tên live ở đây dùng fake adapters/offline behavior, giữ trong suite.
Không gọi `scripts/run_m5_live.py`, không đọc key, không cần billing setup.
Các pin/version lỗi còn lại nếu xuất hiện sau restore phải diagnose riêng; không
auto re-pin config lịch sử. DONE: 18 failures cũ được xử lý bằng nguyên nhân gốc,
hoặc có repro nhỏ cho lỗi mới chưa thể thấy trước.

## C03 — Public inputs, LF và default test contract

Allowlist: `.gitattributes` mới, `.gitignore` đúng rules public, `AGENTS.md`
đúng câu .git lỗi thời, `examples/evaluation/live_config.example.json` nếu cần
sanitized content. `pyproject.toml`/tests chỉ khi chứng minh test discovery bug;
không thêm default exclude/xfail/skip cho 18 tests nêu trên.

1. Include OFF example config trong release input allowlist vì tests cần file đó.
   `live_enabled=false`, credential values không có, không copy operational
   `live_config.m5_*.json` có authorization/live_enabled vào default release.
2. Thêm `.gitattributes` **chỉ các 16 manifest paths** `text eol=lf` (và manifest
   khi cần) sau khi xác nhận chúng đang LF như probe. Không global renormalize,
   không sửa core.autocrlf của tài khoản. Không chạy git add --renormalize .
3. Bảo đảm tests vẫn collect đầy đủ, historical private bridge giữ local-only
   như G0; không hồi sinh nó chỉ để có count 382.
4. Sửa câu AGENTS “lacks .git” thành kiểm tra thực trạng; giữ routing/scope rules.
5. Kiểm trên một clean export gồm current selected working-copy bytes, không chỉ
   `git archive HEAD` đang thiếu dirty fixes. Nêu rõ cách chọn file ở §6.
6. Full pytest + Ruff. Nếu chỉ sửa 19 failures mà chưa thêm test, dự kiến **386
   passed +2 skipped**; đây là dự đoán, không là acceptance count cứng.

Gate Astra A: frozen integrity restored không nới verifier; UTF-8+inventory đúng;
OFF config portable; negatives còn hiệu lực; full suite 0 failures và Ruff pass.
Không chấp nhận kết luận “19 failures unrelated nên release xanh”.

## C04 — Lấy native reference trước khi đoán PBIR properties

Được tạo: scratch Desktop copy ngoài Current/Candidate/R1; reference packet
`docs/design/dashboard_refresh_r2_reference.md`, sanitized reference JSON snippets
và `docs/design/dashboard_refresh_layout_r2.json` mới. Chưa sửa generator.
Đọc: `bi.py::_visual/_textbox/build_report`, vendor schema liên quan, R1 manifest.

Trong bản scratch của đúng report, dùng Power BI Desktop hiện có:

1. Set một Change card đủ dấu + và một Growth card 2 decimals/dấu + bằng
   visual-level formatting; giữ measure expression và model formatString.
2. Bar formatting theo sign: positive teal `#087F72`, negative `#B54734`, zero
   neutral; label signed. Dùng native rule từ existing Change measure; không
   tạo color measure/DAX mới hoặc hardcode màu theo nhãn North/South.
3. Bật word wrap cho values/headers của Evidence/AnalysisInfo; chỉnh column widths.
   Dùng visual-level Property filter ẩn Dataset/hash/fingerprint/Root analysis
   scope JSON, giữ human scope/period/coverage/limitation. Không xóa model rows.
4. Desktop Edit interactions: chọn từng bar và monthly chart, set none tới mọi
   overview data visual khác. Không nhầm drillFilterOtherVisuals với cross-filter.
5. Save **scratch** project; diff trước/sau cho từng action một. Record Desktop
   version, exact JSON path/property/value, screenshot behavior. Không lấy whole
   Desktop reserialization và gọi mọi thay đổi là required.
6. R2 manifest giữ canvas/IDs/roles; chỉ thêm allowlist properties đã thấy.
   Không upgrade schema hàng loạt. Nếu property đúng version chưa đủ, ghi exact
   schema incompatibility để Astra diagnosis, không suy rendering từ schema.

Gate contract B-pre: review packet phải khóa structures và expected behavior
trước khi downstream edit. Khi native UI không có: pause C04 tại một thao tác
người dùng cụ thể, vẫn làm offline độc lập; không đoán property “có vẻ đúng”.

## C05 — Sửa readability/formatting trong generator

Prerequisite: C04 có reference. Allowlist: `bi.py` presentation functions,
`tests/test_powerbi.py`, R2 layout manifest. Chia hai commits/diffs logic nếu lớn:
**C05a cards/bars/month** rồi **C05b evidence/scope**. Một writer.

C05a:

- Apply visual-level native properties có reference; K03 `+60,000`, K04 `+6.36%`
  (locale tương đương); no auto K/M cho cards. Không đổi DAX formatString để fix.
- Positive/negative bars có màu phân biệt và dấu số; labels đủ chỗ.
- Monthly title ngắn `Doanh thu quan sát theo tháng`; caveat đặt ở text object
  sẵn có với vùng đủ rộng. Với demo hai tháng nêu hai điểm/chưa kết luận xu hướng.
  Generator generic không hardcode “2” cho dataset có nhiều tháng; dùng wording
  trung tính nếu không có count trusted, không thêm aggregation/tool mới.
- Giữ months order đúng Jan→Feb; verify label không bị tooltip chụp ảnh che.

C05b:

- E01 wrap Finding/ScopeLabel, đủ bốn cột FindingID/Finding/ScopeLabel/Status;
  có thể vertical scroll cho scope dài. Không mất filter/null/empty semantics.
- S01 visual filter chỉ giấu technical rows, giữ nguyên model/M/evidence data.
  Coverage không đổi thành “dữ liệu được chứng minh hoàn chỉnh”.
- Tiêu đề/column alias tiếng Việt nếu native reference cho phép; underlying query
  field names/refs giữ nguyên. Không dịch lại candidate.text bằng model.
- T04 không crop trong full page; default 1280×800, đọc được fit-to-page tại
  1366×768. Ưu tiên wrap/width/space, không giảm font tới mức ảnh khó đọc.
- Giữ root/narrowed scope distinction; không giới hạn 7 findings cố định hoặc
  lấy demo values thay accepted artifact để vừa bảng.

Tests meaningful:

- Existing known answers/card ratio/roles/IDs pass; negative/null/zero/scale2
  labels giữ nghĩa; stale/missing artifact không trở thành ready.
- Test presentation mapping đúng native reference và legend/sign semantics.
  JSON assertions chỉ chứng minh emit property, **không** chứng minh Desktop dùng nó.
- Fixture nhiều tháng không bị ghi sai “2”; one-dimension request không tự sinh
  Product breakdown khi chỉ yêu cầu Region. Chỉ sửa nếu regression tái hiện được.
- S01 visual filter không ẩn Scope/Coverage/limitations, không làm mất model rows.
- Root+narrowed cùng label, đảo thứ tự, ScopeLabel phải vẫn đúng.

Run targeted Power BI tests/Ruff cho các path sửa. Mọi source change cần Astra B.

## C06 — Cô lập interaction để tránh KPI/narrative khác scope

Allowlist: `bi.py::build_report`, R2 layout manifest, comparator presentation
portion trong `scripts/validate_powerbi.py`, `tests/test_powerbi.py`.
Không sửa DAX bằng REMOVEFILTERS mới để che issue interaction.

1. Emit đúng Desktop-saved interaction mapping từ C04, source/target dùng stable
   visual IDs; hai breakdowns và monthly là sources phải cover.
2. Existing rule `drillFilterOtherVisuals` trong comparator giữ nguyên nếu không
   cần thay. Nếu native reference cần đổi, nêu exact exception, không bỏ guard toàn bộ.
3. Missing pair/invalid target/duplicate conflicting pair/đổi none→filter phải
   fail static regression. Map well-formed vẫn là static-only, chưa native pass.
4. Native click selection vẫn được highlight chính selected source, nhưng các
   target charts/KPI/narrative giữ root context. Không thêm slicers, buttons,
   bookmarks hoặc đổi analytical contract.
5. Nếu native cấu trúc không biểu diễn được bằng schema vendored hiện tại,
   dừng card với minimal repro. Chỉ cho phép review một schema/property exception
   cụ thể; không tự chuyển to “interactions optional” để đóng gate.

DONE tạm: generated map đúng reference, counterexamples reject, pending C08.

## C07 — Regenerate R2 và review invariant trước Desktop

Allowlist: `scripts/build_demo.py` constants/manifest wiring; comparator allowlist
đúng presentation exceptions; tests tương ứng; R2 manifest và output mới.
Giữ `docs/design/dashboard_refresh_layout.json` của R1 và R1 candidate nguyên trạng.

1. Set generator revision `dashboard-refresh-r2`, chọn R2 manifest rõ ràng.
   Dùng existing `layout_manifest=` comparator argument; tránh generic version
   framework mới. Record revision nào dùng file manifest nào.
2. Cập nhật chỉ tests đang so default emitted refresh revision. Tests legacy
   v1 comparator vẫn dùng legacy Candidate; không convert mọi assertion 9→13.
3. Script output và verification path phải **chưa tồn tại**; không force overwrite.
   Nếu lần build fail, lưu failed candidate/record vào sibling có attempt ID trước
   retry; kiểm path canonical không nằm trong protected trees.
4. Seed giữ `20260923`, independent oracle giữ nguyên. Bắt buộc stamp mới đúng
   provenance trong 5 nơi: AnalysisInfo, evidence, manifest, bi_spec, summary.
5. Exact model comparator chỉ giữ exceptions trước đã reviewed: ScopeLabel và
   authoritative fingerprint. No extra table/measure/culture/M drift.
6. Chạy mutation regressions stale fingerprint/sourceColumn/empty M/culture,
   wrong binding/overlap; thêm wrong formatting/interaction cases của R2.

Lệnh build hiện có, chỉ chạy sau wiring R2:

```powershell
.\.venv\Scripts\python.exe scripts/build_demo.py --seed 20260923 --baseline deliverables/PowerBI_Demo_Candidate --output deliverables/PowerBI_Demo_Refresh_R2 --verification-output deliverables/verification/dashboard_refresh_r2/static-verification.json
.\.venv\Scripts\python.exe scripts/validate_powerbi.py deliverables/PowerBI_Demo_Refresh_R2
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\ruff.exe check src scripts tests app.py run.py
```

Note: CLI validate hiện chỉ schema+references. Build_demo phải gọi refresh
comparator R2; đừng ghi CLI đó đã chạy deep comparator nếu chưa gọi.
Static output execution/reconciliation/interactions/rendering đều `not_checked`.
Gate Astra B: full tests/Ruff pass, comparator rejects mutations, preserved-tree
hashes match, inspect emitter và reference mapping. Review không cấp native pass.

## C08 — Native R2 và browser acceptance (gate không được bỏ)

Read-only artifact sau C07. Có thể tạo engine/native/interaction/browser records
và screenshots mới dưới verification R2; không sửa published/historical evidence.

### C08a — Full Refresh + engine

1. Mở đúng R2 PBIP. Ghi process command line/path, Desktop version và source
   hashes trước. Không suy artifact chỉ từ window title `EvidenceBI`.
2. Home→Refresh, quan sát completion/errors/warnings. Capture completion hoặc
   ghi exact user report nếu UI unavailable; không suy report từ screenshot canvas.
3. Kiểm năm measures Ready. Có thể query metadata trạng thái read-only bằng
   current TOM connection nếu UI không xem được; record evidence source chính xác.
4. Discover đúng msmdsrv child/local listen port; **không dùng lại port 54743**
   vì đó là giá trị phiên trước. Chạy verifier mới với R2 oracle/output mới.

```text
powershell.exe -NoProfile -File scripts/verify_powerbi.ps1
  -Project deliverables/PowerBI_Demo_Refresh_R2
  -Port <discovered-current-port>
  -Cases deliverables/PowerBI_Demo_Refresh_R2/verification_cases.json
  -Output deliverables/verification/dashboard_refresh_r2/engine.json
```

Nếu local reviewed script bị execution policy chặn, giải quyết ở process scope
đã được phép; không đổi machine-wide security. Engine script đọc-only và luôn
giữ rendering=not_checked. Pass 7 contexts/35 values theo money exact, growth 1e-12.

### C08b — Appearance + interactions

Before clicking, capture full page baseline; toolbar/Filter pane có thể collapse
để chụp, không crop content để che lỗi. Kiểm cả fit-to-page và full-size.

| Check | Expected |
|---|---|
| KPI | 943,363 / 1,003,363 / +60,000 VND; +6.36% (locale equivalent) |
| Region | North +122,000; South −42,000; West −20,000 |
| Product | Anchor +80,000; Growth −15,000; Stable −5,000 |
| Monthly | Jan 943,363 rồi Feb 1,003,363; caveat nhìn thấy |
| Signed style | positive/negative khác màu, có dấu/zero baseline rõ |
| Findings | F001–F007 đúng artifact, accepted-only; không hardcode |
| Evidence table | Finding/ScopeLabel wrap, Status đọc được; cuộn dọc chấp nhận |
| Scope table | periods/scope/coverage/limitations đọc được; no raw hash/JSON mặc định |
| Header/footer | đầy đủ, không ellipsis cắt caveat, không chồng/canvas trắng |

Interaction cases tuần tự: click North, South, West, Anchor, Growth, Stable,
Jan, Feb; reset selection giữa cases. Mỗi lần ghi selected source/value, actual
4 KPIs, target charts và narrative scope. Targets phải giữ root baseline;
chính bar được chọn có thể highlight. Kiểm page switch rồi quay lại không lưu
filter scope giả. Lặp âm/zero ở fixture hợp lệ nếu implementation màu cần test
runtime; không tạo metric mới.

Nếu lỗi: record actual/screenshot, giữ R2 candidate revision; quay đúng C05/C06,
repair limit per defect. Bất kỳ PBIR sửa sau verification làm native pass stale,
regenerate revision/attempt riêng rồi recheck affected gates.

Khi UI không có: yêu cầu **tối đa một thao tác** mỗi lần, ví dụ “bấm thanh North
và gửi ảnh page tổng quan”. Không yêu cầu người dùng tự debug hay đếm 13 files.
Ảnh tĩnh không chứng minh interaction. Full Refresh user statement được ghi
`reported`, hình quan sát được ghi `observed`; unknown warnings không bằng false.

### C08c — Streamlit smoke

Đọc U1/U2 accepted tests, mở localhost instance task-specific với telemetry OFF.
Success, partial coverage, needs_input ở viewport 1366×768. Xác nhận KPI/scope
đúng, diagnostics gọn; partial cho xem/tải artifact, PBIP vẫn chặn theo contract;
mode không được phép không gọi adapter. Dùng supported synthetic fixtures.
Browser QA không thay native BI QA. Nếu bug mới, freeze nhỏ, repro AppTest rồi
fix đúng `ui.py`/`test_ui.py`; không tranh thủ thiết kế lại UI.

DONE C08: tất cả subgates có evidence; missing một thì `partial/blocked`, không
“done trong phạm vi có thể làm” cho whole gate.

## C09 — Media và một đường dẫn demo chính

Allowlist: README, RELEASE_EVIDENCE_INDEX, CV_PROJECT_BRIEF, LEARNING_PORTFOLIO_DRAFT,
RESUME_CHECKPOINT summary hiện hành, progress, verification R2 public packet.
Historical sections được giữ nhãn/date; không rewrite lịch sử như đã chạy hôm nay.

1. Hai ảnh full-page, không tooltip, không Filters pane thừa, không account/path
   riêng tư. Screenshot R1 thiếu footer không làm final ảnh R2.
2. Export PDF đúng hai pages đã kiểm trong Desktop; ưu tiên native PDF để giữ
   full canvas. Nếu phải dùng verified full-page images tạo PDF, ghi rõ phương
   thức; không dựng HTML rồi gọi đó là Desktop export. Dùng PDF skill khi execute.
3. PBIX sample optional: Save As bản copy, reopen dữ liệu load được, không
   author-local source path. Không viết tính năng PBIX cho mọi upload.
4. README mở đầu: business question → ảnh → 3 observed facts + limitation →
   local quickstart → scope. Diagnostics/hash/gate table chuyển phần evidence.
5. Default mở `PowerBI_Demo_Refresh_R2/EvidenceBI.pbip` sau pass; Candidate cũ là
   regression baseline, Current local không bị promote. Không tạo thư mục copy
   canonical thứ tư rồi gây nhiều nguồn mặc định.
6. Update count theo actual public revision; phân biệt collection/pass/skip,
   Windows/Linux, live historical R6 vs mocked tests. Không claim AI app default
   đang gọi cloud; mọi live score vẫn trỏ đúng historical identity.
7. Correction R1 note liên kết từ index để không còn chỗ bảo whole V1 trước đã pass.

DONE: reviewer mới đọc README biết chạy file nào, dữ liệu gì, giới hạn gì;
mọi link cần cho quickstart/evidence đều có trong staged public file set.

## C10 — Portable distribution và CI của revision thật

Allowlist: `.github/workflows/tests.yml`, `.gitattributes`/`.gitignore` rules
explicit nếu C03 chưa đủ, `scripts/package_release.py` + targeted test **chỉ nếu
chưa có packaging helper phù hợp**, `docs/RELEASE_FILESET.json` mới, release reports.
Không dependency/framework mới để đóng zip.

Thực hiện đóng gói theo §6. Fresh environment phải nằm ngoài workspace để không
đọc nhầm editable install/src/tmp cũ. Install requirements.lock + local project
từ clean package, `pip check`, pytest/Ruff, build-demo ra fresh sibling output,
validate schema/references/refresh comparator. Không cần API key.

CI config target matrix Windows + Ubuntu, Python 3.12; giữ locked dependencies.
Use path-portable commands/temp path (đừng dùng `/tmp` cho Windows). Jobs không
chạy Power BI Desktop, không inject secrets, không gọi live runner. No skip/xfail
để né manifest/layout failures. Local config change chưa là CI pass.
Nếu chỉ có Windows host: chạy clean Windows thật; Linux `not_run` tới khi CI
được chạy sau authorized publication. Không bịa Linux result hoặc đòi cài VM mới.

Full regression gate là **0 failures**, skip có tên/lý do platform-specific.
So selected public node IDs với workspace để không lặng lẽ rơi app/security
tests. Historical bridge ngoài scope giữ theo G0, không bỏ thêm tests.

Sau README/test-count edit cuối, repackage final selected bytes, ghi file list
hash/archive hash và verify chỉ docs/media thay so với tested tree. Source/test/
config thay thì rerun affected acceptance; tránh vòng lặp hash của chính report.

## C11 — Final Astra review + stop

Reviewer mới, read-only, được quyền đọc và rehash **actual artifact directories**,
không giới hạn vào JSON claims như review R1 trước. Packet chứa:

- cards/diffs/file allowlists và reason từng thay đổi;
- full regression/workspace+clean distro, Ruff, collection node IDs;
- frozen manifest/pins, actual protected-tree hashes;
- R2 model/report/oracle/analysis fingerprint và corruption probe results;
- native Refresh/Ready/render/interaction records + full screenshots/PDF;
- selected public file set, leak/path scans summary, archive/source tree identity;
- README/CV claims ↔ đúng evidence, unresolved items/status.

Reviewer kiểm code failure modes và scope, không chỉ đẹp/khớp count.
Sau accepted, chỉ sửa typos không đổi evidence claims; nếu đổi claims/hash nguồn
reviewer phải biết và review delta. Không sửa record sau review rồi giữ verdict
cũ như review exact final bytes.

Hard STOP:

1. Default offline suite+Ruff xanh trên clean Windows package; Linux result có
   thật hoặc ghi rõ chưa chạy (public CI pending, không gọi cross-platform certified).
2. Frozen specs đúng identity, no dropped mandatory tests, negative guards còn.
3. R2 engine/appearance/interactions/Refresh acceptance đủ chứng cứ đúng revision.
4. Có 2 ảnh full-page, PDF, PBIP; README chính xác, public files đủ/không runtime secrets.
5. Astra đóng actionable findings, Current/Candidate/R1/historical không đổi.

Khi 1–5 đạt: `ready_for_publication`, dừng coding, giao zip/path/checksums và
prompt publish riêng. Chỉ khi người dùng yêu cầu publish bản này mới push GitHub;
điều đó không cần thêm feature. Nếu gate native chưa xong, ghi offline-complete,
không close C11. Không tự tạo task V2 để “bù” cho blocker.

## 5. Oracle và negative cases cố định cho builder

| Case | Expected | Tuyệt đối không sửa để pass |
|---|---|---|
| Root demo | prev943363,current1003363,delta60000,ratio0.0636022400708953 | DAX/raw amount |
| Region contributions | 122000−42000−20000=60000 | Xóa nhóm giảm |
| Product contributions | 80000−15000−5000=60000 | Cộng hai partitions thành 120000 |
| E01–E14 acceptance | giữ 14×3=42,39 model-exposed,3 preflight-blocked historical rubric | Denominator/threshold/fixture |
| Fake evidence/wrong scope/wrong delta | vẫn reject ở tests hiện có | Validator hoặc assertion |
| Unknown/all-null | unavailable/partial/needs_input theo contract | Biến thành zero/completed |
| P1 provenance mutation | stale fingerprint/empty M/wrong sourceColumn/culture vẫn reject | Bỏ model parity |
| Snapshot bar selection | root KPIs/narrative/target context không đổi | DAX để bỏ filter mọi nơi |
| Growth display | +6.36% hoặc locale +6,36% | Nhân percent hai lần |
| Frozen master | exact d176…1b89a67,16 entries match | Rehash manifest accepted lịch sử |

## 6. Contract của public file set

Không dùng `git archive HEAD` một mình khi HEAD chưa có dirty changes, không
zip cả workspace. Tạo `docs/RELEASE_FILESET.json` liệt kê **exact relative files**
được duyệt và SHA256, kiểm path không escape/root/symlink/private runtime.

Default lấy Git tracked files **đang tồn tại, current working-copy bytes**, trừ
historical deletion đã documented và explicit private exclusions; thêm một
allowlist exact của untracked files cần thiết. Mọi excluded tracked path phải
có lý do và kiểm references. Không stage/commit tự động trong bước này.

Nhất thiết include: app/src/tests/scripts/vendor schemas, requirements/pyproject,
OFF example config, 16 frozen inputs/manifest, public plans/readme, Candidate
baseline, R2 artifact source files, sanitized public verification/media.
Nếu public tests tham chiếu R1 thì giữ test baseline tối thiểu cần thiết có record
rõ; không kéo thêm backup Desktop tree chỉ vì “cho đủ”.

Exclude: `.venv`, `.git`, caches, `tmp`, `t`, runtime/run_store, one-time key
bridges, account/local Desktop settings/cache.abf, credentials, operational live
authorization configs và superseded backups. Chỉ include historical R6 report/
attempt/session/smoke nếu đã public-reviewed; không mở recursive parent wildcard.

Native source record có absolute local paths được giữ nội bộ. Tạo public-safe
record riêng dùng relative paths với same content hashes, nêu derived_from;
không sửa record gốc. Scan secrets/absolute local paths trên **selected set**;
ghi filenames/issues, không echo secret candidates. Dữ liệu demo synthetic.

Manifest tự thân/archive hash ghi ở report bên ngoài bundle để tránh self-hash
vòng lặp. Những report generated sau tests chỉ ghi observations, không là test
input. Builder phải chứng minh clean package không import source từ repo gốc.

## 7. Commands chuẩn theo mức kiểm tra

Chạy tại project root, mỗi dòng là lệnh riêng; kiểm exit code từng lệnh:

```powershell
git status --short
git diff -- docs/FLAGSHIP_EXECUTION_PLAN.md
.\.venv\Scripts\python.exe -m pytest tests/test_stages.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest tests/test_evaluation_scenarios.py tests/test_evaluation_harness.py tests/test_live_eval_readiness.py tests/test_live_evaluation.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest tests/test_powerbi.py tests/test_ui.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest --collect-only -q
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\ruff.exe check src scripts tests app.py run.py
```

Đây là danh sách theo task, **không yêu cầu chạy tất cả sau từng edit**.
Archive install chạy interpreter của venv mới tại clean package root:

```text
<clean-python> -m pip install -r requirements.lock
<clean-python> -m pip install --no-deps .
<clean-python> -m pip check
<clean-python> -m pytest -q --tb=short
<clean-ruff> check src scripts tests app.py run.py
```

Nếu network/package cache thiếu cho fresh install, ghi dependency blocker, không
claim clean install bằng venv cũ. Package registry install không phải cloud LLM.

## 8. Output mỗi task để người dùng/model sau tiếp tục được

```text
Task: Cxx / substep
Requested model: ...; host-reported model/effort: ...
Baseline: commit + dirty paths + affected file hashes
Prerequisites: references và gate verdict thật
Observed failure: command, exit code, expected, actual
Fix: paths/functions, tại sao minimum
Before/after tests: node IDs/counts/skips, logs path
Preserved invariants: source/artifact hashes
Native statuses: refresh / ready / execution / reconciliation / rendering / interactions
Review: reviewer model, scope, verdict, findings, repair round
Unresolved: exact limitation, không dùng 'all done' nếu còn gate
Next: card ID, command đầu tiên, người dùng chỉ làm 1 thao tác nếu native cần
```

## 9. Prompt giao builder — copy nguyên khối

> Execute đường R00–R08 trong `docs/RELEASE_REPAIR_R3_ADDENDUM.md`, từ task pending
> đầu tiên trong `docs/RELEASE_REPAIR_PROGRESS.md`. Dùng C-cards của
> `docs/RELEASE_REPAIR_SMALL_MODEL_PLAN.md` chỉ làm acceptance reference; không
> restart các lỗi C01/C02 đã sửa. Builder `gpt-5.6-luna`, effort `max`; reviewer
> `gpt-6-astra`, effort `high`, context mới, read-only, không reviewer con.
> Ghi requested identity và identity host thực sự cung cấp; thiếu thì ghi unknown.
> Một writer, task nhỏ, giữ user changes. Không audit lại repo/redesign/thêm feature.
> R01 sửa CI entry point; R02 sửa public file selection và manifest-to-ZIP integrity;
> R03 khóa interaction negative guards; full tests/clean Windows provisional package
> và Astra OFFLINE trước downstream. R04 lấy Desktop-saved known-good reference;
> R05a/R05b sửa presentation từng slice; R06 build Refresh_R3 riêng; R07 native và
> browser verification; R08 final clean package + Astra FINAL. Không ghi pass thay
> reviewer, không lấy AppTest/schema làm native/browser evidence.
> Giữ analytics/validators/DAX/pins/cloud OFF; Current/Candidate/R1/R2 và historical
> evidence read-only. Không ghi đè R2 ZIP, không tự promote/publish/push/chạy live.
> Hai repair rounds cùng failure mode chưa đạt thì dừng card, ghi repro và chờ
> user chuyển model; không reset số vòng bằng task/attempt mới. Làm tiếp offline
> độc lập nếu đủ dependency; native cần người dùng thì tối đa một thao tác mỗi lần.
> Không bắt đầu R05 nếu R04 thiếu reference. Dừng khi mọi mandatory gate accepted,
> hoặc báo blocker thật. Sau mỗi card cập nhật checkpoint và packet, không tự
> đánh dấu cả batch complete từ unit tests. Final status chỉ ready_for_publication
> sau Astra FINAL trên exact candidate; Linux chưa chạy phải ghi rõ CI pending.

## 10. Prompt giao reviewer — context mới

> Review read-only gate <OFFLINE|FINAL> theo RELEASE_REPAIR_R3_ADDENDUM và
> acceptance references trong RELEASE_REPAIR_SMALL_MODEL_PLAN.
> Actual requested reviewer gpt-6-astra/high. Không sửa file, không spawn reviewer.
> Đọc card/gate và file packet; được rehash actual source/artifact trees cần cho
> claim, đừng chỉ tin JSON tự khai. Kiểm counterexamples, public reproducibility,
> accepted scope, native screenshots và phép phân biệt unknown/pass.
> Không hạ acceptance vì tool UI thiếu hoặc test fail được gọi historical.
> Trả accepted / changes_requested / blocked kèm file/field/repro cụ thể,
> scope thực đã kiểm và limitations. Review plan không được gọi là code acceptance.

## 11. Không build trong batch này

Frontend rewrite, multi-agent, RAG/vector DB, orchestration framework, DuckDB/SQL,
forecast/churn/AOV/profit/Pareto, metric/dataset expansion, automatic data cleaning,
general prose verifier, multi-provider application support, auto PBIX mọi upload,
enterprise auth, public hosting. Không cập nhật provider pricing/rate guards lịch
sử chỉ vì coding model khác; task này không chạy billable eval.

Khi release repair đạt, thời gian tiếp theo dành cho walkthrough và giải thích
ba quyết định: evidence validation, null/coverage semantics, DAX reconciliation.
Không tiếp tục coding chỉ vì quota còn hoặc vẫn nghĩ ra feature mới.
