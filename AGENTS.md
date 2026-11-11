# AGENTS.md — Nightmare Studio

**Đọc file này trước khi đụng vào repo.** Đây là nguồn sự thật cho agent (Claude Code, Codex, Cursor, agent khác).
Runbook chi tiết sản xuất tập mới: [`docs/PRODUCTION-RUNBOOK.md`](docs/PRODUCTION-RUNBOOK.md).

---

## 1. Dự án làm gì

Pipeline sản xuất tập video kinh dị dạng truyện ngắn (narration + ảnh AI + video AI + voiceover tiếng Anh)
cho kênh YouTube. Mỗi "tập" = 1 episode trong `data/studio.db`, có 155 scene, master ~18 phút.

Stack: Python 3.12 (FastAPI/CLI) · Next.js web dashboard · SQLite (`data/studio.db`) ·
**OmniVoice** (TTS, CUDA local) · **flowkit** (điều khiển Google Flow qua Chrome CDP để render ảnh/video) ·
**9Router** (LLM, viết lời + storyboard).

---

## 2. Services phải bật trước khi chạy

| Service | Port | Khởi động |
|---|---|---|
| flowkit (instance duy nhất) | 8100 API, 9222 WS | `cd F:\truyen_ma\flowkit; python -m agent.main` |
| MCP server (studio) | 8200 | `.\scripts\start_studio.ps1` |
| VoiceStudio / OmniVoice (GPU) | 3900 | mở app VoiceStudio trên máy |
| LLM router 9Router | 20128 | chạy ngoài repo |

```powershell
Invoke-RestMethod http://127.0.0.1:8100/health
Invoke-RestMethod http://127.0.0.1:3900/health
```

**Chrome extension**: mỗi Google account có 1 profile riêng `F:\truyen_ma\chrome-profiles\account-NN`.
Đổi account (khi hết credit / bị throttle):
```powershell
.\scripts\switch-account.ps1 -List
.\scripts\switch-account.ps1 -Account 2
```
> Chỉ dùng **một** flowkit + đổi account **tuần tự**. `app/pool_manager.py` là code chết, đừng dùng.

---

## 3. Sản xuất tập mới — 6 bước

```bash
# 1. Chọn truyện
python -m app.cli queue https://reddit.com/r/nosleep/comments/xxx/...
python -m app.cli find                                   # auto-discover (cần FIRECRAWL_API_KEY)

# 2. Pipeline chính: rewrite → storyboard → ảnh → audio → video → quality gate → package
python -m app.cli produce --approve-all

# 3. Cân lại lời theo slot thời gian từng scene (chạy SAU khi có edit_decision_list.json)
python scripts/resegment-narration.py --episode-id <EPISODE_ID>

# 4. Voice mrkane trầm ấm (TTS 155 scene + warm DSP) — tự gọi bước 5
python scripts/regenerate-mrkane-warm-voiceover.py --episode-id <EPISODE_ID>

# 5. Đồng bộ audio theo EDL → master + 155 clip
python scripts/build-master-voiceover-sync.py --episode-id <EPISODE_ID>

# 6. Chấm điểm + kiểm tra
python -m app.cli rate <EPISODE_ID>
python -m app.cli status --limit 5
```

Output: `data/outputs/<EPISODE_ID>/final_master_with_voiceover.mp4` + `clips/scene-001..155.mp4`.

Mọi script nhận `--episode-id <uuid>` (hoặc env `NIGHTMARE_EPISODE_ID`). **Không sửa code để đổi tập.**

---

## 4. Quy tắc bất di bất dịch

1. **Không bao giờ fallback sang pink noise / silence.** `.env` phải giữ `NIGHTMARE_AUDIO_MODE=voice_studio`.
   Tập trước từng ra master im lặng vì fallback này — đây là lỗi nghiêm trọng nhất của dự án.
2. **Không commit** `.env`, `data/`, `*.db`, `outputs/`, media render (đã khai trong `.gitignore`).
3. **Không commit trực tiếp lên `main`** — tạo branch, mở PR (xem `GIT_WORKFLOW.md`).
4. **Giữ nguyên preset giọng** khi sửa: `mrkane` / `omnivoice` / `num_step=32` / `guidance_scale=2.0` /
   `language=en` / `speed=0.88` + warm DSP chain trong `scripts/regenerate-mrkane-warm-voiceover.py`.
5. **Không chạy song song 2 account** — 1 flowkit, đổi account tuần tự qua `switch-account.ps1`.
6. Quality gate heuristic (blind, không LLM) trong `app/quality_gate.py`, ngưỡng pass **8.0/10**.

---

## 5. Bản đồ file

| File | Vai trò |
|---|---|
| `app/cli.py` | CLI: `produce`, `queue`, `status`, `rate`, `find` |
| `app/production.py` | `EpisodeProductionService` — điều phối stage của 1 episode |
| `app/jobs.py` | Job runner: `rewrite`, `storyboard`, `assets`, `audio`, `video` + EDL + `final_no_voiceover.mp4` |
| `app/media.py` | `GoogleFlowKitMediaProvider` — gọi flowkit REST (8100) |
| `app/audio.py` | VoiceStudio TTS provider + `AudioSettings` (num_step, speed, language…) |
| `app/quality_gate.py` | Chấm điểm blind 5 dimension |
| `app/systemone.py` | Dynamic pacing / framing cho scene |
| `app/nanobanana_prompt_rules.py` | Image prompt builder theo beat (lighting thích ứng) |
| `app/repository.py` | Truy cập SQLite (`data/studio.db`) |
| `app/mcp_server.py` | MCP server (8200) cho agent gọi tool |
| `app/firecrawl_discovery.py` | Tìm truyện r/nosleep qua Firecrawl |
| `scripts/switch-account.ps1` | Đổi Google Flow account (profile + project UUID + hold) |
| `scripts/regenerate-mrkane-warm-voiceover.py` | TTS 155 scene + warm broadcast DSP |
| `scripts/build-master-voiceover-sync.py` | atempo + apad theo EDL → master + clip |
| `scripts/resegment-narration.py` | Chia lại lời theo slot thời gian, cắt ở ranh giới câu/mệnh đề |
| `data/flow-accounts.json` | Registry account + account đang active |

---

## 6. Bẫy đã biết (đừng mất thời gian phát hiện lại)

- **GPU 1050 Ti 4GB**: dài hơn ~26 từ/scene thì request có thể vượt 300s → client timeout, job tích tụ trong hàng đợi
  và làm nghẽn. Script đã set timeout 600s + cooldown 5s. **Không chạy game (kenshi…) song song**, và nếu timeout
  thì restart VoiceStudio để xoá hàng đợi, đừng retry liên tục.
- **Windows + FFmpeg concat**: phải dùng đường dẫn **absolute POSIX** (`path.resolve().as_posix()`) trong file concat,
  nếu không sẽ resolve sai và ghép hỏng.
- **`atempo` chỉ nhận 0.5–2.0**: giữ speed trong `[1.0, 1.35]`, cần giãn scene thì chia nhỏ lời ở bước `resegment`.
- **Throttle Google Flow**: `PUBLIC_ERROR_UNUSUAL_ACTIVITY` → đổi account, không retry liên tục.
- **Reddit discovery hết story**: `data/studio.db` đã biết hết top tháng → dùng `queue <url>` với URL cụ thể.

---

## 7. Kiểm thử

```bash
pytest -q                       # test suite (Python)
python scripts/test_generate_scene.py   # smoke test render 1 scene
python -m app.cli rate <episode_id>     # quality gate
```
TDD bắt buộc theo `CODING_STANDARDS.md` §1 (RED → GREEN → REFACTOR), coverage ≥ 80%,
bằng chứng lưu vào `docs/testing/`.
