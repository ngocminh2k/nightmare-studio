# Hướng Dẫn Đóng Góp & Phát Triển (Nightmare Studio Contributing Guide)

Cảm ơn bạn đã tham gia đóng góp cho dự án **Nightmare Studio**! Vui lòng đọc kỹ hướng dẫn này để đảm bảo mã nguồn và quy trình làm việc luôn tuân thủ các quy chuẩn kỹ thuật của dự án.

---

## 1. Chuẩn Bị Môi Trường Phát Triển (Prerequisites)

- **Python**: Phiên bản 3.12 trở lên.
- **Node.js**: Phiên bản 20.x trở lên (`npm` v10+).
- **FFmpeg**: Cài đặt sẵn trên hệ điều hành và thêm vào `PATH`.
- **Git**: Đã cấu hình `user.name` và `user.email`.

### 1.1. Thiết lập Backend (Python)
```bash
# Tạo môi trường ảo
python -m venv .venv

# Kích hoạt môi trường (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Cài đặt dependencies (bao gồm dev tools)
pip install -e ".[dev]"
```

### 1.2. Thiết lập Frontend (Next.js)
```bash
cd web
npm install
cd ..
```

---

## 2. Quy Trình Phát Triển Chuẩn (Development Workflow)

Dự án áp dụng quy định nghiêm ngặt từ [`CODING_STANDARDS.md`](CODING_STANDARDS.md) và [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md).

### Bước 1: Tạo Nhánh Làm Việc (Branching)
Luôn tạo nhánh mới từ `main` mới nhất:
```bash
git checkout main
git pull origin main
git checkout -b feature/prd-03-storyboard-editor
```

### Bước 2: Chu Trình TDD (Test-Driven Development)
1. **Viết test trước (RED)**:
   - Viết test cho tính năng mới trong thư mục `tests/` (Backend) hoặc `web/src/lib/` (Frontend).
   - Chạy test và xác nhận test thất bại:
     ```bash
     pytest tests/test_new_feature.py
     ```
2. **Cài đặt logic tối thiểu (GREEN)**:
   - Viết code để bài test vượt qua.
3. **Refactor & Kiểm tra độ bao phủ (Coverage)**:
   - Tối ưu hóa code.
   - Chạy toàn bộ test suite và kiểm tra coverage (yêu cầu **>= 80%**):
     ```bash
     pytest --cov=app --cov-report=term-missing
     ```
4. **Ghi lại bằng chứng**:
   - Ghi lại kết quả test RED/GREEN vào thư mục `docs/testing/`.

### Bước 3: Kiểm Tra Cục Bộ Trước Khi Commit (Pre-commit Checks)
Trước khi commit, hãy đảm bảo tất cả các lệnh sau vượt qua mà không có lỗi:

```bash
# 1. Backend tests & coverage
pytest --cov=app

# 2. Frontend tests
npm --prefix web run test

# 3. Frontend linting & type check
npm --prefix web run lint
npx --prefix web tsc --noEmit
```

### Bước 4: Commit Theo Chuẩn Conventional Commits
```bash
git add .
git commit -m "feat(storyboard): add ordered batch scene image upload support"
```

### Bước 5: Đẩy Nhánh và Mở Pull Request
```bash
git push -u origin feature/prd-03-storyboard-editor
```
- Mở PR trên GitHub tới nhánh `main`.
- Điền đầy đủ các mục trong mẫu Pull Request Checklist.

---

## 3. Tiêu Chuẩn Viết Code (Coding Conventions)

- **Kiến trúc phân lớp**:
  - `Domain`: Độc lập, không import FastAPI, SQLite, hoặc filesystem.
  - `Routes/API`: Chỉ làm nhiệm vụ validate request và mapping error.
  - `Repository`: Lớp duy nhất tương tác trực tiếp với cơ sở dữ liệu.
- **Bảo Mật**:
  - Tuyệt đối không commit file `.env` hoặc hardcode API keys / tokens.
  - Không commit các file database `.db` và dữ liệu media trong `outputs/`.
