# Dashboard refresh và sửa lỗi trải nghiệm — gói giao Luna 5.6

Ngày: 25/09/2026. Trạng thái: thiết kế và kế hoạch; chưa implement ứng dụng/PBIR.
Yêu cầu mới của người dùng: sửa mẫu dashboard còn sơ sài và lập plan rõ để Luna
5.6 thực hiện. Bản xem trước: `design/dashboard_refresh_preview.html` (bản nội bộ, không phân phối).
Mẫu HTML là design reference bằng dữ liệu synthetic, không phải bằng chứng Power BI render.

## 1. Quyết định đã chốt

- Giữ Python, Streamlit, ba deterministic tools, một agent, Revenue additive,
  Region/Product, hai kỳ explicit và independent validation.
- Lượt này giao mẫu thiết kế và task cards. Việc build ứng dụng theo task cards
  là lượt execute tiếp theo; không coi plan hoặc HTML là code ứng dụng đã sửa.
- Thiết kế lại lớp trình bày; không thay analytics, DAX formulas, nghĩa của
  coverage/null, accepted finding rules hoặc các ngưỡng evaluation.
- Cloud OFF. Lựa chọn AI chưa hoạt động trong app phải được mô tả đúng và khóa
  trong UI; không mở transport thật để làm cho nút đó chạy.
- Báo cáo mới là revision riêng: `deliverables/PowerBI_Demo_Refresh_R1`.
  Giữ nguyên Candidate đã pass, Current local và mọi hồ sơ verification lịch sử.
- Bộ thực hiện ưu tiên: sửa reproducibility → UX trung thực → trình bày Streamlit
  → Power BI candidate mới → nghiệm thu. Không đổi frontend framework.

Ngoại lệ được yêu cầu mới cho phép đối với frozen v1: đổi bố cục/formatting/type
của visual hiện có; chuyển scope sang trang hai; thêm bốn text objects và một
cột string chỉ để trình bày `Evidence.ScopeLabel` từ scope đã validate. V1 vẫn
là 2 pages/9 visuals. Thiết kế mới là **2 pages/13 objects: 9 data visuals và 4
text objects**. Không được ghi đè hay đổi nhãn pass của v1 thành v2. Đây là
presentation amendment; không phải mở lại architecture.

Inventory 13 áp dụng demo có cả Region và Product. Request hợp lệ chỉ chọn tập
con dimension vẫn phải hoạt động: không tự thêm dimension/claim; bỏ panel không
được yêu cầu và nới panel còn lại theo layout variant khóa trước. Số data visuals
của variant = 7 + số requested dimensions (4 KPI + tháng + evidence + scope +
breakdowns), cộng 4 text objects. Không đổi request chỉ để đủ số visuals.

## 2. Vấn đề thực tế và độ chắc chắn

| ID | Bằng chứng | Hành động |
|---|---|---|
| B01 | `tests/test_m5_bridge_resume.py:16–23` đọc bridge trong `tmp/`; bridge không tracked. Chạy test từ archive HEAD thất bại FileNotFoundError | Tách rõ kiểm thử công cụ vận hành lịch sử khỏi public application suite; giữ lịch sử và công bố lại denominator |
| B02 | `scripts/build_demo.py:258–259` đọc `t15-current-before.sha256` không có trong public bundle. Chạy build từ archive thất bại trước generate | Làm public build tự tái lập với tracked baseline/manifest, output và verification mới riêng |
| U01 | `ui.py` cho chọn LLM và gọi `OpenAIAdapter`; `provider.py` vẫn chặn live transport. M5 có adapter riêng | Disable/hide những controls live chưa hỗ trợ, giải thích đúng capability |
| U02 | Ảnh public page 1: title KPI bị cắt, hai chiều biến động cùng màu, raw hash/JSON trong bảng scope | Format business-first; chuyển diagnostics khỏi trang tổng quan |
| U03 | Ảnh public page 2: chỉ bảy dòng table ở đầu trang, khoảng trống lớn, thông tin scope thiếu gần finding | Bố cục evidence + scope, chiều rộng/độ cao đúng nội dung |
| U04 | `ui.py`: "Tao xác nhận", cột label/previous/delta/net_contribution_pct, validation JSON mở khi lỗi | Đổi câu chữ và nhãn; lỗi có hướng xử lý cụ thể |
| U05 | `ui.py` hiển thị mọi breakdown nhưng tiêu đề chỉ có dimension | Thêm scope rõ; test root/drill-down trộn thứ tự trước khi kết luận bug cụ thể |
| D01 | README dẫn clean-run evidence đã loại khỏi public set | Chỉnh link/public evidence index; không công bố lại runtime riêng tư để sửa link |

B01/B02 được tái hiện ngày 25/09/2026 trên `git archive HEAD` của local commit
`c58df7a1b58497489a8ee2f6452cc5ae5093458f`. Probe dùng Python của venv hiện có,
không phải clean-install test. B01: một test fail ở BRIDGE_PATH.read_text.
B02: build_demo fail ở before_path.read_text. Đây là evidence mới, không phủ nhận
382 passed/2 skipped đã được ghi nhận trong workspace đầy đủ; không được dùng
kết quả cũ để mô tả suite của bản tải từ GitHub.

Không xác nhận các phê bình "không có chart", "mọi null đều lỗi", "thường xuyên
timeout". Code có KPI/bar charts và null policy. Không sửa analytics vì các
khẳng định chưa được tái hiện.

## 3. Thiết kế dashboard mới

### 3.1 Câu hỏi phải trả lời ngay ở trang đầu

1. So sánh kỳ nào, metric/unit nào, phạm vi nào?
2. Doanh thu trước/sau và thay đổi bao nhiêu?
3. Region/Product nào tăng/giảm, các biến động bù trừ ra sao?
4. Số liệu có giới hạn gì và cần điều tra điều gì tiếp?

Nền `#F3F6FA`; panel trắng; heading `#142D4E`; body `#334155`; positive
`#087F72`; negative `#B54734`; warning `#9A6700`. Font Segoe UI/system sans;
không web font/CDN. Money hiển thị đủ chữ số trong KPI, có VND. Dấu +/- và nhãn
số là bắt buộc, không chỉ dựa vào màu. Không gradient/shadow nặng, gauge hoặc pie.
Canvas Power BI 1280×800; padding 24; gap 16–20; body 12–14 px tối thiểu ở canvas,
title 18–28, KPI 28–34. Native fit-to-page có thể scale: nghiệm thu bằng mắt ở
1366×768 và full-size, sửa nếu chữ bị cắt/không đọc được.

### 3.2 Trang 1 — Tổng quan doanh thu (9 objects)

| Object | x,y,w,h | Nội dung/binding |
|---|---|---|
| T01 header (mới) | 24,16,1232,80 | Tên report; kỳ trước/kỳ này; VND; synthetic; scope gốc; 31/28 ngày |
| K01 giữ ID kpi0 | 24,116,296,116 | Revenue Previous Period; title "Kỳ trước" |
| K02 giữ ID kpi1 | 336,116,296,116 | Revenue Current Period; title "Kỳ hiện tại" |
| K03 giữ ID kpi2 | 648,116,296,116 | Revenue Change; dấu và màu theo chiều |
| K04 giữ ID kpi3 | 960,116,296,116 | Revenue Growth %; ratio×100 một lần khi format |
| C01 giữ ID breakdown0 | 24,252,608,268 | DimRegion.Region → Revenue Change; diverging bar; zero baseline |
| C02 giữ ID breakdown1 | 648,252,608,268 | DimProduct.Product → Revenue Change; diverging bar |
| C03 giữ ID trend | 24,540,448,236 | DimDate.Month → Revenue; đổi sang native column chart có reference hợp lệ |
| T02 nhận xét (mới) | 492,540,764,236 | Accepted observations + caveats; giữ root scope cố định |

Giữ chronological sort Month/MonthKey hiện có; với đúng hai tháng, nhãn
"Doanh thu quan sát theo tháng" và lưu ý "2 điểm quan sát, chưa kết luận xu hướng".
Không nội suy ngày, thêm forecast, chuẩn hóa theo ngày hay giả dữ liệu nhiều tháng.
Bar labels có số signed; scale/trục không bóp méo. Nếu nhiều nhóm, không cắt nhóm
âm/unknown để tạo câu chuyện đẹp; overflow có scroll hoặc top-N có nhãn và phần
còn lại đầy đủ. Default revision này không áp dụng top-N aggregation mới.

T02 chỉ render template từ accepted candidates/root scope; không dùng model
viết lại và không gọi analytics. Câu hành động dạng "Cần kiểm tra thêm bối cảnh
bán hàng ở các nhóm giảm" là câu hỏi/next step, không phải causal finding.
Nếu không có đủ accepted claims tương ứng, bỏ câu đó; không hardcode số demo.
Không dùng từ "nguyên nhân" để mô tả contribution.

### 3.3 Trang 2 — Bằng chứng & phạm vi (4 objects)

| Object | x,y,w,h | Nội dung/binding |
|---|---|---|
| T03 header (mới) | 24,16,1232,80 | Phạm vi gốc của lượt; từng finding có phạm vi riêng ở cột Phạm vi |
| E01 giữ ID findings | 24,116,796,536 | Values projections chính xác: FindingID, Finding, ScopeLabel, Status; wrap |
| S01 giữ ID scope, đổi page | 840,116,416,536 | AnalysisInfo.Property/Value, scope/coverage/periods/limitations |
| T04 caveat (mới) | 24,672,1232,104 | Nghĩa coverage; không suy causal; cách tra raw evidence ngoài report |

Các cột EvidenceID/ScopeJSON/ValidationJSON vẫn giữ nguyên trong semantic model
và evidence.json, không drop để làm đẹp. Bảng S01 ưu tiên Property mang nghĩa
nghiệp vụ (Coverage, Previous, Current, Scope, Analysis sufficiency, Interpretation,
Analysis limitation); raw hash/JSON truy cập trong artifact đi kèm. Có thể dùng
visual-level filter Property để ẩn raw metadata khỏi canvas; không sửa model rows.
FindingID là reference ngắn đã có, không bịa hyperlink drill-through. ClaimType
giữ trong model/artifact, không cần thêm vào E01. Thay projections E01 hiện tại
`FindingID,Finding,EvidenceID,Status` bằng list nêu trên là exception explicit.

`ScopeLabel` là cột trình bày string mới duy nhất, được exporter tạo từ chính
`record.candidate.scope` và `candidate.label` đã validate. Phải có metric, unit,
scale, hai khoảng [start,end), tất cả filters và dimension/group nếu có. Có thể
dùng xuống dòng và nhãn tiếng Việt; không chỉ viết "theo scope gốc". Không cắt
filter values hoặc bỏ empty/null distinction. Không thêm quan hệ/measure/table,
không sửa ScopeJSON, candidate, validator hoặc authoritative artifact schema.
Ví dụ root North và North trong Product=Anchor phải khác rõ ở Phạm vi, dù cùng
tên nhóm. Mọi hàng hiển thị ScopeLabel mặc định; raw ScopeJSON vẫn đi kèm model
và evidence.json để đối chiếu, không dùng tooltip ẩn làm cách duy nhất đọc scope.
Cho phép cuộn dọc bảng evidence nếu scope dài; text phải wrap, không mất thông
tin hoặc co font dưới tiêu chí. Header không được gọi mọi finding là root.

HTML details là tiện ích preview; PBIR không có HTML details tương đương, dùng
artifact đi kèm hoặc tooltip/column đã kiểm chứng, không hứa tương tác chưa build.

### 3.4 Scope và interaction contract

- Đây là báo cáo snapshot của câu hỏi đã xác nhận. Caption phải ghi các filters
  gốc (hoặc "Tất cả trong phạm vi dữ liệu đã xuất").
- Không thêm slicer, filter panel hay drilldown mới trong batch này. Default
  chart-to-chart selection không được thay số KPI mà để narrative giữ scope cũ:
  cấu hình none cho cross-filter/highlight ở overview bằng cấu trúc PBIR có
  reference; native test click từng bar phải xác nhận. Không đoán property name.
- Finding/evidence là root hoặc narrowed scope riêng đã validate, không tự đổi
  theo Power BI user filter. Label root scope phải tồn tại ở trang evidence.
- Native Filter pane/edit-mode nếu người dùng tự sửa ngoài layout mặc định không
  sinh lại findings. Phải có caption nói rõ evidence thuộc analysis scope gốc.
- Hai partition Region và Product giải thích cùng net: không cộng contribution
  giữa chúng. Net zero: giữ +/− observations, tỷ lệ không xác định là unavailable.
- Partial/abstained không có full PBIP mới. Scope không xác nhận không được vẽ
  badge "Dữ liệu hoàn chỉnh". Coverage chỉ là xác nhận của người cung cấp.

### 3.5 Known answers của mẫu

Nguồn: Candidate `business_case_summary.json`, `verification_cases.json`,
`demo_sales.csv`; cùng seed/fixture đang được dùng, không đổi dataset để làm đẹp.

| Mục | Giá trị chính xác |
|---|---|
| Previous / Current | 943363 / 1003363 VND |
| Delta / growth ratio | 60000 / 0.0636022400708953 |
| Growth display | +6,36% (làm tròn 2 số; không đổi stored ratio) |
| Region | North +122000; South -42000; West -20000 |
| Product | Anchor +80000; Growth -15000; Stable -5000 |
| Kỳ | [2026-01-01,2026-02-01) và [2026-02-01,2026-03-01) |
| Accepted findings | 7 (F001–F007); IDs/text/scope từ artifact, không tự cấp pass |

Region/ Product labels giữ nguyên dữ liệu; currency và format theo contract khi
chạy dataset khác, không mặc định mọi dataset là VND scale 0. Mẫu có 18 dòng
synthetic, không phải doanh thu khách hàng thật.

## 4. Task cards — tuần tự, không build một lượt context khổng lồ

### G0 — Sửa public reproducibility (B01/B02/D01)

Đọc/sửa: `tests/test_m5_bridge_resume.py`, `scripts/build_demo.py`,
`scripts/validate_powerbi.py`, tests comparator trực tiếp,
`.github/workflows/tests.yml`, `.gitignore`, README/evidence index; chỉ direct
helper/test phục vụ build nếu cần. Không đọc toàn bộ lịch sử live config/secret.

1. Tái hiện B01 và B02 trên một archive/clone sạch; ghi command, commit, failure.
2. B01 default: đây là suite của one-time historical r2 key bridge không được
   phân phối. Giữ nguyên test và bridge nội bộ ở workspace recoverable; tách suite
   vận hành ấy ra khỏi public `tests/` bằng đường dẫn local-only rõ. Ghi chính xác
   test IDs/count tách ra và lý do; regression app/agent/security vẫn chạy đầy đủ.
   Không thêm skip vì thiếu file, `pytest -k not ...`, mock production guard bằng
   bản tự viết, hoặc xóa assertion để giữ số 382. Nếu xác minh guard đó vẫn là
   capability public thì phải đưa helper sanitized được dùng thật + fixture vào
   repo và test helper đó; không publish toàn operational bridge/config.
3. B02: build-demo public dùng baseline tracked Candidate, có explicit baseline,
   output và verification destination. Không cần Current/máy tác giả/historical
   manifest. Guard protected-tree before/after vẫn có ý nghĩa; generated outputs
   không viết đè `t15-*` hay revision cũ. Preserve seed và independent oracle.
   Default build phải chạy từ clean clone; từ chối đè existing output/baseline.
   **Dependency cần sửa ngay tại G0:** legacy `compare_powerbi_projects` chỉ
   phục vụ pre-T14→T14. Đã probe Candidate so với chính nó vẫn fail schema
   Evidence vì cột ScopeJSON/ValidationJSON có sẵn ở baseline. Thêm comparator
   exact-equality dành cho tracked post-T14 baseline (schema, DAX, relationships,
   PBIR IDs/roles/layout), dùng nó trong public v1 build. Giữ nguyên comparator
   legacy và tests của nó. Self-parity phải pass; mutation thực phải fail. P1
   tái dùng invariants checker này với presentation allowlist, không đợi P1
   mới giải quyết dependency baseline của G0.
4. D01 sửa links về evidence thực sự nằm trong publish set hoặc ghi rõ local-only.
   Không thêm runtime/secret vào repo chỉ để link hết 404.

Tests: clean public archive import/pytest/build; missing baseline báo rõ; existing
output/protected path bị từ chối; before/after hashes; cùng seed cùng known answers.
Ruff + full suite public phải chạy thật, counts mới tách khỏi historical workspace.
Review G0: Astra High về không giấu test lỗi và không nới trust boundary.

### U1 — Capability và lỗi dễ hiểu (U01/U04)

Files: `src/bi_analyst/ui.py`, `tests/test_ui.py`; tối đa một UI presentation
helper nếu giảm lặp thực sự. Không chỉnh transport/provider/runtime để mở cloud.

- Mode mặc định rõ "Phân tích cục bộ bằng Python". LLM lựa chọn unavailable với
  lời giải thích "Đã đánh giá riêng; chưa bật trong ứng dụng"; tương tự nút LLM
  đề xuất mappings. Không suy quyền live từ API key hoặc checkbox semantics.
- Đổi "Tao xác nhận" → "Tôi xác nhận". Mapping có ví dụ grain line-item; currency,
  format ngày, coverage có help cụ thể; vẫn require xác nhận thực sự.
- Trình bày validation issue theo code → vấn đề/count → bước khắc phục; mã/raw JSON
  trong expander. Không bịa row IDs nếu profiler chưa trả row-level diagnostics.
- Null reject/exclude, date parse, missing mappings, duplicate/coverage unknown
  có lời hướng dẫn đúng policy hiện có. Không clean tự động, không hạ error thành
  warning, không đổi unknown thành zero để tránh chặn.
- Tách lỗi execution với kết quả partial/abstained. Partial vẫn xem/tải JSON hiện
  có và nêu lý do full Power BI unavailable.

Tests: controls unavailable không gọi adapter dù env có dummy key; semantics không
bật cloud; mock error codes map đúng; unknown code có fallback an toàn; status
artifact override compatibility metadata; export gate invariant giữ nguyên.
Không dùng assertion vị trí checkbox/button khi có label/key ổn định.

### U2 — Streamlit presentation tương ứng mẫu

Files: `ui.py`, `tests/test_ui.py`; helper presentation nếu U1 đã tạo thì dùng lại.
Giữ Streamlit/native charts trước; không bắt buộc thêm Plotly/dependency.

- Kết quả lên trước: câu hỏi/periods/scope/mode/status → 4 KPI → 2 breakdowns →
  accepted findings → giới hạn → evidence kỹ thuật thu gọn.
- Số tiền có grouping/currency, growth % đúng ratio/value hiện có; unavailable
  là "Chưa đủ dữ liệu", không 0. Giữ exact raw artifact cho download.
- Bảng nhãn tiếng Việt: Nhóm, Kỳ trước, Kỳ hiện tại, Chênh lệch, Đóng góp vào
  biến động ròng (%). Giải thích tỷ lệ có thể >100%, âm hoặc undefined; không gọi
  đó là market share và không vẽ pie.
- Root KPI dùng `root_evidence_ids`. Các chart phải matching root filters/periods;
  narrowed evidence hiện trong phần riêng có scope đầy đủ, không tiêu đề dimension
  mơ hồ. Không gọi tools từ formatter hoặc tạo findings mới.
- Chỉ đưa các chart có evidence hiện hữu. Monthly chart thuộc semantic model
  Power BI; không tự aggregate dataset trong Streamlit để bắt chước mẫu khi
  validated artifact chưa có monthly evidence.
- Không xây bộ sửa dữ liệu, download PDF/Excel generator, filter/drilldown UI mới
  trong task này. Bản partial có mô tả các quan sát được hỗ trợ và phần còn thiếu.

Tests: root/narrowed evidence đảo thứ tự; zero/negative/all-null/unavailable;
contribution denominator zero; long labels; stale/missing artifact; accepted-only
findings; HTML/text escaping dataset labels. Rerun targeted UI + data tests rồi
full regression/Ruff. Browser thật: success + partial + needs_input, viewport
1366×768, không raw hash/UUID chiếm trang kết quả mặc định.
Review U1/U2 chung một gate Astra High.

### P1 — Build Power BI refresh candidate

Files: `src/bi_analyst/bi.py` (`_visual`, `build_report`, direct export call),
`tests/test_powerbi.py`, `scripts/validate_powerbi.py`, `scripts/build_demo.py`
và tests trực tiếp của các scripts. Native scratch reference nếu cần ở thư mục
local/candidate riêng. Không sửa DAX formulas/analytics. Model schema chỉ cho phép
thêm đúng cột string `Evidence.ScopeLabel` như §3.3; các cột/bindings khác giữ nguyên.

1. Lấy Desktop-saved minimal reference cho native column chart, textbox,
   conditional colors/labels/title và interaction settings khi chưa có example.
   Chỉ đọc vendor schema tương ứng. Không đoán properties từ trí nhớ hoặc lấy
   JSON schema pass làm bằng chứng formatting hiển thị được.
2. Giữ PBIR schema/version, datasetReference, query projections đang hoạt động,
   ngoại trừ E01 đổi EvidenceID→ScopeLabel như §3.3 và C03 đổi type/role khi native
   reference đòi hỏi. Không thêm ClaimType vào query E01. Giữ
   IDs của 9 data visuals và page IDs; scope chuyển sang page evidence. 4 text
   objects có stable deterministic IDs, không random mỗi lần export.
3. `build_report` đang chỉ nhận request. Nếu cần T02 từ accepted claims, thêm
   argument keyword-only tối thiểu cho presentation data ở direct caller; dùng
   artifact exporter đã validate. Không load JSON tùy ý từ disk/hardcode demo
   hoặc đổi authoritative contract. Escape labels/text đúng JSON/PBIR.
4. Thực hiện palette/spacing/title/data label/zero baseline/signed formatting;
   bỏ auto display units K/M trong KPI demo đủ chỗ; body readable ở fit-to-page.
   Không đổi currency/scale calculations; property formatting phải từ contract.
5. Chốt layout manifest riêng `docs/design/dashboard_refresh_layout.json` trong
   task này: page/name/id/type/roles/rectangles/interactions/allowed differences
   theo bản thiết kế. Manifest được khóa/review trước regenerate, không generate
   expected bằng cách copy output hiện tại. Snapshot styles không thay oracle.
6. Giữ legacy `compare_powerbi_projects` strict cho v1. Thêm check v2 explicit
   so model/DAX/relationships/query bindings invariants và inventory/layout mới;
   allowlist model chỉ thêm đúng ScopeLabel:string ở Evidence và cột row tương
   ứng; phải xác minh từng value là render của đúng candidate scope/label. Không
   chỉ bỏ qua toàn bảng Evidence khi compare. E01 có exact projection exception.
   không xóa parity check hay đổi mọi "9" thành "13". C03 chỉ đổi type hợp lệ,
   roles cần thay thì có reference và allowlist chính xác; text không có query
   nhưng validators vẫn phải kiểm đủ mọi data visual, không skip visual tùy tiện.
7. Regenerate vào Refresh_R1; verification riêng dưới
   `deliverables/verification/dashboard_refresh_r1/`. RunStore và tools có thể
   chạy khi tạo analysis mới upstream; exporter/formatter không recompute findings.

Tests: exactly 2 pages / 9 data +4 text; IDs/roles/page order; bounds/no overlaps;
native reference structures; reference resolution; DAX strings unchanged;
semantics/accepted findings unchanged; schema chỉ thêm ScopeLabel đúng allowlist;
scope text dynamic theo candidate, không lấy root làm scope cho mọi row;
layout text không được orphan/cover chart; bad binding/schema vẫn fail; v1 legacy
validator vẫn bắt unexpected delta. Growth percent đúng một lần; sign/null cases.
Counterexample: root và narrowed findings cùng dimension/value, khác filter;
đảo thứ tự vẫn phải hiển thị hai ScopeLabel đúng, không re-scope accepted finding.
Static report execution/reconciliation/rendering mới đều `not_checked`.
Review P1: Astra High code + frozen candidate trước Desktop gate.

### V1 — Native verification, release packet và dừng

- Full Refresh đúng Refresh_R1 trong Desktop; 5 measures Ready. Chạy 7 oracle
  contexts /35 values như v1, money exact và growth tolerance 1e-12. Không tái
  dùng port/model session hay engine record cũ.
- Quan sát cả 2 pages/13 objects; KPI exact; signed bars; tháng đúng thứ tự;
  không cắt title/number, không chồng/canvas trắng; page 2 wrap đọc được; bar
  selection không đổi root KPI/narrative; limitation luôn nhìn thấy.
- Nếu UI không khả dụng: hoàn tất offline checks, giữ rendering `not_checked`,
  dừng với tối đa một thao tác thủ công. Không promote candidate.
- Khi đạt, tạo 2 ảnh public-safe, PDF và tùy chọn bản PBIX mẫu bằng Desktop
  Save As. PBIX mẫu phải mở lại được, có dữ liệu đã nạp và không đường dẫn nguồn
  máy tác giả. Đây là demo cố định; exporter app vẫn PBIP. Nếu không làm PBIX,
  ghi unavailable, không chặn acceptance PDF/ảnh/PBIP đã có.
- Với portable public archive của revision mới: clean venv/install/pytest/Ruff,
  build demo/static checks, success + partial UI; chạy CI nếu publication được
  yêu cầu. Local pass không tự là CI pass. Đường dẫn Windows/Linux phải rõ.
- Cập nhật README ảnh/business case trước, instructions, số test public thật,
  mode LLM thật, evidence index/progress. Không claim production-ready, live
  application AI hay khả năng data cleaning chưa triển khai.
- Astra High final review packet + hashes + native evidence. Có unverified gate
  thì bàn giao đúng trạng thái; không tự mở metric/project mới để bù.
- Publication không thuộc lượt lập mẫu/plan này. Chỉ publish revision đã đạt khi
  người dùng giao execute kèm yêu cầu cập nhật GitHub; không force-push local main
  (local initial commit và remote initial commits đã khác history).

## 5. Lệnh kiểm chứng dùng cho task cards

Lệnh đã có (chạy tại project, Windows):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_ui.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest tests/test_powerbi.py -q --tb=short
.\.venv\Scripts\python.exe -m pytest -q --tb=short
.\.venv\Scripts\ruff.exe check src scripts tests app.py run.py
.\.venv\Scripts\python.exe scripts/validate_powerbi.py deliverables/PowerBI_Demo_Refresh_R1
```

`python scripts/build_demo.py --output ...` hiện có nhưng đang lỗi clean archive
và khóa legacy layout. Chỉ dùng cho refresh sau G0/P1 đã sửa có explicit revision
mode/manifest; cú pháp option mới phải do task card ghi lại sau implement,
không copy command đoán sẵn. `check_powerbi_metadata.py --vm-id` là đường VM cũ,
không dùng thay Windows-native verification.

Native engine command đã có: `scripts/verify_powerbi.ps1 -Project <candidate>
-Port <port của đúng instance> -Cases <candidate/verification_cases.json>
-Output <verification mới/engine.json>`. Port là giá trị được phát hiện/xác minh,
không hardcode. File engine không tự chứng nhận rendering.

## 6. Không build trong batch

React/Next.js, multi-agent/RAG/framework mới, live provider enablement, thêm model,
forecast/churn/AOV/profit/Pareto, tự clean/impute, Waterfall tool mới, một BI
generator tổng quát, schema migration lớn, slicers làm narrative động, tự động
PBIX mọi upload, public hosting, enterprise security. Waterfall có thể cân nhắc
sau; diverging bars hiện có đã trả lời contribution và giảm rủi ro binding.

## 7. Routing, checkpoint và stop

Builder/fix: **gpt-5.6-luna / max**. Reviewer: **gpt-6-astra / high**, read-only,
context mới, không spawn reviewer con. Main không phải Luna thì dispatch đúng
builder; ghi requested model và thông tin host thực sự trả về, không coi prompt
là chứng cứ switch model. Một writer application; reviewers chỉ đọc candidate
đã đóng băng. Plan/design review không thay code review hoặc native verification.

Handoff mỗi card: task ID, allowlisted paths, dependencies, failures/oracles,
hashes/diff, commands/results, limitations, next task. Sau hai vòng sửa cùng lỗi
vẫn chưa đạt: dừng card, báo trigger/expected/actual và bounded diagnosis; không
tự chuyển Sol, giảm tiêu chuẩn, redeem credit hoặc chạy live.

DONE của batch: G0 reproducible public suite; U1/U2 honest/easy UI; P1 generator
deterministic + candidate; V1 native pass + ảnh + README + Astra accepted. Không
đòi số test cố định nhưng không silently drop application coverage. Nếu chưa có
UI gate thì chỉ được ghi offline-complete, không release-complete.

## 8. Prompt giao Luna 5.6

> Execute docs/DASHBOARD_REFRESH_LUNA_PLAN.md từ task pending đầu tiên. Đọc
> BUILD_PROGRESS để biết checkpoint, FLAGSHIP_EXECUTION_PLAN cho analytical
> invariants; presentation amendment trong plan này cho phép layout mới. Build
> gpt-5.6-luna max, Astra high review tại G0, U1/U2, P1 và V1. Một writer, task
> nhỏ, context mới cho reviewer. Bắt đầu tái hiện G0 từ public archive; không
> quét lại repository hoặc đoán source đã đúng chỉ vì historical tests pass.
> Sửa lần lượt G0 → U1 → U2 → P1 → V1 theo allowlists và known answers. Không
> sửa analytics/validators/DAX formulas; không bật cloud. Giữ nguyên Candidate,
> Current và historical evidence; xuất Refresh_R1 riêng. Dùng mẫu HTML làm
> design reference, không dùng HTML/schema pass làm chứng cứ Desktop render.
> Không tự publish. Tiếp tục các bước offline thực hiện được; chỉ dừng khi
> dependency/native UI thật sự cần người dùng, tối đa một thao tác mỗi lần.
> Quá hai repair rounds cùng lỗi dừng để tôi chuyển model. Báo test counts của
> public revision thật, native evidence, review verdict và next task. Dừng sau
> acceptance của batch, không thêm feature mới.

## 9. Các assumptions đã chốt để khỏi hỏi lại

- "Dashboard" ưu tiên mẫu Power BI; Streamlit dùng cùng ngôn ngữ thiết kế nhưng
  không giả bộ có dữ liệu monthly mà authoritative artifact chưa cung cấp.
- Đối tượng xem: analyst/quản lý đọc biến động doanh thu; portfolio Data/BI.
- Dùng lại dataset synthetic đã đối soát, hai trang, tiếng Việt, giữ label gốc.
- Chấp nhận thêm text objects làm đủ bối cảnh; không coi số 9 của v1 là tiêu chí
  cố định cho thiết kế mới. Analytical scope và evidence vẫn không đổi.
- Partial cần hiểu được và tải được artifact; chưa thêm exporter báo cáo partial.
- Không cần API key, quota reset hoặc chi phí dịch vụ để thực hiện batch offline.
