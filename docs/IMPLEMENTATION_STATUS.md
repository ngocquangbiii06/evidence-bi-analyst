# Trạng thái triển khai

> **Lưu ý trạng thái hiện hành (24/09/2026):** Phần lịch sử bên dưới không phải checkpoint mới nhất; xem `docs/BUILD_PROGRESS.md`. Candidate 27 file đã được regenerate và T16/R4 kiểm chứng lại trên Power BI Desktop thật: Full Refresh, 7/7 DAX contexts/35 values, 2 pages/9 visuals; Astra accepted đúng revision mới. T17 offline readiness cũng được Astra accepted sau repair; T18 live evaluation vẫn blocked vì chưa có model/key/rates/budget/authorization. T19 clean Windows CLI rehearsal pass (Python 3.14.7, 46/46 locked requirements, editable install, `pip check`) và local Streamlit walkthrough đã ghi nhận success/partial/needs-input; bản recapture sau đó lưu 4 screenshot Streamlit nội bộ cho success/partial, chưa có screenshot needs-input hoặc timed demo. Release review chưa hoàn tất. Full regression mới nhất: 312 passed, 2 Windows symlink skips; Ruff pass. `PowerBI_Demo_Current` không đổi; cloud LLM OFF; T20/release/publish chưa được chấp thuận.

Cập nhật 12/09/2026. Đây là trạng thái thực tế; roadmap là thiết kế mục tiêu, không phải bằng chứng nghiệm thu. Theo yêu cầu tiếp tục đến Power BI, các phần có thể làm độc lập đã được triển khai tiếp thay vì dừng theo lịch M1.

Đợt kiểm thử gần nhất: **93 cases pass, 0 failures/errors/skips**, sau khi cài lại virtualenv từ lockfile ngoài thư mục cloud. Hai hardening fixes cuối (ghi trong `FINAL_HARDENING_TODO.md`, tài liệu nội bộ không phân phối) đã được kiểm chứng.

## Kết quả hiện tại

| Phần | Đã có | Giới hạn còn lại |
|---|---|---|
| M0 | Python/virtualenv; Windows 11 và Power BI Desktop 2.157.879.0 có trong Parallels | Mac khóa; chưa mở/refresh project bằng UI. Chưa có model/key/budget LLM được cấu hình |
| M1 | Bounded CSV loader, full profile, semantic evidence, strict contracts/policy, run storage, atomic writes, TTL | Grain/currency/coverage phải được người hiểu dữ liệu xác nhận; không tự chứng minh nghiệp vụ |
| M2 | Aggregate/compare/breakdown bằng fixed-point; filters, null/zero, contributions, evidence hashes | Additive metric, một currency; ratio/distinct/snapshot bị từ chối |
| M3 | CLI + Streamlit local; strict tool loop; gateway; source/policy/checkpoint integrity; cancel/timeout/resume; optional semantic LLM review | Live API chưa chạy; test adapters được đánh dấu rõ; không có adapter local model |
| M4 | Predictions có predicate cụ thể, evidence, contradiction và revision; kiểm thử qua loop thật với model fixture | Chưa đo khả năng điều tra và tỷ lệ hoàn thành của LLM thật; không suy luận nguyên nhân kinh doanh |
| M5 | Star model, DAX registry, PBIR/PBIP, evidence page; optional LLM lựa chọn layout, static schemas | LLM không tự viết DAX tùy ý; metadata/DAX engine và rendering chưa xác nhận |
| M6 | Demo export; null fixture; đáp án độc lập và script kiểm chứng context đã chuẩn bị | Chưa hoàn thành gate Power BI execution/reconciliation/rendering |
| M7 | README, lockfile, scripts, threat model, CI config, verification artifacts | Đã cài virtualenv mới từ lockfile trên cùng Mac; chưa chạy CI trên GitHub hoặc trên máy khác, chưa có video/ảnh Power BI đã chạy hoặc live model eval |

## Bằng chứng và cách hiểu

- `deliverables/verification/tests.xml`: kết quả pytest gần nhất, có số ca/thời gian thực tế. Tests bao gồm AppTest cho luồng xác nhận → phân tích → export, real worker termination, known-answer, policy revocation, canary và stage-boundary checks.
- `deliverables/verification/benchmark.json`: một lần đo 200.000 dòng/11.596.241 byte; tổng 6,414 giây, peak RSS 316.162.048 byte. Không bao gồm UI, network/model latency hoặc render Power BI. Không phải p50/p95/SLA.
- `deliverables/verification/powerbi_schemas.json`: kiểm tra JSON theo Microsoft schemas vendored và pinned commit. Không kiểm tra DAX, Power Query execution hoặc hình ảnh.
- `examples/expected.json`, `powerbi_expected.json`, `powerbi_null_expected.json`: đáp án tính tay, tách khỏi implementation.
- Các tests live-provider dùng HTTP mock và key giả. Chưa có request LLM thật, không có số đo accuracy/completion/cost thực tế.

## Điều chỉnh kiến trúc có chủ đích

1. LLM BI Planner chọn dimensions/trọng tâm layout bằng schema chặt; DAX sinh từ registry theo metric đã xác nhận. DAX tùy ý không có quyền thực thi. Điều này giữ vai trò structured planning và giảm bề mặt lỗi của code generation.
2. Semantic review và BI planning là những stage tùy chọn có approval riêng, mỗi stage một local run và một request. Budget là per-run; tổng workflow cộng các run. Không tự bật chúng theo approval analysis.
3. Run store kiểm tra owner theo session; maintenance local dọn run hết hạn của các session đã đóng. Đây không phải authorization nhiều tenant.
4. Không dùng framework orchestration, vector DB hoặc multi-agent. Analytical agent là một observe/act loop và ba read-only tools.
5. CSV parsing dùng kiểu chuỗi, metric chuyển sang Python int/object Series để không mất precision khi có null. Breakdown gom nhóm theo hai kỳ thay vì quét lại toàn CSV cho từng nhãn.
6. Export chặn tên dimension xung đột với calendar và nhãn có thể bị gộp do case/accent/trailing-space collation. Chặn calendar vượt 10 năm thay vì tạo model quá lớn ngoài dự kiến.

## Ranh giới bảo mật đã triển khai

- `local_only` mặc định; demo cloud yêu cầu class synthetic/public, exact dataset SHA256, endpoint, metrics/dimensions/stages và ngân sách riêng.
- Không có tools shell/file/network/email/SQL/Python code tùy ý dành cho model.
- Payload được dựng lại từ fields chọn trước, label tokens và evidence đã kiểm tra; không gửi nguyên dataframe, nguyên state hoặc lỗi chứa raw rows.
- Semantic review chỉ gửi tên cột có trong allowlist; còn lại dùng tokens/statistics. Regex secret/PII là kiểm tra bổ sung, không phải cơ chế ẩn danh.
- Provider dùng HTTPS fixed endpoint, không theo redirect, không environment proxy fallback, `store:false`, bounded response body. Key chỉ đọc ở backend.
- Kiểm tra nguồn/contract/policy, gồm file policy gốc, trước mỗi lượt và trước tool/finish; checkpoint/report/BI plan có integrity checks. Người có quyền sửa cả source và manifests trong OS vẫn nằm ngoài threat model bảo vệ.
- File source không bị sửa. Folder/file local 700/600; không có application-level encryption. UI bind localhost, XSRF/CORS bật, telemetry Streamlit tắt qua config.
- Exports vẫn là bản sao dữ liệu. Không publish Power BI Service, không public deployment, không dữ liệu doanh nghiệp thật.

## Phần cần kiểm chứng tiếp

1. Mở khóa Mac để thao tác đúng project trong Desktop; Refresh và kiểm tra visuals. Công cụ CUA báo máy khóa; các probe metadata qua guest CLI bị timeout, nên chưa có bằng chứng model được nạp thành công.
2. Chạy các DAX context cho baseline và null case. Đối chiếu exact money/BLANK và tolerance growth theo fixture. Lưu version/model fingerprint và ảnh report.
3. Chọn provider/model, cấu hình key ngoài repo, rates và ngân sách hữu hạn. Chạy live acceptance cố định nhiều lần; ghi input/output tokens, retries, abstention và số claim không được hỗ trợ. Không suy chất lượng model từ scripted fixtures.
4. Sửa lỗi phát hiện từ engine/UI/live model trước khi chốt release portfolio. Làm walkthrough bằng synthetic data sau khi report thực sự chạy.

## Những điều chưa được bảo đảm

- Không xử lý mọi dataset, không tự hiểu đúng grain, không tự sửa dữ liệu và không phát hiện mọi outlier/lỗi nghiệp vụ.
- Không có multi-user auth, nhiều tenant, RLS end-to-end, production egress firewall, mã hóa app-level hoặc kiểm định bảo mật độc lập.
- Không có bảo đảm xóa vật lý SSD/backups/provider; cleanup theo TTL chỉ chạy khi app hoạt động/khởi động lại.
- Chưa kiểm chứng toàn bộ ma trận failure modes bằng browser/network capture và engine thực. Xem đối chiếu dưới đây.
- Python money exact không tự chứng minh precision của mọi DAX measure, nhất là scale > 0 và giá trị rất lớn. Chỉ đánh dấu reconciliation cho contexts/giá trị đã thực thi.

## Đối chiếu ma trận failure modes

“Covered” dưới đây chỉ là phạm vi code/tests tương ứng, không phải chứng nhận an toàn toàn diện.

| Nhóm ID | Bằng chứng hiện có | Chưa xong/khác với baseline |
|---|---|---|
| D01–D07, D10–D12 | `test_data.py`, `test_analytics.py`: malformed CSV, limits, precision, IDs, duplicates, nulls, currency | Không tự clean/convert unsupported formats |
| D08 | Semantics chưa confirm bị chặn; proposal luôn yêu cầu xác nhận line vs repeated order revenue | Không tự phát hiện mọi grain khai báo sai |
| D09 | Âm/null/parse/precision flags; min/max metrics | Chưa có outlier detector/domain rules tổng quát |
| D13 | `test_semantics.py`: full uniqueness, type sample scope rõ | Không coi type sample là bằng chứng full parse |
| A01–A08 | Explicit dates và known-answer/filter/contribution tests | Không tự resolve “quý trước” từ natural language |
| A09–A12 | Template findings, evidence integrity, registered predictions/revision tests | Live LLM abstention/quality chưa đo |
| R01, R02, R04 | Schema/unknown-tool/evidence/provider-envelope checks, budgets | Chưa fault-inject mọi chuỗi 429/5xx/network timeout và live retry |
| R03, R05–R08 | Real subprocess timeout/cancel, source/policy/checkpoint checks, run isolation, failed atomic write/export | Chưa chạy đủ crash/power-loss/filesystem fault scenarios ở OS |
| R09, R10 | Payload cap, explicit model, resume context checks | Quá dài thì chặn; không tự tạo hierarchy summaries; live regression chưa chạy |
| S01–S05, S14–S16 | Canary/gateway/permissions/path/upload/redirect tests; stage approvals | OS account bị chiếm quyền nằm ngoài bảo đảm |
| S06–S08, S10 | No raw error content, safe Streamlit render, provider boundary, offline socket-block test | Chưa browser packet-capture/visual security inspection vì UI bị khóa |
| S09 | `restricted_cloud`/confidential cloud bị chặn | Privacy review/suppression cho dữ liệu thật chưa triển khai |
| S11 | Không có export CSV cho spreadsheet; dữ liệu nhúng Base64 thành literal M | Nếu thêm spreadsheet CSV export phải bổ sung formula neutralization |
| S12, S13 | Chỉ fixtures synthetic, `.gitignore`, TTL/delete/abandoned-session tests | Chưa release scan trên Git history hoặc backup/provider deletion |
| B01, B02 | Known field refs/typed keys/model checks, name/label collision rejection | TOM/engine relationship behavior chưa kiểm chứng |
| B03–B05, B07 | Project + context fixtures + read-only verifier chuẩn bị | Desktop Refresh, DAX reconciliation, revision invalidation thực tế còn pending |
| B06 | Local export theo đích chọn, không publish | Quyền chia sẻ doanh nghiệp/Power BI Service ngoài MVP |

Saved runs từ UI được quản lý lại qua CLI bằng owner/run metadata trên cùng OS account. Đây là quyền local operator; browser restore UI và multi-user auth chưa triển khai.
