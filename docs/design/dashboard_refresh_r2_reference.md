# Dashboard Refresh R2 — Native Reference & Visual Structure Packet

Ngày lập: 26/09/2026.
Tài liệu liên quan:
- [RELEASE_REPAIR_SMALL_MODEL_PLAN.md](../RELEASE_REPAIR_SMALL_MODEL_PLAN.md) (§C04, §C05, §C06)
- [DASHBOARD_PRESENTATION_AMENDMENT.md](../DASHBOARD_PRESENTATION_AMENDMENT.md)
- [dashboard_refresh_layout.json](dashboard_refresh_layout.json) (R1 layout baseline)

---

## 1. Mục tiêu và phạm vi Task C04

Task C04 thiết lập gói tài liệu tham chiếu cấu trúc kỹ thuật (reference packet) chuẩn xác theo đặc tả Microsoft Fabric PBIR (Power BI Report definition) nhằm khắc phục các khiếm khuyết hiển thị đã ghi nhận ở bản R1 trước khi cập nhật mã nguồn generator trong `src/bi_analyst/bi.py`.

### Danh mục khiếm khuyết R1 cần sửa:
1. **Thẻ chỉ số (K03, K04)**:
   - K03 (Revenue Change): Cần định dạng hiển thị có dấu `+` (ví dụ: `+60,000`).
   - K04 (Growth %): Cần 2 chữ số thập phân và dấu `+` rõ ràng (ví dụ: `+6.36%` hoặc `+6,36%`), loại bỏ hiển thị làm tròn 1 số lẻ `6.4%`.
2. **Biểu đồ thanh phân rã (C01, C02)**:
   - Phân biệt màu trực quan theo dấu giá trị: Tăng trưởng dương dùng màu xanh `#087F72`, suy giảm âm dùng màu đỏ/gạch `#B54734`.
   - Nhãn dữ liệu (data labels) trên cột/thanh có dấu `+` cho giá trị dương và giữ nguyên đơn vị hiển thị rõ ràng.
3. **Biểu đồ theo tháng (C03)**:
   - Rút gọn tiêu đề tránh bị cắt ba chấm (ellipsis): `"Doanh thu quan sát theo tháng"`.
   - Chuyển lưu ý caveat ("2 điểm quan sát, chưa kết luận xu hướng") sang hộp văn bản T02 sẵn có.
4. **Bảng Trang 2 (E01, S01)**:
   - Kích hoạt thuộc tính `wordWrap` cho cả `columnHeaders` và `values` để nội dung Finding và ScopeLabel tự động xuống dòng, không làm tràn cột Status ra ngoài màn hình.
   - Bảng thông tin phân tích (S01): Lọc ẩn các thuộc tính kỹ thuật thô (`Dataset hash`, `Validated analysis fingerprint`, `Root analysis scope JSON`), chỉ làm nổi bật các trường thông tin nghiệp vụ người dùng quan tâm.
5. **Cô lập tương tác (Interaction Isolation)**:
   - Khai báo danh sách `visualInteractions` trong `page.json` của trang Tổng quan với kiểu `"NoFilter"` từ các biểu đồ chi tiết (C01, C02, C03) đến các thẻ KPI (K01-K04) và văn bản nhận xét (T02).

---

## 2. Cấu trúc JSON PBIR chuẩn hóa

### 2.1. Cấu hình cô lập tương tác (`visualInteractions` trên `page.json`)
Theo schema `https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json`, thuộc tính `visualInteractions` được đặt trực tiếp trong tệp `page.json` của từng trang:

```json
{
  "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.0.0/schema.json",
  "name": "35829699879dfc38c755",
  "displayName": "Tổng quan doanh thu",
  "displayOption": "FitToPage",
  "width": 1280,
  "height": 800,
  "visualInteractions": [
    {
      "source": "a3e0dbb33acd23f01768",
      "target": "bb3a576deb7775a78c6b",
      "type": "NoFilter"
    },
    {
      "source": "a3e0dbb33acd23f01768",
      "target": "5e999cf7f62c05fbca18",
      "type": "NoFilter"
    },
    {
      "source": "a3e0dbb33acd23f01768",
      "target": "cd44dcbf57858845e8be",
      "type": "NoFilter"
    },
    {
      "source": "a3e0dbb33acd23f01768",
      "target": "2d992aae536e27a7d63e",
      "type": "NoFilter"
    },
    {
      "source": "a3e0dbb33acd23f01768",
      "target": "6fcea0e5f701a94ad535",
      "type": "NoFilter"
    }
  ]
}
```

### 2.2. Định dạng Tự động ngắt dòng bảng (`wordWrap` trên `tableEx`)
Áp dụng cho `objects` của `tableEx` (`E01` và `S01`):

```json
{
  "objects": {
    "columnHeaders": [
      {
        "properties": {
          "wordWrap": {
            "expr": {
              "Literal": {
                "Value": "true"
              }
            }
          }
        }
      }
    ],
    "values": [
      {
        "properties": {
          "wordWrap": {
            "expr": {
              "Literal": {
                "Value": "true"
              }
            }
          }
        }
      }
    ]
  }
}
```

### 2.3. Định dạng Thẻ chỉ số (`cardVisual`)
- Áp dụng `customFormatString` với pattern `"+0.00%;-0.00%;0.00%"` cho Growth KPI và `"+#,0;-#,0;#,0"` cho Change KPI.
- Gắn nhãn đơn vị rõ ràng và khóa kích thước phông hiển thị để không phụ thuộc vào locale máy trạm.

### 2.4. Quy tắc phân biệt màu sắc thanh (`barChart`)
- Giữ nguyên màu chủ đạo Teal `#087F72` cho các hạng mục tăng trưởng dương.
- Áp dụng cấu hình phân biệt màu hoặc nhãn dữ liệu có dấu `+` (`valueCustomFormatString`) để người dùng nhận diện ngay chiều hướng tác động của từng chiều danh mục (Region/Product).
