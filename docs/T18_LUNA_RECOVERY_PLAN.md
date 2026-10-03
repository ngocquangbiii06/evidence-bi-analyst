# T18 — Kế hoạch khôi phục M5 dành cho Luna Max

Ngày: 25/09/2026. Phạm vi: lỗi xác minh chuyển API key và tiếp tục revision r1 đã có.
Trạng thái: **kế hoạch, chưa execute**. Verdict review kế hoạch được ghi riêng
trong `docs/BUILD_PROGRESS.md`; không thay cho review r1 code/R5 live.

## 1. Mục tiêu và thẩm quyền

Khôi phục đường chạy M5 với thay đổi nhỏ nhất. Không coi đây là yêu cầu viết lại
bridge, agent hoặc evaluation runner. Kết quả hợp lệ có thể là **không cần sửa
application code**, chỉ sửa cách vận hành và cập nhật checkpoint.

- Product contract: `docs/FLAGSHIP_EXECUTION_PLAN.md`, nhất là mục 9–10.
- Quy trình/routing: `AGENTS.md`, `docs/LUNA_ASTRA_BUILD_RUNBOOK.md`, T17–T18/R5.
- Checkpoint lịch sử: `docs/BUILD_PROGRESS.md`, hai mục T18 cuối. Những câu đang
  stale được chỉ rõ dưới đây, không tự biến thành chứng nhận mới.
- Tài liệu này không đổi master plan, không mở task M1–M4/M6.
- Lượt tạo tài liệu chỉ lập kế hoạch. Chỉ execute khi người dùng giao thực thi.
  Khi execute, dùng lại các authorization còn hiệu lực và đúng phạm vi; không
  hỏi lại mỗi bước thường lệ, không suy ra quyền mới từ chính tài liệu này.

Routing khi execute: builder/fixer `gpt-5.6-luna` + `max`; independent reviewer
`gpt-6-astra` + `high`, context mới, read-only, không spawn reviewer thứ hai.
Một writer duy nhất. Nếu session đã là Luna Max, làm trực tiếp; không spawn một
Luna nữa. Ghi requested route và identity host thực sự trả về; không giả định
Markdown đã đổi model. Nếu routing không khả dụng, ghi blocker.

**Phân biệt:** Luna Max là model làm development. Batch r2 đã chạy bằng
`gpt-6-luna`, Standard, reasoning `medium` và phải giữ nguyên như bằng chứng lịch
sử. Revision active mới dùng `gpt-5.6-luna` với identity/output riêng; không đổi
evaluation effort/model ngoài revision được cấp identity.

## 2. Bằng chứng đầu vào — không chẩn đoán lại từ số zero

### 2.1 Lỗi vận hành đã tái hiện trong conversation ngày 25/09

Trên chính `tmp/m5_live_20260924/one_time_key_bridge.py`, không có
`--execute-live`, cổng `127.0.0.1:60661`:

1. Cả locator theo role và theo label tìm thấy đúng một ô `API key`.
2. `fill` chuỗi giả thành công. Chuỗi giả cuối dài 164 ký tự, không phải key thật.
3. Đọc `el.value.length` qua DOM trả `0`; screenshot lại có dấu chấm trong password.
4. Sau submit, tiến trình bridge in chính xác:
   `M5_BRIDGE_DRY_RUN_KEY_RECEIVED; no provider call`.
5. Tiến trình exit `0`, cổng không còn listener, ledger không đổi, thư mục live r1
   vẫn chưa tồn tại. Tab chẩn đoán đã đóng.

Kết luận đã chứng minh: **password readback không phải oracle đáng tin cho việc
nhập thành công trên đường browser này**. Bridge đã nhận chuỗi hợp lệ; thử nghiệm
này không chứng minh đối chiếu từng byte hoặc một credential được provider chấp nhận.

Suy luận phù hợp, nhưng không khẳng định tuyệt đối: các lần trước có thể đã nhập
được rồi bị automation tự chặn trước submit. Exception gốc đã bị thay bằng thông
báo chung, nên không đủ bằng chứng quy cả ba lần về cùng một nguyên nhân.

Astra đã review chẩn đoán: sửa quy trình xác minh, không có căn cứ sửa helper/app.
Đây là review handoff bằng dummy, **không phải review r1 code hoặc R5 acceptance**.

### 2.2 Lỗi smoke cũ và trạng thái r1

- Smoke r0 failed: 16 model calls, 2 tool executions thành công, 14 finish bị
  reject `INSUFFICIENT_EVIDENCE`, thiếu Product breakdown, hết call budget.
- Chi phí được smoke r0 báo: `$0.0032356`. Ledger đã reserve `$0.0209606` cho
  16 calls; reserved cost khác actual reported cost.
- r1 đã có: prompt yêu cầu đủ structured dimensions; deterministic feedback về
  root comparison/dimensions/citations thiếu; telemetry đếm `tool_completed` một lần.
- Checkpoint ghi targeted 61 pass + readiness 23 pass; full **325 passed, 2 skipped**
  và Ruff pass. Đây là kết quả lịch sử, không phải tests của lượt lập kế hoạch này.
- r1 chưa có live output trong lần kiểm tra gần nhất; chưa có smoke/batch pass.
- `BUILD_PROGRESS.md` vẫn ghi review r1 pending và phần key handoff chưa diễn ra.
  Conversation ghi key r1 chưa dùng đã được thu hồi theo yêu cầu người dùng.
  Đối chiếu review record thật; không lấy bind-only review thay review source r1.

## 3. Phạm vi file và những thứ tuyệt đối không đổi

| File/nhóm | Cách sử dụng trong task |
|---|---|
| `docs/BUILD_PROGRESS.md` | Cập nhật sự kiện mới, hashes, review/tests, blocker và next action |
| Tài liệu này | Checklist vận hành; bổ sung kết quả/đường dẫn record nếu cần |
| `tmp/m5_live_20260924/one_time_key_bridge.py` | Đọc và chạy; mặc định **không sửa** |
| `scripts/run_m5_live.py` | Đọc entry point; mặc định không sửa |
| `examples/evaluation/live_config.m5_20260924_r1.json` | Config đã pin; không sửa để lách preflight |
| `src/bi_analyst/{provider,runtime,security,live_evaluation}.py` | Review vùng r1; chỉ sửa nếu có bug cụ thể được test tái hiện |
| `tests/test_agent_security.py`, `tests/test_live_evaluation.py`, `tests/test_live_eval_readiness.py` | Chạy tests có sẵn; thêm test chỉ khi thực sự thiếu counterexample |
| `deliverables/verification/t18_recovery_20260925/` | Có thể tạo record chẩn đoán/review không chứa secret khi execute |
| `deliverables/verification/t18_live_evaluation_r1/` | Chỉ runner live ghi theo workflow hiện có |

Không tìm toàn repo các từ `password`, `key`, `validation` để bắt đầu audit mới.
Không có file browser-automation vĩnh viễn nào đã được chứng minh cần sửa: thao tác
gây hiểu lầm ở các tool calls của conversation. Đừng tạo framework mới để “fix” nó.

Không đổi analytics, evidence/claim contract, fixed fixtures/oracles, acceptance
thresholds, action schema, tool/call/time budgets, PBIR/DAX/layout hoặc
`deliverables/PowerBI_Demo_Current`/Candidate. Không reset ledger, xóa smoke failed,
init Git, push, publish, deploy, redeem reset hoặc thêm provider. Cloud mặc định OFF;
config M5 được opt-in riêng không phải bật cloud toàn ứng dụng.

## 4. Fingerprints tại thời điểm lập kế hoạch

So hash case-insensitive. Nếu khác, xác định đúng thay đổi trước khi dùng review
cũ; không tự restore file người dùng hoặc gán hash mới cho bằng chứng cũ.

| File | SHA256 |
|---|---|
| `src/bi_analyst/provider.py` | `d867907d1ef92486442f7f5b5bc050d26d9a9f2e8e470320d627adfb3783b5e0` |
| `src/bi_analyst/runtime.py` | `c49a7636736b0b639c4b75e32a090df9a049ef416d569f08778b1f4b46171231` |
| `src/bi_analyst/security.py` | `d758c5bcd0d649adc78ea8f11997f6eb04b8b3e9e67bce3648197c2de93dbd17` |
| `src/bi_analyst/live_evaluation.py` | `9b12ee717bc2246acb7fe308217ffc938e090cc4942cb759e7626819fec7278d` |
| `tests/test_agent_security.py` | `648ef6a27c6a8366bc505b3812d7e6110568c387e059a57b357c69a0807e1944` |
| `tests/test_live_evaluation.py` | `535f8dc523d34ccc6e220e01e448880cc8a48e96e7c132225324b993e7534890` |
| `tests/test_live_eval_readiness.py` | `64b05ab1281f4cec095c77500438c4ce5255f7116b5bcd4b29bf93265b9ae623` |
| `tmp/m5_live_20260924/one_time_key_bridge.py` | `0a6ef3f68f5d3def478ddbe0bfb3c9e5a168828bf786acd5432ab787635cd3c5` |
| `examples/evaluation/live_config.m5_20260924_r1.json` | `5b42e0ce93950e4a62cd7485367c1543d5cecb87efec57f66c4c7e657a6873ac` |
| `deliverables/verification/m5-total-budget.json` | `183450f152c3142883f3423a30ecd3987633891e8d33e1f4c3706538ae01ca77` |

Lưu ý: đoạn bind-only trong checkpoint có typo ở hash helper (`...478D3DB...`).
Hash đọc lại ở bảng trên là `...478DDB...`; cần ghi đính chính, không sửa code cho
khớp typo. Hash ledger là checkpoint trước live, sẽ thay đổi hợp lệ khi reserve mới.

## 5. Chuỗi task nhỏ để Luna execute

### L0 — Khóa trạng thái, không cần credential

Đọc theo thứ tự: tài liệu này → hai mục T18 cuối của BUILD_PROGRESS → T17/T18 và
giao thức review trong runbook → mục 9/10 master plan. Đọc source chỉ ở vùng cần.

Thực hiện read-only:

- Xác nhận cwd/venv, rehash các file bảng trên; đối chiếu review candidate.
- Kiểm tra r1 output đã tồn tại chưa. Nếu có, đọc `session.json`, `smoke.json`,
  `batch-started.json`, `attempts.json`, `batch-report.json` nếu hiện hữu trước khi
  quyết định. Không xóa chúng để chạy lại, không mặc định tiếp tục từ đầu.
- Kiểm tra listener 60661 và process liên quan. Chỉ đọc boolean key env đã set
  hay chưa, không in giá trị, không dump environment/process của runner chứa key.
- Append checkpoint: tách historical test result, dummy handoff pass, key revoked
  theo conversation, r1 review chưa đối chiếu, live chưa chạy. Không sửa lịch sử
  thành “ba lần chắc chắn thành công” hoặc tự ghi release pass.

DONE: biết chính xác revision/output/review nào đang chờ; không cần key để làm L0.

### L1 — Kiểm chứng r1 offline và đóng code-review gate

Không mặc định implement lại bản sửa r1. Các tests quan trọng đã có:

| Test trong file hiện có | Điều cần bảo vệ |
|---|---|
| `test_m5_prompt_requires_every_structured_dimension_even_when_prose_names_one` | Prose không làm mất Product trong structured request |
| `test_full_data_compare_only_finish_is_rejected_until_requested_breakdowns_are_cited` | Finish sớm bị reject; feedback chỉ thiếu gì; có thể hoàn tất sau bổ sung |
| `test_finish_feedback_identifies_missing_root_comparison` | Thiếu root comparison được phản hồi đúng |
| `test_finish_rejects_irrelevant_known_evidence_id` | Citation tồn tại nhưng irrelevant không đủ |
| `test_finish_rejects_narrowed_evidence_as_root_citation` | Narrowed scope không thế chỗ root evidence |
| `test_alternative_root_scope_tool_order_can_complete_without_sequence_rejection` | Không ép agent thành một exact workflow |
| `test_m5_tool_sequence_counts_completed_calls_once_and_ignores_unfinished_request` | Chỉ đếm executions thực, không double-count requests |
| `test_smoke_uses_frozen_profile_and_refuses_replay` | Smoke mock đúng profile; giữ chống replay |
| `test_durable_budget_reservation_never_refunds_an_uncertain_call` | Không hoàn budget của call chưa rõ kết quả |
| `test_batch_records_all_42_once_even_when_attempts_fail` | Giữ denominator/failures, không chọn lọc |

Lệnh chạy từ project bằng PowerShell (offline tests dùng mock transport hiện có):

```powershell
& .\.venv\Scripts\python.exe -m pytest -q tests\test_agent_security.py tests\test_live_evaluation.py tests\test_live_eval_readiness.py --tb=short
& .\.venv\Scripts\python.exe -m pytest -q --tb=short
& .\.venv\Scripts\python.exe -m ruff check src scripts tests
& .\.venv\Scripts\python.exe -m ruff check tmp\m5_live_20260924\one_time_key_bridge.py
```

Chạy targeted một lần, full/Ruff một lần tại gate, không lặp full sau mỗi edit.
Windows temp permission lỗi: dùng temp directory mới bằng `New-Item` và
`--basetemp`, không xóa/chmod rộng hoặc biến failure thành skip. Ghi skip thật.

Gọi `preflight_m5_live(root, config_path, phase="smoke")` của module hiện có để
kiểm tra offline; function này không đọc credential hoặc gọi provider. Ghi
`live_readiness`, blockers, config identity, estimates; không cần runner mới.
Đối chiếu remaining ledger với smoke + full batch, không chỉ riêng smoke.

Review r1:

1. Tìm verdict thật đã có trong context/task records và fingerprint đi kèm.
2. Nếu đúng candidate, đủ scope và không còn finding mở: tái sử dụng record,
   cập nhật checkpoint; không gọi reviewer lần nữa chỉ vì Markdown đang stale.
3. Nếu không có record truy xuất được: gọi đúng **một Astra High** read-only,
   đọc vùng `provider.py` prompt, `runtime.py` finish/feedback/reset,
   `security.py` payload, `live_evaluation.py` telemetry và tests tương ứng.
4. Reviewer kiểm feedback không bypass scope/egress, rejected finish không trở
   thành completed, counters không reset, telemetry không làm đẹp score. Trả
   accepted-for-smoke / changes_requested / blocked với fingerprint và finding IDs.

Nếu có bug mới: red counterexample → fix nhỏ → targeted → regression theo impact
→ re-review affected changes. Không tạo test đỏ giả cho lỗi đã được sửa. Không
thay prompt/config một cách suy đoán chỉ vì r0 từng fail.

DONE: preflight đủ điều kiện, tests thực tế và code-review r1 khớp revision.
Đây là **ready-for-smoke**, chưa phải live pass.

### L2 — Kiểm chứng handoff bằng dummy trên phiên browser sẽ dùng

Thực hiện một lần trước key thật nếu phiên browser/process mới; không dùng riêng
HTTP POST từ shell để thay thế kiểm thử đường browser từng gây hiểu lầm.

1. Cổng 60661 phải trống. Nếu bị process khác chiếm, không kill tùy tiện/đổi cổng
   âm thầm; xác định owner rồi dừng slice nếu chưa giải quyết được trong phạm vi.
2. Chạy helper **không** `--execute-live`:

   ```powershell
   & .\.venv\Scripts\python.exe tmp\m5_live_20260924\one_time_key_bridge.py
   ```

3. Giữ session ID/PID trả về. Xác nhận READY đúng localhost và listener thuộc
   đúng helper; trên Windows không coi riêng READY là chứng minh exclusive owner.
4. Dùng skill computer-use/tool browser hiện có, đọc documentation API của phiên
   đó. Mở `http://127.0.0.1:60661/` trong background, tìm label `API key` và đúng
   nút `Send to local evaluation process` từ trạng thái trang thực tế.
5. Điền một dummy hợp pattern, ví dụ tiền tố `sk-` + 161 ký tự `A`, bằng API fill
   được document; truyền options đúng API. Đây không phải credential thật.
6. **Không** dùng đọc `value`, length, snapshot password hoặc dấu chấm làm điều
   kiện chứng minh thành công/thất bại. Không đổi password thành text, không
   inject DOM/JS để lấy lại giá trị, không tìm cách vượt bảo vệ browser.
7. Submit một lần. Đọc process output: marker DRY_RUN_KEY_RECEIVED và exit 0 là
   bằng chứng handoff dummy. DOM có thể vẫn hiện form cũ; không submit lại vì thế.
8. Kiểm tra port đóng, ledger hash không đổi, không tạo live r1 output; đóng tab
   agent tạo. Lưu record ngắn chỉ gồm mode/hash/marker/exit/cleanup, không secret.

Nếu fill/click có exception thật: giữ tên/mã lỗi và thông điệp đã redaction;
không in raw error, request/headers hoặc input để tránh lộ credential trong lần
live. Không catch rồi đổi mọi thứ thành cùng câu “nhập thất bại”. Nếu click có
kết quả không chắc chắn, kiểm tra process/output trước, không retry mù.

Không cần thêm test Python mô phỏng password DOM rồi gọi đó là browser regression.
Không cần thêm bridge test framework khi end-to-end dummy này pass. Chỉ thêm test
helper nếu tái hiện được bug thực sự của helper.

DONE: handoff trên đường thực tế pass dummy, không provider call; vẫn chưa có
bằng chứng key thật/quyền model/smoke.

### L3 — Một lần handoff thật và smoke, sau các gate trên

Chỉ làm khi người dùng đã giao execute live trong đúng authorization hiện hành:
synthetic M5, endpoint OpenAI đã pin, tổng app ledger `$4.50`, không tăng budget.
Conversation đã có approval key Restricted 7 ngày, Model capabilities Request,
chuyển vào `http://127.0.0.1:60661/`, smoke rồi batch nếu pass. Nếu tiếp tục đúng
thẩm quyền này thì không bắt người dùng duyệt lại từng bước. Tuân thủ yêu cầu
confirmation/handoff của công cụ hiện hành nếu nó thực sự yêu cầu.

- Kiểm tra lại không có r1 run đã bắt đầu, config/source/review không đổi và giá
  đã pin còn phù hợp trước live; nếu có sai khác, báo blocker, không tự tăng rates/cap.
- Không tìm lại key đã revoke, không đọc secret từ logs/history. Chỉ chuẩn bị
  một credential hợp lệ theo scope đã duyệt, sau khi gates sẵn sàng; không key churn.
- Khởi động helper với `--execute-live` trong **session tương tác giữ stdin mở**:
  dùng `exec_command` với tham số tool `tty=true`, giữ nguyên `session_id` trả về
  để `write_stdin` gửi lệnh sau smoke. `tty=true` không phải tham số CLI của helper.
  Không dùng Start-Process/detach, stdin DEVNULL hoặc pipeline đóng stdin. Nếu host
  không hỗ trợ session có thể ghi tiếp, dừng trước credential/live để chuẩn bị
  đường chạy phù hợp; không thử paid smoke rồi mới phát hiện thiếu stdin.
- Kiểm tra đúng PID/listener/config như L2. **Nhận key ở mode live sẽ tự chạy
  smoke ngay**, không có bước “nhập thử” an toàn. Poll session với `chars=""`,
  không gửi EOF, Ctrl-C hoặc newline trong lúc đang chờ smoke.
- Chuyển key qua đường được phép, không in key vào chat/tool output/file/config,
  không cho key vào command argv. Không yêu cầu người dùng paste key trong chat.
- Nhập xong submit một lần, không đọc lại password. Xác minh qua process markers
  và output runner, không dựa DOM cũ. Nếu không thể tự chuyển an toàn: chỉ nhờ
  người dùng một thao tác nhập/dán vào đúng form local, không yêu cầu họ debug.
- `M5_BRIDGE_SMOKE_START` chỉ chứng minh handoff và runner bắt đầu; không phải pass.
  Đợi kết quả thật, mỗi lần chờ tối đa 60 giây để còn cập nhật người dùng.
- Smoke pass cần record `smoke.json` đúng config identity, status passed, model
  exposed và usage có thật; kiểm root comparison + Region/Product root breakdown,
  accepted findings/scope và sufficiency theo contract. Không chỉ đọc exit code.
- Smoke fail: không gửi BATCH. Giữ nguyên output/ledger, phân loại failure; xem
  mục 6. Không xóa directory để chạy lại cùng revision.

`--prompt-key` của `scripts/run_m5_live.py` là dự phòng, không phải mặc định mới.
Nếu dùng, phải kiểm chứng no-echo trên đúng terminal bằng dummy trước; getpass
trong terminal redirected có thể không bảo đảm no-echo. Không đổi đường nhập
chỉ để né bảo vệ của công cụ.

### L4 — Frozen batch và Astra R5 evidence review

Chỉ sau L3 pass và không đổi code/config. Helper sẽ in
`M5_BRIDGE_SMOKE_PASSED_WAITING_FOR_BATCH_COMMAND`; kiểm tra record trước khi gửi
đúng một dòng `BATCH` vào **session helper đang chờ**. Không mở runner thứ hai.
Thao tác tool là `write_stdin` với đúng `session_id` đã giữ và `chars="BATCH\n"`;
không gửi lệnh đó vào một PowerShell mới hoặc gửi trước marker/smoke record.
Nếu session mất/key không còn, không rerun smoke để lấy lại state; đối chiếu
entry point batch đã có và record để lập bước tiếp tục riêng, không replay mù.

- Chạy đủ E01–E14 × 3: 42 attempts dự kiến; 39 model-exposed dự kiến và 3 E12
  preflight-blocked, báo actual exposure riêng. Không gọi 42 planned là 42 live.
- Giữ deterministic baseline và mọi failure/retry/latency/token/cost. Unknown
  usage không phải zero. Không chạy lại riêng case fail để nâng điểm.
- Gate giữ nguyên: numerical oracle 100%; accepted evidence/value/scope 100%;
  supported completion ≥22/24 và từng scenario ≥2/3; E08–E13 đúng boundary 18/18;
  unnecessary abstention ≤2/24; unsupported/causal leakage 0.
- Astra High review evidence/denominators/frozen hashes/claims, không review style.
  Không sửa code trong khi reviewer đọc candidate. Một call review đầy đủ; re-review
  chỉ phần cần sửa nếu có finding cụ thể. Plan review không thay R5 review.
- `batch-report.json` có grade pass nhưng `r5_review=not_checked` không tự thành
  R5 accepted. Ghi review riêng trong evidence/checkpoint, không sửa đo lường
  lịch sử để làm đẹp trạng thái.

DONE task này: có báo cáo M5 thật + verdict R5 đúng evidence, hoặc blocker/failure
được giữ trung thực. Không gọi full project/release hoàn tất, không tự bắt đầu M6.

## 6. Nhánh lỗi và giới hạn sửa

| Tình huống | Hành động nhỏ nhất | Không làm |
|---|---|---|
| Password readback = 0, fill không exception | Submit một lần vào bridge đã duyệt, xác minh process | Không kết luận mất key; không tạo key khác |
| Dummy không có marker, process còn sống | Kiểm exception đã redaction, owner/mode/form; dừng nếu chưa rõ | Không đưa key thật vào để “thử” |
| Sau submit không rõ có gửi chưa | Đọc đúng process/session/output/ledger, giữ uncertain cost | Không gửi lại/restart tự động |
| 401/403 từ provider | Dừng, ghi typed auth/permission error, đối chiếu endpoint/scope | Không nới All permissions hoặc đổi provider |
| 429/network | Dùng retry policy hiện có; hết budget thì ghi failure | Không vòng retry ngoài runner |
| Smoke vẫn thiếu Product/lặp finish | Repro offline bằng action sequence/feedback đã redaction; sửa đúng boundary nếu bug | Không bỏ Product/validator hoặc tăng call budget |
| Mock pass nhưng live agent chọn sai | Ghi model-behavior failure; Astra bounded diagnosis | Không khẳng định lỗi numerical engine |
| Ledger/output/config conflict | Giữ records, xác minh identity; báo blocked | Không xóa ledger/session để lách replay protection |
| Batch grade fail | Giữ full batch, classify; đề xuất revision riêng trong budget | Không hạ threshold/rerun chọn lọc |

Một vòng repair = một giả thuyết có bằng chứng → sửa → test lại. Tối đa **hai vòng
repair cho cùng failure**, không bước vào vòng thứ ba: lưu blocker/packet để người
dùng chuyển Sol. Không tự đổi sang Sol hoặc tự tăng effort/model/budget.
Không tính một call cố tình bị reject trong negative test là một repair failure.
Giữ lịch sử các lần lỗi cũ, không reset counter bằng cách đổi tên lỗi/revision.

Nếu thực sự phải đổi prompt/runtime/config sau khi smoke/live đã bắt đầu: không
overwrite r1 records; revision/config identity/output path mới, preflight, tests
và review mới, cumulative ledger giữ nguyên. Trình đề xuất thay đổi cụ thể trước
khi chạy paid revision mới; task này không phải quyền tuning vô hạn.

## 7. Acceptance checklist và record phải bàn giao

- [ ] Tách confirmed observation khỏi suy luận về ba lần handoff cũ.
- [ ] Không còn lấy password value/length làm acceptance oracle trong automation.
- [ ] Browser dummy handoff có marker + exit 0 + cleanup; không provider call.
- [ ] r1 code-review record truy xuất được và hashes khớp, không lẫn bind-only review.
- [ ] Targeted/full/Ruff có command/result thật hoặc lý do blocker rõ; không copy
  325/2 làm kết quả mới. Không forced-red cho code đã pass.
- [ ] Application/cloud defaults, analytics và Power BI surfaces giữ nguyên.
- [ ] Nếu live được execute: đúng approval/config/budget, record smoke và batch thật;
  không claim pass nếu chưa chạy hoặc có failure.
- [ ] Không key/log secret/argv secret; đúng helper process được cleanup; không dừng
  nhầm process của người dùng. Không đóng tab do người dùng mở.
- [ ] Checkpoint ghi modified paths, before/after hashes, model routing/identity,
  commands/results, review verdict, cost reserved/actual, failures và next action.

Record tối thiểu gồm `phase`, `mode` (dummy/offline/live), `config/source hashes`,
`test results`, `bridge marker/exit`, `provider_calls` (0 chỉ khi chứng minh),
`review scope/verdict`, `remaining blocker`. Không cần thêm schema/framework cho record.

## 8. Cách tiết kiệm quota

- Đọc đúng task card và relevant source; không chuyển cả conversation cho reviewer.
- Không sửa file chỉ để chứng minh “đã làm”; không thêm abstraction/test suite mới
  cho một lỗi quan sát đã xác định ở thao tác browser.
- Dùng tests có sẵn và review record khớp hashes; chỉ re-review phần thay đổi.
- Full suite tại gate, không full suite sau mỗi edit; không lặp poll trạng thái.
- Chỉ chuẩn bị key sau khi offline gates pass. Không đốt paid calls để debug UI.
- Hai Astra gates có mục đích khác nhau: r1 code ready-for-smoke (nếu chưa có record)
  và R5 evidence sau batch. Không lấy review kế hoạch này thay cho hai gate đó.

## 9. Prompt giao việc cho Luna

> Execute kế hoạch docs/T18_LUNA_RECOVERY_PLAN.md, chỉ trong phạm vi khôi phục T18.
> Đọc AGENTS.md và các mục tài liệu mà plan trỏ tới; không re-audit toàn repo.
> Dùng Luna Max thực thi, Astra High review độc lập. Ưu tiên không sửa application
> nếu bug nằm ở password readback của automation. Làm L0–L2 trước; chỉ chuyển L3–L4
> khi code-review/offline/dummy gates đạt và authorization live trong conversation
> vẫn áp dụng đúng scope. Không tăng $4.50, không đổi evaluation model, không sửa
> Power BI hoặc analytics. Không dùng password length làm oracle, không in secret,
> không submit lại khi kết quả chưa rõ. Chỉ sửa bug mới có repro, tối đa hai repair
> rounds rồi dừng để tôi đổi Sol; không tự model fallback. Cập nhật BUILD_PROGRESS
> bằng evidence thực, phân biệt plan/dummy/offline/smoke/batch/review pass. Dừng sau
> R5 hoặc blocker cụ thể; chưa bắt đầu M6, chưa publish.

Nếu người dùng chỉ giao offline, dừng sau L2 và báo ready-for-live hay blocker;
không tự diễn giải thành quyền tạo key/chạy API.

## 10. Nguồn và giới hạn bằng chứng

- Source/checkpoint cục bộ và chẩn đoán runtime từ conversation ngày 25/09/2026
  là căn cứ cho lỗi password readback. Không có log exception gốc của ba lần cũ.
- OpenAI Docs: [Browser](https://learn.chatgpt.com/docs/browser) mô tả browser UI
  automation và giới hạn/permission. Tài liệu đó **không** chứng minh nguyên nhân
  kỹ thuật của `value.length = 0`; không gán cơ chế redaction cụ thể khi chưa biết.
- Giá/cost trong tài liệu này là cấu hình hoặc measurement đã ghi của project,
  không phải một báo giá API mới, không phải cam kết billing sẽ chặn chính xác ở $5.
