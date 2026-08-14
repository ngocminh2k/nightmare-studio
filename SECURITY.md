# Chính Sách Bảo Mật (Security Policy)

Dự án **Nightmare Studio** coi trọng vấn đề an toàn thông tin và bảo mật dữ liệu.

---

## 1. Các Phiên Bản Được Hỗ Trợ (Supported Versions)

Hiện tại, các bản vá bảo mật được ưu tiên hỗ trợ trên các phiên bản sau:

| Phiên bản | Được hỗ trợ |
| :--- | :--- |
| `1.x.x` (main) | :white_check_mark: |
| `< 1.0.0` | :x: |

---

## 2. Báo Cáo Lỗ Hổng Bảo Mật (Reporting a Vulnerability)

Nếu bạn phát hiện bất kỳ lỗ hổng bảo mật, nguy cơ rò rỉ dữ liệu hoặc vấn đề an toàn nào trong Nightmare Studio:

1. **Tuyệt đối KHÔNG** mở Issue công khai trên GitHub để thông báo về lỗ hổng bảo mật.
2. Vui lòng gửi email trực tiếp tới người quản trị:
   - **Email**: `minhngoc2k@gmail.com` (hoặc mở [GitHub Security Advisory](https://github.com/ngocminh2k/nightmare-studio/security/advisories/new) ở chế độ riêng tư).
3. **Nội dung email/advisory cần bao gồm**:
   - Tiêu đề: `[Vulnerability Report] - <Tóm tắt ngắn>`
   - Mô tả chi tiết về lỗ hổng và mức độ ảnh hưởng (Severity).
   - Các bước cụ thể (Proof of Concept - PoC) để tái hiện lỗi.
   - Các giải pháp hoặc bản vá đề xuất (nếu có).

---

## 3. Quy Trình Phản Hồi & Xử Lý

- **Xác nhận**: Đội ngũ sẽ phản hồi xác nhận đã nhận được báo cáo trong vòng **48 giờ**.
- **Đánh giá & Khắc phục**: Lỗ hổng sẽ được phân tích, đánh giá tác động và tạo bản vá (Hotfix) trong môi trường riêng tư.
- **Công bố**: Sau khi bản vá được phát hành thành công, thông tin về lỗ hổng và người đóng góp sẽ được ghi nhận minh bạch theo thỏa thuận.

---

## 4. Nguyên Tắc Bảo Mật Cho Người Phát Triển

- Tuyệt đối không lưu trữ khóa API (Gemini, Veo, YouTube, Reddit, OpenAI, v.v.) trong mã nguồn.
- Tất cả API keys và biến môi trường phải được cấu hình qua `.env` và không bao giờ được commit lên Git.
- Mọi đầu vào từ người dùng hoặc nguồn bên ngoài phải được validate qua schema Pydantic/TypeScript trước khi xử lý.
