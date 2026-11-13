# Production Runbook — Sản xuất tập mới

Tài liệu này là quy trình vận hành đã chạy thật cho tập `a87b7580-84af-49b8-a658-36e94a851352`
(155 scene, 18 phút 14 giây, giọng `mrkane`). Mọi lệnh dưới đây đã được verify.

> Agent đọc [`../AGENTS.md`](../AGENTS.md) trước. Nguyên tắc: **đổi tập = đổi `--episode-id`, không sửa code.**

---

## 0. Yêu cầu trước khi bắt đầu

| Service | Port | Kiểm tra |
|---|---|---|
| flowkit (1 instance duy nhất) | 8100 / 9222 | `Invoke-RestMethod http://127.0.0.1:8100/health` |
| VoiceStudio (OmniVoice, CUDA) | 3900 | `Invoke-RestMethod http://127.0.0.1:3900/health` |
| LLM router 9Router | 20128 | `Invoke-RestMethod http://127.0.0.1:20128/v1/models` |
| Chrome extension | WS 9222 | `.\scripts\switch-account.ps1 -List` |

```powershell
cd F:\truyen_ma\nightmare_studio
# Nếu flowkit chưa chạy (mở 1 terminal riêng, giữ terminal này):
cd F:\truyen_ma\flowkit; python -m agent.main
```

**Không chạy game/ứng dụng nặng song song** — GTX 1050 Ti chỉ 4GB VRAM, OmniVoice sẽ bị đẩy sang RAM hệ thống
và mỗi scene sẽ mất 2–3 phút thay vì 30 giây.

---

## 1. Chọn truyện

```bash
# URL cụ thể (khuyến nghị — discovery tự động đã cạn story top tháng)
python -m app.cli queue https://reddit.com/r/nosleep/comments/xxxxxx/xxxxxx/

# Tìm truyện mới (cần FIRECRAWL_API_KEY trong .env)
python -m app.cli find
```

Lệnh `queue` scrape truyện, lưu episode stub vào `data/studio.db` và trả về `episode_id`.

---

## 2. Chạy pipeline chính

```bash
python -m app.cli produce --approve-all
```

Chuỗi stage trong `app/production.py::resume`:

| # | Stage | Job | Sinh ra |
|---|---|---|---|
| 1 | `rewrite` | `app/jobs.py` | Kịch bản tiếng Anh (voice Victor Kane) |
| 2 | `storyboard` | `app/jobs.py` | 155 scene: prompt ảnh, narration, shot, target duration |
| 3 | `assets` | `app/jobs.py` | Ảnh tĩnh mỗi scene qua flowkit (Nano Banana 2 + reference) |
| 4 | `audio` | `app/jobs.py` | `audio/scene-XXX.mp3` (giọng mrkane, chưa warm) |
| 5 | `video` | `app/jobs.py` | `clips/scene-XXX.mp4` (Omni 1.1 Flash 360p 6s) + `edit_decision_list.json` + `final_no_voiceover.mp4` |
| 6 | quality gate | `app/quality_gate.py` | Điểm 5 dimension, ngưỡng pass 8.0/10 |
| 7 | export | `app/production.py` | Manifest, storyboard HTML, CSV, EDL |

Episode bị gián đoạn (hết credit, mất mạng) → chạy lại đúng lệnh trên, pipeline **resume** từ stage chưa xong:

```bash
python -m app.cli produce --episode-id <EPISODE_ID> --approve-all
```

---

## 3. Cân lại lời theo slot thời gian

Storyboard chia lời theo **số từ**, nên nhiều scene bị cắt giữa câu. Script này chia lại đúng số từ, đúng số scene,
cắt ở ranh giới câu/mệnh đề, và kiểm tra bảo toàn từ vựng trước khi ghi DB:

```bash
python scripts/resegment-narration.py --episode-id <EPISODE_ID>          # xem số liệu + ghi DB
python scripts/resegment-narration.py --episode-id <EPISODE_ID> --dry-run  # chỉ xem, không ghi
```

Kết quả tập `a87b7580`: 2.419 từ / 155 scene, 51% kết bằng câu, 49% kết bằng mệnh đề, 0 scene rỗng,
chỉ 1 scene vượt 1.35× slot. Idempotent — chạy lần hai không đổi gì.

---

## 4. Voice `mrkane` — trầm ấm, không generic

```bash
python scripts/regenerate-mrkane-warm-voiceover.py --episode-id <EPISODE_ID>
# thêm --force nếu muốn tạo lại toàn bộ (không resume)
```

Preset (đã chốt trong `.env` + script):

| Tham số | Giá trị | Ý nghĩa |
|---|---|---|
| voice | `mrkane` (`ab36bbf3`) | Profile Voice-Design của bạn trong VoiceStudio |
| model | `omnivoice` | Engine TTS local (CUDA) |
| `num_step` | 32 | Preset chất lượng diffusion |
| `guidance_scale` | 2.0 | Bám instruct chặt |
| `language` | `en` | Bật text normalization + phoneme tiếng Anh |
| `speed` | 0.88 | Slow-burn, chậm có chủ đích |

Warm broadcast DSP (FFmpeg, áp sau mỗi scene):

```
highpass=f=60
equalizer=f=250:t=q:w=1:g=3        # thân giọng, ấm
equalizer=f=1500:t=q:w=1:g=1       # độ rõ của âm tiết
equalizer=f=4000:t=q:w=1:g=-1      # giảm chói
acompressor=threshold=-18dB:ratio=2:attack=10:release=150:makeup=1.5
alimiter=limit=0.85:attack=5:release=50
```

**Resume**: script ghi marker `audio/.batch_start`. File mp3 có mtime ≥ marker là của batch hiện tại → bỏ qua;
file cũ hơn → tạo lại. Xoá marker (hoặc dùng `--force`) để bắt đầu batch mới từ đầu.

**Sau khi synth xong, script tự gọi bước 5.**

> Cần VoiceStudio chạy. Mỗi request timeout 600s, cooldown 5s giữa các request.
> Nếu request treo → restart VoiceStudio (xoá hàng đợi worker tích tụ), đừng spam retry.

---

## 5. Đồng bộ audio–video theo EDL → master

```bash
python scripts/build-master-voiceover-sync.py --episode-id <EPISODE_ID>
```

Cơ chế (chống drift trên 155 điểm cắt):

1. Với mỗi scene: nếu lời dài hơn slot hình → `atempo` (giới hạn `[1.0, 1.35]`), sau đó `apad=whole_dur=<slot>`
   để khớp **đúng** thời lượng cảnh.
2. Concat 155 đoạn WAV đã pad → một track liên tục.
3. Mux với `final_no_voiceover.mp4` (copy video, AAC 192k/48kHz) → `final_master_with_voiceover.mp4`.
4. Cắt lại 155 clip riêng từ master, đồng bộ clip path + `audio_duration_seconds` vào `data/studio.db`.
5. `validate_generated_video()` kiểm tra file đầu ra.

> Windows: file concat của FFmpeg phải dùng **đường dẫn absolute POSIX** (`resolve().as_posix()`) — script đã xử lý.

---

## 6. Kiểm tra & ngưỡng chất lượng

```bash
python -m app.cli rate <EPISODE_ID>      # quality gate blind, pass ≥ 8.0/10
python -m app.cli status --limit 5
ffprobe -v error -show_entries format=duration -of csv=p=0 \
  "data/outputs/<EPISODE_ID>/final_master_with_voiceover.mp4"
```

Ngưỡng tham chiếu của tập `a87b7580`:

| Chỉ số | Giá trị |
|---|---|
| Thời lượng master | 1094.01s (18 phút 14 giây) |
| Audio mean volume | −21.8 dB |
| Audio max peak | −3.0 dB |
| Số clip | 155 (`clips/scene-001.mp4` … `scene-155.mp4`) |
| Dung lượng | ~91 MB |

---

## 7. Lỗi thường gặp

| Triệu chứu | Nguyên nhân | Xử lý |
|---|---|---|
| Master ra im lặng | `NIGHTMARE_AUDIO_MODE` không phải `voice_studio` → fallback pink noise | Đặt lại `NIGHTMARE_AUDIO_MODE=voice_studio`, chạy lại bước 4–5 |
| Request TTS treo / timeout | GPU bị tranh chấp (app nặng khác) | Tắt app nặng; restart VoiceStudio; timeout đã là 600s |
| Lời bị cắt giữa câu | Chưa chạy bước 3 | Chạy `resegment-narration.py` **trước** khi synth voice |
| TTS lỗi chính tả tiếng Anh | Thiếu `language=en` | Kiểm tra `.env`: `NIGHTMARE_AUDIO_LANGUAGE=en` |
| FFmpeg concat fail trên Windows | Đường dẫn tương đối trong file concat | Script đã dùng `resolve().as_posix()` — đừng sửa lại thành `name` |
| `PUBLIC_ERROR_UNUSUAL_ACTIVITY` | Google Flow throttle account | `.\scripts\switch-account.ps1 -Account 2` |
| Quality gate < 8.0 | Scene yếu (prompt ngắn, thiếu beat, pacing lệch) | Xem `data/quality_patches.jsonl`, re-render scene vi phạm, chạy lại `rate` |

---

## 8. Phụ lục: bảng lệnh nhanh

```powershell
# Bật services
cd F:\truyen_ma\flowkit; python -m agent.main      # terminal riêng
cd F:\truyen_ma\nightmare_studio; .\scripts\start_studio.ps1

# Đổi account
.\scripts\switch-account.ps1 -List
.\scripts\switch-account.ps1 -Account 2

# Pipeline
$EP = "<EPISODE_ID>"
python -m app.cli produce --episode-id $EP --approve-all
python scripts/resegment-narration.py --episode-id $EP
python scripts/regenerate-mrkane-warm-voiceover.py --episode-id $EP
python scripts/build-master-voiceover-sync.py --episode-id $EP
python -m app.cli rate $EP
```

Mọi script nhận `--episode-id <uuid>`; nếu không truyền, script dùng env `NIGHTMARE_EPISODE_ID`.
