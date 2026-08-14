## 📌 Tóm Tắt Thay Đổi (Summary of Changes)
<!-- Tóm tắt ngắn gọn mục đích và nội dung các thay đổi trong PR này -->

## 🔗 Liên Kết Nhiệm Vụ & Tài Liệu (Traceability)
- **Issue / PRD / SRS ID**: Closes # <!-- ví dụ: PRD-03, SRS §4.1 -->
- **Tài liệu kiểm thử TDD**: `docs/testing/` <!-- ví dụ: docs/testing/release-1.tdd.md -->

## 🏷️ Loại Thay Đổi (Type of Change)
- [ ] `feat`: Tính năng mới
- [ ] `fix`: Sửa lỗi
- [ ] `refactor`: Tái cấu trúc code (không đổi hành vi)
- [ ] `test`: Bổ sung / cập nhật bài kiểm thử
- [ ] `docs`: Cập nhật tài liệu
- [ ] `chore`: Cập nhật cấu hình, dependency, CI/CD

---

## 🧪 Quy Trình Kiểm Thử TDD & Bằng Chứng (TDD Evidence)
> **Bắt buộc theo CODING_STANDARDS.md §1 & §7:**
1. Viết test trước và ghi nhận trạng thái **RED**.
2. Triển khai code tối thiểu để chuyển sang **GREEN**.
3. Refactor code trong khi vẫn giữ **GREEN**.

- [ ] Đã hoàn thành chu trình RED -> GREEN.
- [ ] Bằng chứng kiểm thử (logs/kết quả test) đã được ghi lại tại `docs/testing/`.
- [ ] Độ bao phủ kiểm thử (Coverage) đạt **>= 80%** cho các dòng lệnh và nhánh logic.

---

## ✅ Checklist Hoàn Thành (Definition of Done)
- [ ] Code tuân thủ kiến trúc phân lớp (Domain độc lập, Routes không chứa SQL, Repository là lớp duy nhất truy cập DB).
- [ ] Type hints đầy đủ trên tất cả hàm/method công khai (Python 3.12+ / TypeScript strict).
- [ ] Toàn bộ bộ test (Pytest Backend & Vitest/Playwright Frontend) chạy thành công không có lỗi.
- [ ] **Bảo Mật**: Tuyệt đối KHÔNG commit file `.env`, API key, token bí mật hoặc dữ liệu file render `outputs/`.
- [ ] **Accessibility (a11y)**: Kiểm tra khả năng tương tác phím và độ tương phản màu sắc cho UI thay đổi.

---

## 📸 Ảnh chụp màn hình / Bằng chứng thực thi (nếu có)
<!-- Đính kèm ảnh giao diện hoặc kết quả chạy lệnh nếu có thay đổi UI/CLI -->
