# Recovery sau Gemini — task nhỏ cho Luna 5.6 Max

Ngày 26/09/2026. **Plan này đã được dùng để execute R00–R03 và OFFLINE; các
claim trạng thái phải đọc từ RELEASE_REPAIR_PROGRESS, không suy từ lịch sử.**
Đọc file này + RELEASE_REPAIR_PROGRESS trước. Nó supersede thứ tự thực thi,
đường dẫn output và gate names trong RELEASE_REPAIR_SMALL_MODEL_PLAN; không
thay analytical contract hoặc giảm acceptance của C04–C11.

## 1. Baseline và sáu findings đã tái hiện

Đây là kết quả lượt review trước, không phải test mới chạy trong lượt sửa docs.

- `.venv/Scripts/python.exe -m pytest -q --tb=short`: **389 passed, 2 skipped,
  195.56s**. Hai skip là symlink privilege Windows; không xóa/skip thêm tests.
- Ruff `src tests scripts app.py run.py`: pass.
- R2 schema: 21 files; reference checks: 6 tables, 3 relationships, 5 measures,
  12 bindings, zero failures. Refresh comparator hiện zero failures nhưng có
  blind spot interaction dưới đây. Đây không phải native acceptance.
- Frozen master SHA256 đã đúng `d176b0172ee8465155fd4eb2a4c5d96c8e5e72340704f3aa2200577871b89a67`.
  Không restore/re-pin lần nữa nếu hash vẫn đúng.
- Current tree `322b45e530d670ff0d836795135724a25584839be3eec2275336e6bb551ee91f`;
  Candidate `f5da6c14f350ce2c19a5cd371844127c6fba810a8b6ab2dd3b1e3daa69423329`;
  R1 `b1377e031e92c9185a872ddf73be5b0eccc0da998000c4ce19b862e7aec7a32c`.
  Các tree này khớp baseline trước Gemini; thuật toán `build_demo._tree_sha256`.
- R2 actual tree lúc review `42cee9d4d20dfb8f05b6041a0f9b65553ae8268d5c6bf2ddbff6c15a6db3a267`.
  Hash có thể thay bởi Desktop cache; R00 phải phân biệt file source và cache.

| ID | Bằng chứng cụ thể | Card xử lý |
|---|---|---|
| F1 packaging | ZIP 833 files có 387 run_store files, 9 operational live configs, 2 localSettings; is_included('.env') trả True | R02,R08 |
| F2 CI | pytest.exe tests/test_package_release.py --collect-only -q lỗi No module named scripts tại import dòng 4; CI chạy pytest -q | R01 |
| F3 appearance | R2 PNG còn 6.4%, thiếu dấu +, bars âm/dương cùng teal, ScopeLabel/Status chưa đọc đủ, hash/JSON còn trên scope table | R04,R05,R07 |
| F4 interactions | Thay visualInteractions bằng [] trong memory vẫn comparator failures=[]; test all([]) vẫn True | R03,R07 |
| F5 provenance | Native report hash 74a148… khác static/current 0f58f8…; hash chính static file vẫn khớp reference | R00,R06,R07 |
| F6 premature acceptance | Checkpoint ghi Astra A/B passed, C11 ready nhưng packet chưa có reviewer records đủ kiểm; AppTest thay cho browser smoke | R00,R08 |

F1 chưa phải bằng chứng secret thực sự bị lộ. F5 chưa chứng minh report source
đã đổi: có thể khác cache/hash scope. Không sửa hash bằng cách copy current hash
vào record cũ. F6 không khẳng định review chưa từng xảy ra; thiếu packet thì
không dùng claim đó làm current acceptance.

Independent review được dispatch `gpt-6-astra/high`, task
`/root/astra_gemini_delta_review`, kết luận chưa đủ ready_for_publication cho
F1/F2/F4/F5/F6. Reviewer không có runtime identity tự kiểm độc lập. F3 do main
reviewer trực tiếp xem hai PNG R2 và đối chiếu bi.py; không gán F3 cho Astra.

## 2. Ràng buộc thực thi và outputs

- Builder `gpt-5.6-luna/max`, reviewer `gpt-6-astra/high`. Không tự chuyển Gemini,
  Sol, provider hay application LLM. Nếu user chọn Gemini sau, cùng card/criteria;
  không có reviewer thì xuất packet ở review_pending, không tự cấp verdict.
- Một writer. Chỉ đọc vùng source/test được card dẫn, tối đa 1–3 source/test files
  mỗi slice. Direct dependency ngoài allowlist cần ghi lý do trước khi sửa.
- Giữ Revenue/additive, Region/Product, hai explicit periods, evidence semantics,
  validators, DAX expressions/model formatString/relationships, frozen pins.
- Cloud OFF; không key/billing/live eval. Không publish/push/stage/commit/deploy.
- Current/Candidate/R1/**R2**, static/engine/native records/ZIP lịch sử read-only.
  Không sửa README/historical record để biến native chưa kiểm thành pass.
- Bản sửa mới: `deliverables/PowerBI_Demo_Refresh_R3/`;
  evidence `deliverables/verification/dashboard_refresh_r3/`;
  layout `docs/design/dashboard_refresh_layout_r3.json`;
  reference `docs/design/dashboard_refresh_r3_reference.md`.
- Tất cả output mới phải chưa tồn tại. Nếu tồn tại, kiểm provenance/checkpoint
  và dùng attempt sibling rõ ràng; không overwrite, không recursive delete.
  Counter failure mode đi theo lỗi, không reset qua attempt mới.
- Existing R2 ZIP không được phát hành. R3 ZIP chỉ tạo từ reviewed exact file set;
  giữ archive hashes và review records ngoài bundle để tránh self-hash loop.

## 3. Dependency, review và stop rule

`R00 → R01 → R02 → R03 → OFFLINE → R04 → R05a → R05b → R06 → R07 → R08 → FINAL`.

R04 là native reference prerequisite thật, không chỉ file ghi property names.
Có thể chuẩn bị checklist/đường dẫn media R08 khi native blocked, không đóng gate.
Không thêm một vòng full audit; hai independent acceptance reviews OFFLINE/FINAL.
Khi có vấn đề kỹ thuật bất định, xin bounded diagnosis, không gọi nó là accepted.

Mỗi lỗi: meaningful red repro → minimum fix → positive/negative tests → packet.
Sau tối đa **hai vòng sửa cùng failure mode** chưa đạt: dừng card, giữ diff,
ghi exact repro/actual/expected, chờ user chuyển model. Không dùng quota còn
làm lý do mở scope. Reviewer không sửa code; writer không sửa frozen candidate
khi review đang chạy. Thay source sau review phải re-review delta.

## R00 — Khóa checkpoint, không đánh đồng history với acceptance

Đọc: progress hiện hành; R2 native/static/engine records; `build_demo._tree_sha256`.
Ghi: progress, append BUILD_PROGRESS, record mới `dashboard_refresh_r3/baseline.json`.
Không sửa app, R2 records, master hoặc acceptance manifest.

1. Capture dirty paths và hash đúng files dự định sửa; đây có thể là user changes.
2. Rehash protected trees/16 frozen inputs và ghi thuật toán, danh sách file hashed.
3. Đối soát hai report hashes F5 bằng file inventory nếu có. `.pbi`/cache differences
   ghi riêng; không normalize bỏ source files để ép bằng nhau. Nếu thiếu historical
   inventory: linkage unresolved, phải native-verify R3 mới.
4. Giữ R2 engine 7/7/35 là historical record đã đọc, không ghi newly executed.
5. Checkpoint hiện hành changes_requested, full release not accepted. Native
   interaction not_checked; screenshot content observed không chứng minh Refresh.

DONE: baseline packet có nguồn/giới hạn; next R01. Không chạy lại full suite
nếu dependency hashes thực sự chưa đổi từ kết quả review đã nêu.

## R01 — CI collection nhất quán

Allowlist: `.github/workflows/tests.yml`, `tests/test_package_release.py`;
`pyproject.toml` chỉ khi cần fix discovery thực sự, không sửa packaging logic ở card này.

- Repro lệnh console pytest ở F2, lưu exit code và import error; đối chiếu với
  `python -m pytest tests/test_package_release.py --collect-only -q`.
- Default minimum: dùng `python -m pytest` nhất quán trong CI và quickstart hiện
  hành; không thêm sys.path hack, không skip test, không đổi installed package
  discovery để ship toàn bộ scripts như application package.
- Nếu vẫn hỗ trợ console pytest thì fix/test riêng; không claim lệnh đó pass
  chỉ vì python -m pass. Update README test command nếu thực sự còn chỉ dẫn cũ.
- Test targeted package tests + collection toàn suite; node IDs phải giữ nguyên
  trừ tests mới được ghi rõ. Windows/Ubuntu workflow config có lệnh portable.

DONE: documented/CI command collect đúng và targeted tests pass; Linux execution
vẫn not_run nếu chỉ thay YAML trên Windows. Next R02.

## R02 — Đóng gói bằng exact allowlist, không quét gom workspace

Allowlist: `scripts/package_release.py`, `tests/test_package_release.py`, một file
allowlist nếu cần `docs/RELEASE_PUBLIC_EXTRA_FILES.json`; không framework mới.
Đọc §6 của main plan. Không rewrite R2 manifest/ZIP, không gọi script cũ __main__.

RED tests trong tmp fixture độc lập (không dựa file count >50 của workspace):

1. .env/.env.*, credentials và operational live_config.m5_*.json bị loại hoặc
   explicit rejection; OFF example được phép. `.pbi`, cache.abf, runtime/run_store,
   one-time bridge, Desktop backups không tự vào bundle dù nằm sâu dưới deliverables.
2. Arbitrary untracked file không vào; exact approved untracked file có thể vào.
   Tracked source đang dirty lấy working-copy bytes; deletion không resurrect HEAD.
3. Reject absolute/drive/UNC/traversal paths, resolved path ngoài root, Windows
   case-insensitive duplicate archive entries. Symlink/reparse point reject rõ;
   dùng existing platform-aware fixtures, không nâng quyền để làm xanh.
4. Missing/changed selected file sau manifest phải làm packaging fail; không tạo
   ZIP "đạt" bằng cách recollect silently. Đổi file không selected không ảnh hưởng.
5. ZIP entries/bytes/sha256 khớp exact manifest; không manifest self-hash vòng lặp.
   Output tồn tại bị từ chối; không để partial output mang tên final release.
6. Positive minimal synthetic package đủ source + approved fixture + OFF config
   vẫn đóng gói/verify được. Secret probes dùng fake marker, không in secret.

Implementation tối thiểu: lấy Git tracked paths tồn tại bằng NUL-safe listing,
trừ explicit denied paths, thêm exact reviewed untracked paths; normalize/resolve,
scan selected set, hash, rồi đọc đúng manifest để đóng ZIP. Không broad os.walk
fallback. Nếu không Git: yêu cầu approved explicit manifest, không tự include-all.
Source/provenance giữ rõ working copy thay vì archive HEAD. Scan báo file/rule,
không echo credential values; không biến task này thành enterprise secret scanner.

Provisional selected file set chứa các dependencies test thực sự cần và R2
baseline tối thiểu read-only, **không tuyên bố R2 là accepted dashboard**. Những
file operational scripts không cần release phải loại theo path có giải thích.
Manifest/ZIP provisional để ngoài root trong temp task directory và ghi exact paths.
Chưa cập nhật RELEASE_FILESET canonical ở card này.

DONE: negative+positive tests pass, kiểm selected set không chứa F1 paths, ZIP
manifest consistency pass. Next R03; clean distro test ở gate OFFLINE.

## R03 — Exact interaction coverage guards

Allowlist: `scripts/validate_powerbi.py`, `tests/test_powerbi.py`; `bi.py::build_report`
chỉ nếu test chứng minh emitter thiếu mapping. Không sửa DAX/drill behavior.

Tái hiện F4 với tmp copy/monkeypatch, không sửa R2. Expected map độc lập:
sources = hai breakdowns + monthly; targets = 4 KPIs + hai breakdowns + monthly
+ narrative; bỏ self-pairs. Fixture đầy đủ: **21 directed pairs**.
Với một dimension: chỉ source/target tồn tại; 2 sources × 6 targets = **12 pairs**.
Không hardcode 21 cho mọi request; IDs lấy từ locked inventory, không từ map
đang validate. Header không có data/filter behavior nên không là target bắt buộc.

Negative tests: missing field, [], thiếu một pair, target giả, source giả,
duplicate (cùng type và conflicting), NoFilter→Filter, self-pair ngoài contract.
Positive exact full map và one-dimension fixture. Không dùng all(...) làm assertion
duy nhất; kiểm uniqueness, exact set coverage và allowed interaction type.
Giữ native status not_checked dù static map hợp lệ. Không claim JSON encoding
thực sự có tác dụng trước khi R04/R07 Desktop chứng minh.

DONE: comparator reject mutations, known-good accept, old model/provenance guards
vẫn nguyên. Next OFFLINE.

## Gate OFFLINE — Astra independent review

Full workspace `python -m pytest -q --tb=short`, Ruff; tạo provisional ZIP bằng
helper mới, extract vào temp ngoài workspace, venv mới, install requirements.lock
+ project, pip check, full suite/Ruff/collection parity. Kiểm module imports trỏ
đúng clean export, không editable install từ repo gốc. Ghi actual counts/skip lý do,
không ép bằng 389 khi có tests mới. Package/network thiếu thì blocked, không giả pass.

Fresh Astra packet: R01–R03 diffs, red/green probes, selected file list/hashes,
public exclusions/dependency check, clean logs, protected hashes. Review chỉ
offline correctness, không cấp native/release pass. Accepted mới sang R04/R05.

## R04 — Native reference thật, chặn đoán property

Không sửa generator. Thực hiện C04 main plan trong scratch copy ngoài protected
artifacts, dùng Desktop hiện có. Reference mới phải có version, source hash,
before/after saved PBIR cho từng feature, exact JSON path và screenshot behavior:

- Card +60,000 và +6.36% ở visual layer, không đổi DAX/model formatString.
- Bar sign colors + signed labels từ measure hiện có, không hardcode theo tên nhóm.
- Bảng wrap **và column widths** để 4 columns đọc được; visual filter ẩn technical
  rows, không xóa AnalysisInfo rows; scope/null/filter semantics còn nguyên.
- NoFilter source→targets và click behavior, không chỉ trích schema/doc.

Chỉ dùng UI/tool được host hỗ trợ; không bypass tool restrictions bằng shell.
Nếu không tương tác Desktop được: dừng đúng substep, hỏi tối đa một thao tác;
người dùng không phải tự tìm property/debug. Không coi reference R2 markdown
hiện có là Desktop-saved proof. Không lower criteria khi property không hoạt động.

DONE prerequisite: concrete saved differences + behavior cho các feature cần sửa.
Chưa đủ thì R05 blocked. Gửi bounded diagnosis nếu hết repair budget; không tự
thay visual types/bindings hay thêm measure.

## R05a / R05b — Minimum presentation fixes

Allowlist mỗi slice: presentation vùng `src/bi_analyst/bi.py`, `tests/test_powerbi.py`,
R3 layout/reference. R05a sửa cards/bars/month; R05b sửa evidence/scope tables.
Giữ 2 pages, 9 data visuals +4 textboxes, stable IDs/roles/bindings/canvas.
Áp dụng native property chính xác từ R04, không nâng schema hàng loạt.

R05a: +60,000, +6.36% locale-equivalent, positive/negative/zero styling;
monthly title ngắn giữ lại, caveat trung tính nếu không có trusted month count.
Tests negative/zero/scale2 và nhiều tháng không diễn đạt sai chỉ có hai observations.
R05b: wrap/width để Finding/ScopeLabel/Status đọc được, cho cuộn dọc, không ép
font nhỏ; technical rows ẩn tại visual nhưng model/evidence rows nguyên. Test
technical filter không ẩn coverage/limitations và không lẫn root/narrowed scope.
Không dịch accepted findings bằng LLM hoặc thêm UI feature.

DONE mỗi slice: targeted tests/Ruff pass, before/after packet, native vẫn
not_checked cho generated revision mới. Next R06 sau cả hai slice.

## R06 — Fresh R3 build và immutable verification identity

Allowlist: `scripts/build_demo.py` revision/manifest wiring; comparator chỉ exact
presentation exceptions nếu R04 yêu cầu; tests tương ứng; R3 layout/output.
Giữ Candidate baseline, seed 20260923, oracle và analytical invariants C07/§5.
Không đổi scripts/verify_powerbi.ps1 để làm DAX pass; helper mới chỉ nếu thật sự
cần process/path discovery, không dùng first matching port như proof report identity.

Build vào paths mới ở §2, generator_version dashboard-refresh-r3. Static schema,
references, strict comparator và full regression/Ruff phải pass trước native.
Record per-file model/report hashes; normalized source inventory loại đúng cache
paths được khai báo riêng, không loại tùy tiện source gây mismatch. Có raw tree
hash riêng nếu cần; không so hash được tính theo hai phạm vi khác nhau.
Artifact bị Desktop save đổi source sau đó làm prior proof stale cho affected
gates: capture diff và revalidate; không sửa record cũ để giữ pass.

DONE: build/test packet khóa candidate R3, source/report inventory rõ; execution,
reconciliation/rendering/interactions not_checked tới R07. Không overwrite R2.

## R07 — Native và browser acceptance trên đúng R3

Theo C08 main plan, không dùng historical engine/screenshots làm pass mới.

1. Bind exact PBIP path/process + current engine connection/model identity; tên
   cửa sổ EvidenceBI và model match riêng lẻ không chứng minh report/layout identity.
2. Full Refresh completion + warnings +5 measures Ready: ghi observed/reported/
   not_checked trung thực; không suy từ canvas. Port discover mới mỗi session.
3. Chạy existing read-only verifier: 7 contexts/35 values, money exact, growth
   tolerance1e-12; model/report/oracle hashes thuộc candidate đang mở.
4. Check toàn bộ appearance C08b: root943363/1003363/+60000/+6.36%; regions
   +122000/-42000/-20000; products+80000/-15000/-5000; monthly order; two pages/
   13objects; full readable evidence/scope/footer, no raw metadata mặc định.
5. Tám click cases North/South/West/Anchor/Growth/Stable/Jan/Feb, reset giữa cases.
   Ghi actual 4KPIs + target charts/narrative trước/sau, selected source có thể
   highlight. Screenshot tĩnh/config NoFilter không là interaction pass.
6. Browser smoke Streamlit thực: success/partial/needs_input, local synthetic,
   telemetry/cloud OFF. AppTest chỉ supporting evidence, không thay browser smoke.
   Bug mới: repro nhỏ, allowlist ui.py/test_ui.py chỉ khi thật sự cần; hết repair
   budget hoặc beyond scope thì blocked, không tiện tay redesign.

Record mới tách check_state (passed/failed/not_checked/not_applicable) và
evidence_kind (observed/reported/configured). Reported Refresh cần exact user
statement theo C08, không tự coi configured là observed. Thiếu proof là pending.
Giữ ảnh đầy đủ, không edit che lỗi. Nếu không native UI, tối đa một thao tác user
mỗi lần. Chưa đủ R07 thì R08 chỉ chuẩn bị docs, không promote accepted demo.

## R08 — Final media, distribution và Astra FINAL

Allowlist: README, RELEASE_EVIDENCE_INDEX, checkpoint/docs links cần thiết;
R3 public-safe evidence/media; approved file set/packaging outputs mới. Không
rewrite R1/R2 historical records. C09/C10/C11 là acceptance reference chi tiết.

1. Chỉ khi R07 đạt, chọn R3 làm default demo, hai ảnh/PDF đúng revision (PDF skill
   khi làm media); public safe relative paths, không private account/machine details.
2. Dùng helper R02 chọn exact current bytes + approved extras; zero run_store,
   operational live configs, localSettings/credentials. Native internal records
   được giữ riêng; public-safe derivatives có derived_from/hash linkage rõ.
3. `docs/RELEASE_FILESET.json` hiện là R2 historical list: giữ nguyên. Tạo
   `docs/RELEASE_FILESET_R3.json` mới; exclude manifest itself/ZIP/report self-hashes.
   ZIP R3 filename mới. Manifest tồn tại cũ → attempt sibling, không overwrite.
4. Clean extracted Windows environment: pip check/full suite/Ruff/node parity,
   smoke build/validate output mới. Linux not_run/CI pending nếu chưa chạy thật.
   Sau source/test/config change phải rerun affected gates; docs/media edits cuối
   phải rehash/repackage, không giữ zip cũ khác reviewed bytes.
5. Astra FINAL fresh context đọc actual files/ảnh/checksums, không chỉ claims.
   Packet gồm cả R04–R07 diffs/native reference, formatting/click/browser evidence,
   preserved hashes, clean logs, selected files/ZIP hashes, README claims.
   Verdict phải có reviewer identity được host cung cấp hoặc unknown, phạm vi,
   candidate hash và findings. Thiếu reviewer → review_pending, không ghi accepted.

STOP: OFFLINE accepted + R04–R07 đủ proof + clean final package + Astra FINAL
accepted = ready_for_publication, **không đồng nghĩa published**. Dừng coding;
không feature mới, không tự push. Linux pending phải ghi rõ, không claim certified.

## 4. Packet tối thiểu sau mỗi card

Ghi vào progress hoặc record link: task/dependencies; requested/host-reported
model; baseline/diff hashes; red repro/exit code; minimum fix/paths; tests actual
count/node IDs/skips; protected hashes; native check states; repair counter theo
failure mode; reviewer scope/verdict; unresolved; next card/first command.
Không copy toàn history vào Luna/reviewer; prompt main plan §9 đã cập nhật để
chạy addendum này. Planning review không thay application acceptance review.
