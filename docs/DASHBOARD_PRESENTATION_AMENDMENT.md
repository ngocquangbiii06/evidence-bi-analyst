# Dashboard Presentation Amendment

Ngày ban hành: 25/09/2026.
Tài liệu gốc liên quan:
- Master Contract: [FLAGSHIP_EXECUTION_PLAN.md](FLAGSHIP_EXECUTION_PLAN.md)
- Kế hoạch làm mới Dashboard: [DASHBOARD_REFRESH_LUNA_PLAN.md](DASHBOARD_REFRESH_LUNA_PLAN.md)
- Kế hoạch sửa lỗi release: [RELEASE_REPAIR_SMALL_MODEL_PLAN.md](RELEASE_REPAIR_SMALL_MODEL_PLAN.md)

Tài liệu này lưu trữ phần phụ lục presentation amendment được tách từ master plan để bảo toàn mã băm đóng băng (frozen sha256) của [FLAGSHIP_EXECUTION_PLAN.md](FLAGSHIP_EXECUTION_PLAN.md) (`d176b0172ee8465155fd4eb2a4c5d96c8e5e72340704f3aa2200577871b89a67`).

---

## Post-v1 — Yêu cầu chỉnh dashboard (25/09/2026)

Người dùng yêu cầu mẫu dashboard rõ/đẹp hơn và plan giao Luna 5.6 sửa các lỗi
trải nghiệm. Thiết kế và task cards mới ở `DASHBOARD_REFRESH_LUNA_PLAN.md`.
Đây là presentation amendment riêng sau release v1; analytical scope, validators,
coverage/null semantics và DAX formulas vẫn giữ nguyên. Mẫu HTML chưa phải PBIR
đã build hoặc native rendering pass. Lượt lập plan không tự execute application.

Revision mới dự kiến 2 pages, 9 data visuals + 4 text objects cho demo hai
dimensions; giữ nguyên Candidate/Current đã xác minh và xuất Refresh_R1 riêng.
Cột `Evidence.ScopeLabel` chỉ để hiển thị scope đã validate là bổ sung model
duy nhất được plan cho phép; không đổi authoritative artifact hoặc DAX formulas.
Mọi sửa generator cần static checks, native Desktop verification và review mới.
Build/fix dùng `gpt-5.6-luna/max`, review `gpt-6-astra/high` theo routing hiện hành.
