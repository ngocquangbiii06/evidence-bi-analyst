> Cập nhật 12/09/2026: code đã triển khai. Xem [trạng thái và bằng chứng](IMPLEMENTATION_STATUS.md); checklist bên dưới là kế hoạch gốc.

# M1 — Kế hoạch triển khai Data Foundation

Ngày: 11/09/2026. Trạng thái: chưa bắt đầu implementation.

Nguồn quyết định: [PROJECT_PLAN.md](PROJECT_PLAN.md). Yêu cầu lỗi/bảo mật: [SECURITY_AND_FAILURE_MODES.md](SECURITY_AND_FAILURE_MODES.md).

## 1. Kết quả cần có

Sau M1, người dùng có thể chạy một lệnh local để đọc CSV theo cấu hình rõ ràng, kiểm tra định nghĩa dữ liệu và nhận profile/validation report. Không gọi LLM, không gửi dữ liệu ra mạng trong runtime, không tự sửa file nguồn.

Đầu vào: CSV, BusinessContract viết tay và DataPolicy mặc định local_only. Đây là cấu hình cho người phát triển dùng trong giai đoạn đầu; UI hỗ trợ tạo/xác nhận contract sẽ tới M3.

Đầu ra trong runtime directory riêng:

```text
<runtime_root>/runs/<run_id>/
  manifest.json
  dataset_profile.json
  validation_report.json
```

Nếu ingestion thất bại, manifest + validation report ghi trạng thái failed; không tạo profile giả như đã scan thành công. Nếu file đọc được nhưng không có dòng, có thể tạo profile 0 dòng với `NO_DATA`; readiness vẫn bị chặn.

## 2. Điều kiện bắt đầu — phần M0 tối thiểu

- [ ] Có Python environment riêng, phiên bản tương thích dependencies đã chọn và lockfile.
- [ ] Chọn đường runtime ngoài repo; với dữ liệu nhạy cảm không nằm trong cloud-sync folder.
- [ ] Chấp nhận fixture giả lập và ý nghĩa Revenue/grain bên dưới.
- [ ] Ghi Power BI feasibility/provider/budget là resolved hoặc pending; các mục này chưa chặn M1.
- [ ] API keys không cần thiết cho M1; không cài hoặc cấu hình LLM framework để làm foundation.

M0 chỉ kiểm chứng những điều cần chọn môi trường. Không trì hoãn M1 để nghiên cứu mọi provider hoặc mọi framework.

## 3. Fixture chuẩn

Fixture chỉ dùng dữ liệu tổng hợp; một dòng = một dòng bán hàng, khóa `LineID`, `Revenue` là doanh thu dòng sau điều chỉnh đã ghi nhận, currency VND, scale 0, null metric/date/key bị chặn. Date là ngày calendar, không phải timestamp.

| LineID | OrderID | OrderDate | CustomerID | Region | Product | Revenue |
|---|---|---|---|---|---|---|
| 0001 | O001 | 2026-01-05 | C001 | North | A | 100 |
| 0002 | O002 | 2026-01-10 | C002 | North | B | 200 |
| 0003 | O003 | 2026-01-15 | C003 | South | A | 300 |
| 0004 | O004 | 2026-01-20 | C004 | South | B | 400 |
| 0005 | O005 | 2026-02-05 | C001 | North | A | 50 |
| 0006 | O006 | 2026-02-10 | C002 | North | B | 100 |
| 0007 | O007 | 2026-02-15 | C003 | South | A | 200 |
| 0008 | O008 | 2026-02-20 | C004 | South | B | 250 |

Expected M1: 8 dòng, 7 cột, 0 null, 8 LineID khác nhau, 0 duplicate groups/rows/excess, 2 regions, 2 products, 4 customers, ngày min 2026-01-05/max 2026-02-20, Revenue min 50/max 400. ID giữ 0 đầu. Profile chỉ chứng minh những gì có trong file; coverage của hai tháng được khai báo trong fixture description riêng, không suy ra từ max date.

Đáp án chuẩn dành cho M2, lưu bằng tay trong expected fixture: January = 1.000; February = 600; delta = −400. North 300 → 150, delta −150, contribution 37,5%; South 700 → 450, delta −250, contribution 62,5%. M1 chưa implement compare/breakdown.

## 4. Contracts M1 tối thiểu

### BusinessContract

- `schema_version`, `contract_id`, `revision`.
- Dataset column mapping; IDs là strings.
- `grain_description`, `row_key_columns`, `duplicate_policy`.
- `date_column`, `date_format`, kiểu date/timestamp; timestamp chưa được hỗ trợ thì từ chối rõ.
- Currency và money scale; metric additive tham chiếu cột nguồn có sẵn.
- Dimension IDs/mappings.
- Null/parse/negative-value policy; không có default auto-clean.
- Coverage declaration nếu người dùng có thông tin; cho phép unknown.

### DataPolicy

- `schema_version`, `policy_id`, `revision`, `mode=local_only`.
- `external_llm_enabled=false`; không cần API credentials.
- Runtime root, retention TTL, saved-run policy.
- File/row/column/cell limits; raw samples trong report mặc định off.
- Giữ cấu trúc cho allowed outgoing fields/endpoints về sau; chưa implement gateway M3.

### ProfileReport

- `schema_version`, dataset ID/hash, parser config fingerprint, full/sample scope.
- Row/column counts và loại dữ liệu quan sát/đã xác nhận, phân biệt hai loại.
- Null/invalid counts theo cột; unique counts đúng định nghĩa, nêu null có được tính hay không.
- Exact duplicate rows: report số dòng dư; key duplicate statistics: groups, rows involved, excess rows; null keys báo riêng.
- Date bounds và numeric stats cơ bản được tính trên những giá trị parse thành công; kèm valid/invalid counts. Không gọi column valid nếu vẫn có parse failures.
- Không ghi tên khách hàng, raw row samples hoặc free-text values trong output mặc định.

### ValidationReport và RunManifest

- Issue fields: `code`, `severity`, `scope`, `count`, `message`, `suggested_action`; không chứa raw row/secret trong message.
- `execution_status` tách `analysis_readiness`: profile có thể hoàn thành nhưng chưa đủ điều kiện phân tích.
- Manifest ghi dataset hash, contract/policy/schema/tool versions, parser configuration, trạng thái artifact, created/updated/expiry times.
- Các issue có thứ tự ổn định để so sánh kết quả. Timestamp/run ID khác nhau không làm sai determinism test.

Chưa xây tất cả contract của agent. M1 chỉ tạo những types thực sự phục vụ load/profile/validate/store.

## 5. Thứ tự task

| Task | Công việc | Đầu ra / nghiệm thu | Phụ thuộc | Giờ |
|---|---|---|---|---|
| T01 | Setup package, tests, dependency lock, ignore rules, runtime config | Environment chạy được; chỉ sample data được track; runtime path được kiểm tra | M0 | 1–2 |
| T02 | Typed schemas + config validation | Invalid config bị chặn; version mismatch rõ; không eval expressions | T01 | 2–3 |
| T03 | Fixture chuẩn + expected values độc lập | Có clean và negative fixtures; người học giải thích được các expected counts | T02 | 2–3 |
| T04 | Bounded CSV loader | Đọc UTF-8/BOM, giữ ID, không skip malformed rows, limits thực thi khi đọc | T03 | 2–3 |
| T05 | Profiler và business validation | Counts/types/keys/date bounds đúng; grain chưa rõ không được cấp readiness giả | T04 | 3–4 |
| T06 | Run store, safe logging, retention/cleanup | Atomic writes, run isolation, không sửa source; log không có canary | T05 | 2–3 |
| T07 | CLI + report serialization | Một lệnh chạy; exit status phân biệt success/blocked/input/runtime error; JSON ổn định | T06 | 2–3 |
| T08 | Integration/negative tests + walkthrough | Gate M1 pass; ghi giới hạn và số đo cơ bản; không có network calls trong runtime tests | T07 | 2–3 |

Tổng: 16–24 giờ. Khi task vượt estimate, ghi nguyên nhân và thu nhỏ phần mở rộng; không bỏ validation để giữ lịch.

Trong mỗi task, viết/test trường hợp quan trọng cùng implementation. T08 chỉ chạy tích hợp và nghiệm thu, không phải đợi tới cuối mới bắt đầu tests.

## 6. Giao diện CLI dự kiến

Các lệnh dưới đây là yêu cầu giao diện, chưa tồn tại:

```text
bi-analyst profile --input <sales.csv> --contract <business_config.json> --policy <data_policy.json>
bi-analyst runs show <run_id>
bi-analyst runs delete <run_id>
bi-analyst runs cleanup-expired
```

Tóm tắt terminal chỉ có counts/status và vị trí artifacts cần thiết cho người dùng local. Không dump raw dataset hoặc config secrets khi exception. `runs delete` chỉ xóa app-managed copies của đúng run, không xóa input gốc; deletion failure báo rõ.

Giới hạn khởi điểm: 50 MiB input, 200.000 dòng, 100 cột, 4.096 ký tự mỗi cell. File nén/Excel không hỗ trợ. Limits có cấu hình nhưng không được model đổi. Parser không tin extension/MIME đơn lẻ và phải có giới hạn khi đọc field; oversized field không được load vô hạn rồi mới kiểm tra.

## 7. Các case M1 bắt buộc

| Case | Expected |
|---|---|
| Clean fixture | Đúng toàn bộ expected M1, readiness theo contract hợp lệ |
| Zero-byte / header-only | EMPTY_DATASET hoặc NO_DATA, không success analysis |
| Missing required column / duplicate column names | Issue rõ, không auto rename/map |
| BOM và leading-zero ID | Đọc được, giữ ID nguyên nghĩa |
| Wrong encoding / malformed quoting | Không silently skip; yêu cầu cấu hình hoặc báo lỗi |
| Ambiguous date / number locale | Không đoán; báo parse/config error |
| Metric/date/key null | Đếm đúng; readiness bị chặn phần critical |
| One key xuất hiện 4 lần | 1 duplicated group, 4 involved rows, 3 excess rows |
| Two duplicated key groups khác multiplicity | Counts khớp định nghĩa; không nhầm số groups với excess |
| Duplicate full row | Báo riêng; không xóa dòng |
| Negative revenue | Flag theo contract; không auto drop |
| Money precision/overflow | Reject rõ, không truncate/round/overflow âm thầm |
| File/row/column/cell vượt limit | Dừng trong bounded load, cleanup partial artifacts |
| Path/symlink escape trong managed storage | Không đọc/ghi/xóa ra ngoài root được quản lý |
| Disk/write failure | Manifest không completed; source còn nguyên |
| Hai runs cùng input | Thư mục riêng; cùng semantic profile khi bỏ metadata runtime |
| Sensitive canary trong lỗi/raw data | Không nằm trong operational logs hoặc raw sample outputs mặc định |
| Expiry / delete / cleanup sau crash | Xóa đúng app copies; không xóa source; handles hết hiệu lực |

Fixtures trùng khóa không bắt buộc trùng toàn dòng; cần chủ động tạo khác biệt để chứng minh hai phép đếm không bị trộn.

## 8. Tiêu chí nghiệm thu

- [ ] Tất cả case bắt buộc ở trên có kết quả đúng, không chỉ test happy path.
- [ ] Input source hash không đổi trước/sau; app-managed copy có cùng hash nếu được tạo.
- [ ] Mọi report có schema version và đúng dataset/contract/policy revision.
- [ ] File không hợp lệ không được tạo profile/manifest thành công giả.
- [ ] Same input/config → cùng semantic output, ngoại trừ metadata runtime đã định nghĩa.
- [ ] Không gửi network requests trong runtime/tests M1 sau khi môi trường đã cài dependencies.
- [ ] Runtime data không bị track trong Git hoặc đưa vào artifacts demo.
- [ ] Người học giải thích được grain, duplicate definitions, contract vs policy và parse failure behavior.
- [ ] README có một walkthrough local thật, kèm các giới hạn đã đo/đã hỗ trợ.
- [ ] Đã đo thời gian/memory trên fixture lớn hơn trong giới hạn; ghi cấu hình máy và số đo, chưa hứa SLA.

## 9. Không làm trong M1

LLM calls, semantic discovery bằng AI, agent loop, charts/dashboard, DAX, arbitrary formulas, tự làm sạch dữ liệu, multi-user authentication và external integration.

M1 làm xong phải có CLI/report hữu ích để nhìn thấy tiến độ. Mốc tiếp theo là M2 analytics dùng contract đã kiểm tra; không nhảy thẳng sang một chatbot rồi tính bằng model.

## 10. Gói bàn giao cuối M1

Code + lockfile; sample configs/fixtures; actual test results; một run output giả lập; hướng dẫn chạy; danh sách hạn chế/issue còn mở; thời gian thực tế và estimate M2 cập nhật. Chỉ đánh dấu M1 hoàn thành khi có các bằng chứng này.
