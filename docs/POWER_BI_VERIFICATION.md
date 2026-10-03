# Kiểm chứng Power BI

Ngày kiểm chứng: 21/09/2026. Artifact hiện hành đã được Full Refresh và kiểm chứng trên Power BI Desktop `2.157.1354.0 (26.08)` ở Windows. Metadata/model load, 5 DAX measures, reconciliation 7/7 cases và rendering 2 pages/9 visuals đều pass. Bằng chứng engine nằm trong `../deliverables/verification/powerbi_engine.json`; ảnh từng page nằm trong `../deliverables/verification/powerbi_rendering/`.

## Artifact cần mở

`deliverables/PowerBI_Demo_Current/EvidenceBI.pbip` — 8 dòng synthetic, Revenue VND scale 0. Model fingerprint trong `export_manifest.json` phải đi cùng báo cáo kiểm chứng. Bản `PowerBI_Demo` cũ được giữ để đối chiếu, không phải bản hiện tại.

Mở trong Power BI Desktop trên Windows và Refresh. Có hai trang: Business performance và Evidence & scope. Nếu Desktop yêu cầu tính năng PBIP/PBIR hoặc báo lỗi schema, ghi rõ thông báo/version rồi sửa generator; không sửa riêng con số trong report.

## Những context phải đối soát

Đáp án độc lập nằm tại `examples/powerbi_expected.json`:

| Context | Base | Previous | Current | Change | Growth ratio |
|---|---:|---:|---:|---:|---:|
| Toàn bộ | 1600 | 1000 | 600 | -400 | -0.4 |
| Region North | 450 | 300 | 150 | -150 | -0.5 |
| Product A | 650 | 400 | 250 | -150 | -0.375 |
| North + A | 150 | 100 | 50 | -50 | -0.5 |
| Date January | 1000 | 1000 | 600 | -400 | -0.4 |
| Date April, không có rows | BLANK | 1000 | 600 | -400 | -0.4 |
| Region không tồn tại | BLANK | 0 | 0 | 0 | BLANK |

Previous/Current dùng hai kỳ đã khai báo nên chủ đích bỏ filter DimDate; base measure theo filter ngày. Filters trên dimension vẫn áp dụng. Growth trả ratio, được format thành phần trăm trên UI. Tolerance fixture nguyên VND = 0; growth = 1e-12.

Null case riêng dùng `examples/null_sales.csv`, `null_business_config.json` và `powerbi_null_expected.json`. Ví dụ North không có row tháng 2 là 0 do coverage xác nhận; South có rows nhưng metric toàn null là BLANK. Phải thực thi fixture này, không chỉ đọc công thức IF/COALESCE.

## Script đối soát chỉ đọc

`scripts/verify_powerbi.ps1` chuẩn bị để chạy trong Windows bằng account đang chạy Desktop. Nó kết nối engine tại localhost, tìm model Evidence BI, so sánh metadata/measure/M với bản xuất, rồi chạy các DAX query từ fixture. Không ghi/refresh/xóa database.

```powershell
powershell -NoProfile -File .\scripts\verify_powerbi.ps1 -Project .\deliverables\PowerBI_Demo_Current -Port ACTUAL_PORT -Cases .\examples\powerbi_expected.json -Output .\deliverables\verification\powerbi_engine.json
```

Thay `ACTUAL_PORT` bằng cổng engine của đúng cửa sổ Desktop đã mở project. Không dùng một cổng từ phiên cũ. Cổng có trong `msmdsrv.port.txt` dưới AnalysisServicesWorkspaces tương ứng. Nếu chưa kết nối được, giữ `execution=not_checked` và ghi blocker; không dùng credentials khác để vượt chặn.

Script đã chạy thành công trên đúng engine của artifact hiện hành. Nó đối chiếu model fingerprint, model file hash, fixture hash và 7 DAX contexts; kết quả được ghi trong `../deliverables/verification/powerbi_engine.json`. Báo cáo output không tự thay `export_manifest.json`; trạng thái rendering chỉ được nâng lên `passed` sau khi ảnh từ Desktop thật được kiểm tra riêng.

## Kiểm tra hình ảnh và tương tác

- Không có error visuals; số KPI và định dạng âm/% đúng.
- Chọn North, Product A và tổ hợp; kiểm tra cross-filtering.
- Trục thời gian sắp xếp đúng MonthKey; tiêu đề/nhãn không bị cắt.
- Trang Evidence cho truy vết IDs và scope; nhãn thiếu dữ liệu không được hiểu nhầm là 0.
- Lưu ảnh/walkthrough của dữ liệu giả lập, ghi version Desktop và ngày kiểm tra.

Kiểm chứng metadata, DAX và rendering là ba bằng chứng riêng. Ảnh Desktop xác nhận trang **Business performance** có 4 KPI cards, 2 bar charts, 1 line chart và bảng scope; trang **Evidence & scope** có evidence table. Tổng cộng 2 pages và 9 visuals, không có error placeholder. Null-case engine/reconciliation cũng pass, nhưng rendering của artifact null-case vẫn `not_checked` vì không thuộc dashboard hiện hành.
