# Kế hoạch dự án — Evidence-Driven AI BI Analyst

Phiên bản thiết kế: 1.0. Ngày: 11/09/2026. Trạng thái: baseline thiết kế. Tiến độ thực tế ở [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## 1. Mục tiêu và cách sử dụng kế hoạch

Xây dựng một hệ thống điều tra câu hỏi nghiệp vụ bằng công cụ tính toán deterministic, có định nghĩa dữ liệu rõ ràng, bằng chứng cho từng kết luận và đầu ra thiết kế Power BI. Đồng thời học được tool calling, state, agent loop, lập kế hoạch, điều chỉnh giả thuyết và giới hạn quyền của agent.

Không thể liệt kê trước mọi tình huống hoặc bảo đảm không phải sửa. Kế hoạch giảm chi phí sửa bằng cách chốt ranh giới module, version hóa contracts, kiểm chứng giả định sớm và dùng bộ đánh giá độc lập. Tình huống ngoài phạm vi phải có đường dừng an toàn và thông báo hữu ích.

Mỗi milestone chỉ hoàn thành khi có artifact chạy được, bằng chứng kiểm tra và giới hạn đã ghi lại. Không tự gửi dữ liệu thật, mua dịch vụ hoặc public deployment. Yêu cầu tiếp tục triển khai đến Power BI sau đó cho phép hoàn thành các module liên tiếp khi làm được; không cần chờ lịch baseline.

Tài liệu đi kèm:

- [Bảo mật và tình huống lỗi](SECURITY_AND_FAILURE_MODES.md).
- [Kế hoạch triển khai M1](M1_IMPLEMENTATION_PLAN.md).

## 2. Giả định và các quyết định phải kiểm chứng sớm

| Hạng mục | Giả định lập kế hoạch | Thời điểm xác nhận / nếu không đúng |
|---|---|---|
| Người thực hiện | Một người vừa học vừa xây dựng | Ước lượng theo giờ; điều chỉnh sau M1–M2 |
| Máy phát triển | macOS như workspace hiện tại | Python core chạy độc lập Power BI |
| Người dùng MVP | Một người trong môi trường local đáng tin | Không bật truy cập Internet/LAN công khai |
| Dữ liệu demo | Sales giả lập; biết cách tạo và đáp án | Dùng fixture nhỏ tính tay và dataset lớn hơn có seed |
| Dữ liệu thật | Chưa được phê duyệt gửi cloud | Giữ `external_llm_enabled=false` |
| LLM provider/model | Chưa chọn | M0 thử trên dữ liệu giả lập, ghi chất lượng, latency, cost; không tự mua dịch vụ |
| Ngân sách API | Chưa có số tiền được xác nhận | Mock client ở M1–M2; live run cần cấu hình ngân sách hữu hạn |
| Power BI | Chưa xác nhận máy Windows / môi trường được hỗ trợ | M0 thử dựng model và measure nhỏ; không chờ M6 mới tìm đường chạy |
| Quy mô ban đầu | Tối đa 50 MiB, 200.000 dòng, 100 cột | Giới hạn thiết kế ban đầu, cần benchmark; không phải thông số đã đo |

Power BI Desktop yêu cầu Windows; tài liệu Microsoft liệt kê môi trường ảo hóa được hỗ trợ. Phải kiểm chứng phương án thực tế trước khi lên lịch integration. Nếu chưa có, vẫn làm core và BI specification nhưng không đánh dấu M6 hoàn thành. [Microsoft: Power BI Desktop](https://learn.microsoft.com/en-us/power-bi/fundamentals/desktop-get-the-desktop).

## 3. Phạm vi sản phẩm

### 3.1 MVP — hoàn thành sau M3

- Một CSV sales theo grain dòng hàng; cột ID được giữ dưới dạng chuỗi khi cần.
- Một đồng tiền mỗi lần phân tích; Revenue và các metric cộng được có cột nguồn rõ ràng.
- So sánh hai khoảng thời gian không chồng lặp, xác định ngày bắt đầu/kết thúc và chính sách coverage.
- Phân rã chênh lệch theo dimension đã khai báo; drill-down chỉ trong những filter được cho phép.
- Semantic proposal có evidence, unknowns và màn hình xác nhận tối thiểu.
- Một analytical agent có tool loop, state, kế hoạch ngắn, evidence và điều kiện dừng.
- Report gồm findings, giả định, giới hạn, tool trace và trạng thái validation.
- Data policy gateway, giới hạn tài nguyên và vòng đời dữ liệu được kiểm tra.

### 3.2 Portfolio hoàn chỉnh — M4 đến M7

- Điều tra nhiều bước, bác bỏ hoặc sửa giả thuyết khi kết quả thay đổi.
- BI Planner tạo KPI, model, DAX ứng viên và dashboard specification nhất quán.
- Một Power BI report được dựng từ output; measures được chạy và đối chiếu trong các context chọn trước.
- Demo cho thấy câu hỏi, phép kiểm tra, kết quả, lý do đổi hướng ngắn gọn và điều chưa biết.
- README, sơ đồ, threat model, eval report, hướng dẫn chạy lại và giới hạn công khai.

### 3.3 Ngoài phạm vi bản đầu

Nhiều bảng đầu vào, streaming, tự sửa dữ liệu không cần review, SQL/Python tùy ý do model sinh, causal inference tự động, hệ thống phục vụ nhiều doanh nghiệp, vector database, RAG, MCP, multi-agent tự chủ và tự động tạo toàn bộ PBIX.

Ratio, distinct count và snapshot được dự liệu trong metric schema nhưng bản đầu trả `UNSUPPORTED_METRIC_TYPE`. Chỉ mở rộng khi có công thức, phép phân rã phù hợp và bộ kiểm thử riêng.

Chức năng bị trì hoãn không được mô phỏng thành đã hoạt động trong demo hoặc README.

## 4. Những quyết định kiến trúc đã chốt

| ID | Quyết định | Lý do / điều kiện xem xét lại |
|---|---|---|
| ADR-01 | Một analytical agent | Số agent không quyết định chất lượng; thêm agent khi có nhiệm vụ tự chủ đo được |
| ADR-02 | Profiler và computation là Python | Kiểm thử độc lập LLM; số liệu không lấy từ model |
| ADR-03 | Profile trước semantic proposal | Đề xuất grain/key cần bằng chứng từ dữ liệu |
| ADR-04 | Business contract tách DataPolicy | Định nghĩa nghiệp vụ và quyền gửi dữ liệu là hai quyết định khác nhau |
| ADR-05 | Mọi LLM call qua gateway | Bao gồm semantic discovery, review, BI Planner, retries |
| ADR-06 | Metric có type và dependencies | Không cộng margin/distinct count như Revenue |
| ADR-07 | Tool catalog có kiểu dữ liệu, giới hạn và quyền | Model chỉ đề xuất hành động; executor mới quyết định được chạy hay không |
| ADR-08 | Evidence là dữ liệu có cấu trúc, có version | Không dùng đoạn văn model làm nguồn chân lý |
| ADR-09 | Input bất biến, thay đổi tạo revision mới | Truy vết và tránh kết quả cũ gắn với định nghĩa mới |
| ADR-10 | Core độc lập UI/provider/Power BI | Thay adapter khi cần; không xây framework tổng quát trước |
| ADR-11 | Lưu run local theo thư mục riêng và atomic writes | Đủ cho single-user; chưa cần database/queue |
| ADR-12 | Không tự fallback sang provider khác | Tránh thay đổi đích gửi dữ liệu ngoài chính sách |
| ADR-13 | BI Planner là structured generation | Nâng thành loop khi có công cụ thực thi và lợi ích đã đo |
| ADR-14 | MVP localhost, không có public upload dữ liệu tùy ý | Public service cần một nhánh hardening riêng |
| ADR-15 | Evaluation dùng đáp án độc lập | Không tự lấy hàm đang kiểm thử sinh expected answer |

## 5. Luồng và ranh giới module

```text
Local UI / CLI
     │
     ▼
Ingestion → Immutable dataset reference → Deterministic profiler
                                               │
                            Local schema evidence + DataPolicy
                                               │
                                    LLM gateway (nếu được phép)
                                               │
                                    Semantic proposal
                                               │
                                  User confirms / edits
                                               │
                                  Validated BusinessContract
                                               │
                                    Run controller (local)
                                      │               ▲
                                LLM gateway           │
                                      │          ToolResult + evidence
                                Model proposal        │
                                      ▼               │
                              Permission/argument checks
                                      │               │
                                      ▼               │
                                Python executor ───────┘
                                               │
                                 Findings + validation
                                               │
                                      BI Planner
                                               │
                               Local exports / Power BI
```

Validation, policy enforcement và trace áp dụng tại từng boundary. Gateway kiểm tra cả user question, context, schema, nhãn dimension, tool results và dữ liệu được gửi ở lượt kế tiếp.

Không có module LLM nào import trực tiếp provider SDK ngoài adapter được duyệt. Không có API lấy tùy ý file/path/network từ tool arguments. Runtime data sống ngoài source tree, ngoài thư mục được cloud-sync khi dùng dữ liệu nhạy cảm; thư mục dự án hiện tại chỉ chứa code và tài liệu.

## 6. Contracts cần thiết kế trước khi triển khai agent

Các tên dưới đây là ranh giới dữ liệu dự kiến; chỉ tạo model nào milestone đang dùng. Mỗi artifact có `schema_version`, `run_id` nếu thuộc run và các dependency revision tương ứng.

| Contract | Trường chính | Điều bất biến |
|---|---|---|
| DatasetRef | opaque ID, hash, bytes, row count, encoding, parser config | Model không nhận đường dẫn thật; file nguồn không bị sửa |
| ProfileReport | types, nulls, parse failures, cardinality, key statistics, date bounds, scope | Nêu rõ full scan hay sample; mặc định không xuất raw sample values |
| SemanticProposal | candidate mappings, evidence refs, unknowns, user decisions | Proposal chưa phải contract đã xác nhận |
| BusinessContract | grain, key policy, date, currency/scale, metrics, dimensions, null/return policies, coverage | Metric quyết định được công thức và phạm vi; unresolved critical semantics chặn analysis |
| DataPolicy | mode, approved endpoints/fields/aggregations/filters, label treatment, retention, resource limits, revision | LLM không sửa policy; không có policy hợp lệ thì không gửi ra ngoài |
| AnalysisRequest | question, metric ID, dimension candidates, periods, filters | Không dùng thời điểm hiện tại ngầm định để suy ra “quý trước” |
| ToolRequest | registered tool, typed arguments, call ID | Dùng metric/column IDs trong catalog; không nhận code thực thi |
| ToolResult | status, value fields, metric/filter/period scope, units, row counts, evidence ID, warnings | Kết quả thiếu/suppressed/error không được diễn giải thành 0 |
| Finding | claim type, template/text, typed numbers, evidence refs, limitations, validation records | Con số báo cáo phải trỏ tới field/path hoặc phép biến đổi được đăng ký |
| RunManifest | versions, hashes, model/adapter, policy revision, progress, counters, timestamps | Context đổi làm mất hiệu lực kết quả phụ thuộc |
| BISpec | KPI definitions, table/column/relationship specs, measures, visuals, dependencies | Measure/visual tham chiếu thành phần tồn tại và phù hợp contract |

Validation record dùng `passed / failed / not_checked / not_applicable`, kèm phương pháp, lý do, thời gian và phạm vi. Tách numerical, evidence-linkage và interpretation review. LLM reviewer hỗ trợ diễn giải nhưng không cấp chứng nhận calculation.

DAX có records riêng cho reference checks, syntax checks nếu có parser/engine, execution và reconciliation. Không gọi là syntax-validated nếu mới dò tên cột. Execution phải kèm model revision, context và kết quả; model đổi thì record cũ thành stale.

## 7. Quy tắc analytics để tránh phải đổi nền tảng sau này

### 7.1 Dữ liệu và semantics

- Business ID giữ leading zeros. Không xem dtype suy đoán là định nghĩa nghiệp vụ.
- M1–M2 dùng cột Revenue có sẵn. Công thức Discount/Quantity/Price chỉ thêm sau khi xác nhận đơn vị và định nghĩa; không dùng `eval` cho expression.
- Dòng trùng hoàn toàn, nhóm khóa trùng, số dòng thuộc nhóm trùng và số dòng dư là bốn số khác nhau.
- Khóa chưa xác định không mặc nhiên làm mọi phân tích vô hiệu: tác vụ cần tính duy nhất phải bị chặn; tác vụ sum chỉ chạy khi grain/revenue và chính sách duplicate đã xác nhận đủ để tránh double count.
- Không tự drop duplicate, impute null, loại outlier, đổi currency hoặc loại returns. Mọi transformation được duyệt tạo dataset revision mới có lineage.
- Null metric mặc định chặn metric đó; chỉ loại trừ nếu có quy tắc rõ và nêu số dòng/số tiền liên quan. Null dimension được đưa vào nhóm Unknown khi chính sách cho phép.
- Negative revenue có thể là returns; flag và áp dụng định nghĩa đã xác nhận, không mặc định coi là lỗi.
- Số tiền dùng fixed-point theo currency scale đã khai báo; kiểm tra overflow trước phép cộng. Scale 0 cho VND trong fixture, scale 2 cho fixture USD. Không làm tròn dữ liệu nguồn âm thầm; tỷ lệ chỉ làm tròn khi hiển thị.

### 7.2 Kỳ so sánh

- Giao diện có thể dùng ngày đầu/cuối inclusive; core chuẩn hóa về khoảng `[start, end)` và hiển thị rõ.
- Khai báo cột ngày, timezone nếu timestamp, fiscal/calendar convention và `as_of_date` khi cần.
- Câu hỏi “quý trước” phải được resolve và hiển thị hai kỳ cụ thể trước khi phân tích.
- Min/max ngày không chứng minh dataset đầy đủ. Coverage lấy từ metadata người dùng xác nhận hoặc ghi là unknown; không khẳng định suy giảm kinh doanh khi có thể chỉ thiếu dữ liệu.
- Phân biệt no observations, known zero activity và unavailable/suppressed results.
- Kỳ chồng lặp bị từ chối trong MVP. Kỳ có độ dài khác nhau vẫn có thể so tổng nếu nêu rõ; không tự chuẩn hóa theo ngày.
- Baseline bằng 0: absolute delta có thể tính; growth % trả null với lý do. Baseline âm: MVP không diễn giải growth % thông thường; báo số tuyệt đối và hạn chế.

### 7.3 Phân rã đóng góp

- `delta = current - previous`; `net_contribution_pct = 100 × segment_delta / overall_delta`.
- Overall delta bằng 0: contribution null. Contribution âm hoặc lớn hơn 100% có thể hợp lệ.
- Đối soát tổng chỉ với partition không chồng lặp, cùng filters, cùng kỳ, cùng metric và bao phủ đầy đủ.
- Nhóm chỉ xuất hiện ở một kỳ: outer alignment; điền 0 chỉ nếu dữ liệu/phạm vi xác nhận không có hoạt động, không phải thiếu/suppressed.
- Không cộng contribution ở cấp toàn công ty với contribution điều kiện trong riêng South. Mỗi kết quả ghi scope và denominator.
- Top-N phải có quy tắc tie ổn định và nhóm Other nếu được phép. Không xuất grand total + mọi nhóm còn lại nếu nó làm suy ra nhóm bị bảo vệ.
- Absolute share, price-volume-mix và ratio decomposition là phương pháp riêng; không gắn cùng một nhãn contribution.

### 7.4 Nội dung kết luận

Mỗi claim thuộc `observation`, `contribution`, `hypothesis` hoặc `recommendation`. Attribution kế toán không chứng minh nhân quả. Outlier/correlation không tự chứng minh lỗi hoặc nguyên nhân. Chưa đưa kiểm định thống kê vào MVP; thêm sau phải nêu assumptions, sample size và xử lý multiple comparisons khi cần.

Report ưu tiên số liệu được render từ typed fields, tránh để LLM tự gõ lại số. Hypothesis giữ trạng thái proposed/supported_by_observation/contradicted/inconclusive và evidence liên quan; không dùng nhãn “causally proven”.

## 8. Agent runtime và xử lý gián đoạn

State chính:

`CREATED → INGESTED → PROFILED → AWAITING_SEMANTICS → READY → ANALYZING → REVIEWING → COMPLETED`

Các nhánh: `NEEDS_INPUT`, `PARTIAL`, `FAILED`, `CANCELLED`, `EXPIRED`. Policy block ghi reason code và dừng hành động phụ thuộc. BI export là một bước riêng từ kết quả còn hiệu lực.

- Mỗi model step chọn tool hợp lệ, hỏi thông tin còn thiếu hoặc kết thúc. Model không quyết định quyền.
- Kế hoạch hiển thị là tóm tắt hành động và lý do ngắn gọn, không yêu cầu xuất nội dung suy luận nội bộ của model.
- Khởi điểm: tối đa 12 tool calls, 2 retries cho lỗi transient, 1 lần sửa structured response sai, 180 giây cho một run phân tích. Đây là budget đề xuất để benchmark, không phải SLA.
- Trước mỗi call kiểm tra phần budget còn lại. Retry tính vào budget; dùng backoff và tránh lặp tool arguments y hệt khi không có dữ liệu mới.
- Tool computation có timeout riêng, cancellation và cơ chế worker có thể dừng nếu cần. Timeout wrapper không được giả vờ đã hủy một phép tính vẫn chạy nền.
- Network failure giữ checkpoint local. Resume kiểm tra dataset/contract/policy/version trước; không tự gửi tiếp khi policy đổi hoặc dữ liệu đã hết hạn.
- Tool lỗi không trở thành kết quả 0. Partial report chỉ chứa kết quả đã hoàn thành và còn hợp lệ, có nhãn thiếu phần nào.
- Cache key gồm dataset hash + contract revision + tool version + normalized arguments; mọi lần sử dụng lại vẫn kiểm tra policy hiện tại. Không cache dùng chung giữa run/user không cùng phạm vi quyền.
- Atomic write qua file tạm rồi rename trong cùng filesystem; manifest chỉ đánh dấu hoàn thành sau khi artifacts đã ghi đủ.

## 9. Security baseline

Thiết kế chi tiết, threat matrix và nghiệm thu nằm trong [SECURITY_AND_FAILURE_MODES.md](SECURITY_AND_FAILURE_MODES.md).

Ba chế độ được phân biệt:

1. `demo_cloud`: chỉ dữ liệu giả lập/công khai đã khai báo; endpoint và fields được cho phép.
2. `restricted_cloud`: dữ liệu thật, chỉ mở sau đánh giá và phê duyệt phạm vi sử dụng; không thuộc MVP release.
3. `local_only`: không gọi external model; dùng manual semantics, deterministic report hoặc model nội bộ nếu đã kiểm chứng. Không giả vờ có AI khi chưa có local model.

Mặc định local_only và không có network credentials. Đổi chế độ là cấu hình có chủ đích. UI preview payload hỗ trợ minh bạch; không thay quyền của người sở hữu dữ liệu.

Mọi dữ liệu derived, evidence, business context, tên schema, nhãn và exports đều có thể nhạy cảm. Redaction/aggregation không đồng nghĩa anonymity. Không tự nâng cấp local prototype thành enterprise deployment.

## 10. Stack và cấu trúc dự kiến

- Python + Pandas + Pydantic; chọn phiên bản tương thích đã thử ở M0 rồi lock dependency.
- pytest cho unit/integration/known-answer cases; static checks gọn và formatter.
- CLI trước; Streamlit là lựa chọn UI local ở M3 nếu phù hợp kiểm soát session/lưu trữ. Core không phụ thuộc UI framework.
- Một provider adapter đầu tiên, mock adapter cho offline tests; không xây bộ abstraction cho mọi provider.
- JSON artifacts và run directory local. Chưa cần PostgreSQL, Redis, queue, Docker orchestration, LangGraph hay DuckDB.
- Chỉ thêm DuckDB khi benchmark hoặc yêu cầu SQL biện minh; chỉ thêm workflow framework khi manual loop khó duy trì và đã có eval để bảo vệ hành vi.

```text
src/bi_analyst/
  contracts/       typed schemas thực sự đang dùng
  data/            ingestion, profiling, normalization
  analytics/       metric operations và tool registry
  security/        policy, safe payloads, limits
  runtime/         state, executor, gateway, provider adapter
  evidence/        findings, validation, local store
  bi/              planner, specifications, export
  interfaces/      CLI và UI
tests/
  fixtures/        chỉ dữ liệu giả lập
  unit/
  integration/
  evaluation/
docs/
examples/          cấu hình và output giả lập
```

Đây là bản đồ phát triển, không tạo tất cả thư mục/module rỗng ngay ở M1. Runtime data directory được cấu hình riêng, không nằm trong repo.

## 11. Roadmap và tiêu chí hoàn thành

Ước lượng là giờ tập trung cho một người, gồm học vừa đủ, code, kiểm tra và ghi tài liệu; chưa có vận tốc thực tế. Đánh giá lại sau M1 và M2.

| Mốc | Đầu ra và gate | Phụ thuộc | Ước lượng |
|---|---|---|---|
| M0 — Feasibility | Chốt đường chạy Python, Power BI, fixture semantics, provider/budget; ghi các mục còn pending | Kế hoạch này | 4–8 giờ |
| M1 — Foundation | Loader, profiler, manual contract, data policy, local artifacts, negative tests | Phần Python/dataset M0 | 16–24 giờ |
| M2 — Trusted analytics | 3 tools aggregate/compare/breakdown, independent expected answers, scope/precision checks | M1 | 18–30 giờ |
| M3 — Agent MVP | Gateway, mock/live adapter, loop, state, evidence, semantic confirmation UI, giới hạn runtime | M2; provider/budget nếu live | 24–40 giờ |
| M4 — Investigation | Multi-step hypotheses, revision, abstention, frozen eval set và report | M3 | 16–28 giờ |
| M5 — BI Planner | KPI/model/measure/visual specs có dependencies và static checks | M4 | 16–28 giờ |
| M6 — Power BI verification | Report mẫu, chạy DAX và đối chiếu context, ghi khác biệt/null semantics | M5; Power BI M0 | 12–24 giờ |
| M7 — Portfolio release | UX, walkthrough, docs, release evaluation và reproducibility | M6 | 12–20 giờ |

Tổng baseline: 118–202 giờ; dự phòng khoảng 25% cho điều tra lỗi và học sâu: khoảng 150–255 giờ. Với 10–15 giờ/tuần, khoảng 10–26 tuần là phạm vi lập kế hoạch, không phải cam kết ngày giao. MVP M0–M3: 62–102 giờ trước dự phòng. Không cần dùng hết dự phòng nếu gates đạt sớm.

Critical path: M1 → M2 → M3 → M4 → M5 → M6 → M7. Power BI feasibility chạy sớm ở M0; thiếu môi trường không chặn M1–M5 nhưng chặn lời hứa M6/release đầy đủ. Không mua license/máy ảo để lấp dependency mà chưa có quyết định của người dùng.

### Gate từng mốc

- M0: có fixture description và thử được toolchain; Power BI/provider có kết quả thử hoặc trạng thái pending, chi phí/phụ thuộc được ghi rõ.
- M1: hoàn thành toàn bộ [M1 checklist](M1_IMPLEMENTATION_PLAN.md); không cần LLM/API.
- M2: known-answer và invariants đạt; không còn sai total/scope/precision đã biết.
- M3: một câu hỏi chạy end-to-end qua tool loop thực tế; evidence và boundary checks hoạt động; offline tests không gọi mạng.
- M4: eval nhiều bước lặp lại được về phép tính, có thay đổi hướng khi evidence bác giả thuyết, có abstain đúng.
- M5: không xuất metric không có dữ liệu; model/measure/visual hợp lệ về tham chiếu; chưa chạy DAX ghi not_checked ở execution.
- M6: tổng và ít nhất các context date/region/product/combined/empty khớp reference trong tolerance khai báo. BLANK và 0 được xét riêng. Không đánh dấu toàn bộ DAX đúng chỉ từ một context.
- M7: người khác chạy từ hướng dẫn sạch; có sample report, demo và eval report; không có dữ liệu thật/secrets trong artifacts công khai.

## 12. Evaluation, chất lượng và chi phí

### Bộ kiểm thử

- Unit: parsing/precision, periods, key counts, normalized arguments, policy decisions.
- Integration: load → profile → contract → tool → evidence → report; checkpoints/retries/cleanup.
- Known-answer: fixture nhỏ kiểm tra tay hoặc phép tính độc lập; fixture lớn để benchmark.
- Agent eval: khoảng 20 scenario đầu tiên, gồm câu hỏi rõ, mơ hồ, thiếu dữ liệu, giả thuyết sai, gọi tool lỗi và prompt injection. Tách dev set khỏi frozen acceptance set.
- Live acceptance chạy mỗi scenario 3 lần ở cấu hình cố định để thấy biến động. Không bắt agent có một chuỗi tool call duy nhất; chấm phép kiểm tra có đủ, đúng scope và tiết kiệm hay không.
- Provider/model/prompt thay đổi phải chạy lại tập eval liên quan. Replay tools không đồng nghĩa model sẽ sinh nguyên văn giống nhau.

### Release targets ban đầu

| Chỉ tiêu | Gate đề xuất |
|---|---|
| Deterministic analytics | 100% case bắt buộc khớp expected/tolerance |
| Số liệu trong completed findings | 100% truy được về đúng evidence và phép biến đổi cho phép |
| Completion cho câu hỏi được hỗ trợ | Ít nhất 90% trên tập acceptance và các lần lặp đã công bố |
| Critical unsupported claims | 0 trong tập acceptance; nhận định nhân quả thiếu bằng chứng chặn release |
| Privacy/access control cases | 0 forbidden egress hoặc cross-run access trong bộ bắt buộc |
| Abstain khi thiếu dữ liệu/quyền | 100% case bắt buộc không vượt giới hạn |
| DAX | Chỉ báo reconciled cho measures/contexts đã thực thi và đối chiếu |

Các con số này là mục tiêu trên tập kiểm thử hữu hạn, không chứng nhận hệ thống đúng/an toàn trong mọi tình huống. Eval report phải nêu mẫu số, lỗi, retries, model/version và chi phí.

Latency, memory và cost là số đo cần thu ở M2/M3. Ghi thời gian theo stage, input size, p50/p95 khi đủ mẫu, model tokens, retries. Không tuyên bố p95 từ vài run. Ngân sách tiền được cấu hình trước live run và có cảnh báo/dừng, không hardcode giá API chưa xác minh.

## 13. Cách làm việc để học và hạn chế sửa lớn

Mỗi task theo chu kỳ: câu hỏi cần giải quyết → input/output mẫu → invariant → implementation nhỏ → test có ý nghĩa → đọc diff → ghi quyết định. Mỗi task nên có thể hoàn thành trong 1–4 giờ tập trung.

Vai trò người học: xác nhận ý nghĩa business, giải thích được dữ liệu/state/loop, thử một case bất thường và review output. Vai trò trợ lý: làm rõ tradeoff, thực hiện task đang được giao, kiểm tra và báo bằng chứng; không dựng toàn bộ dự án vượt milestone được chọn.

Trước khi chuyển milestone, ghi: đầu ra, test đã chạy, lỗi còn mở, phần chưa biết, chi phí/thời gian thực tế và thay đổi estimate. Chỉ sửa thiết kế khi có requirement hoặc bằng chứng mới; lưu lý do thay đổi, không viết lại kiến trúc vì tên framework mới.

Khi đổi contract/schema: tăng version, có loader kiểm tra version; hỗ trợ migration cho artifact cần giữ hoặc từ chối với lỗi rõ. Không đọc artifact cũ theo nghĩa mới âm thầm. Thay policy nghiêm hơn phải áp dụng ngay cho mọi egress tiếp theo.

Các extension chỉ cần đường nối: tool registry, provider adapter, BISpec và schema_version. Không viết sẵn multi-tenancy, distributed tracing hay generic plugin system nếu chưa có người dùng/yêu cầu.

## 14. Rủi ro và quyết định còn mở

| Rủi ro | Mức ưu tiên | Hành động |
|---|---|---|
| Hiểu sai grain/revenue | Cao | Fixture có đáp án; semantics gate trước analysis |
| Số liệu nhạy cảm bị gửi qua tool result/log | Cao | Gateway toàn diện + canary tests + mặc định deny |
| Model suy luận hay nhưng gọi tools sai | Cao | Typed executor + eval + giới hạn actions |
| Môi trường Power BI không khả dụng | Cao | Spike M0; giữ integration là gate thật |
| Scope tăng thành platform tổng quát | Cao | Khóa MVP; extension có business case và tests |
| Privacy suy luận từ nhiều aggregates | Cao cho dữ liệu thật | Không coi nhóm lớn là đủ; restricted_cloud cần threat review riêng |
| Chi phí API/retries tăng | Trung bình | Budget/counters/timeouts; mock tests mặc định |
| Reproducibility bị hiểu là model deterministic | Trung bình | Lưu config và evidence; công bố biến động live runs |
| Quá nhiều tuần chỉ viết nền tảng | Trung bình | M1/M2 có report/CLI demo nhỏ, M3 có luồng người dùng sớm |

Các input chưa biết không chặn kế hoạch: số giờ học mỗi tuần, provider/budget, nguồn Windows, dataset thật tương lai. Không tự suy ra quyền dùng dữ liệu doanh nghiệp từ việc người dùng có file.

## 15. Bước thực hiện kế tiếp

1. M0: kiểm tra Python/dependency trong môi trường riêng bằng fixture giả lập; xác định đường chạy Power BI và provider/budget.
2. M1: theo từng task trong [M1_IMPLEMENTATION_PLAN.md](M1_IMPLEMENTATION_PLAN.md).
3. Theo yêu cầu tiếp tục thực hiện đến Power BI, các bước tiếp theo và blockers được cập nhật ở IMPLEMENTATION_STATUS.md.

Code đã được triển khai trong src/bi_analyst. Các “gate” và “target” phía trên vẫn là tiêu chí; chỉ coi đã pass khi có bằng chứng trong IMPLEMENTATION_STATUS.md và deliverables/verification.
