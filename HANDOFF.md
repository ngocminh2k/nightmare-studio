# Nightmare Studio — Session Handoff

**Cập nhật:** 2026-11-11
**Project root:** `F:\truyen_ma\nightmare_studio`

> Agent đọc [`AGENTS.md`](AGENTS.md) trước (services, quy tắc, bẫy đã biết).
> Runbook sản xuất tập mới: [`docs/PRODUCTION-RUNBOOK.md`](docs/PRODUCTION-RUNBOOK.md).

---

## Trạng thái hiện tại

### Tập vừa hoàn thành ✅
`a87b7580-84af-49b8-a658-36e94a851352` — 155 scene, giọng `mrkane` (tiếng Anh, trầm ấm), đã master + sync audio.

| Chỉ số | Giá trị |
|---|---|
| Master | `data/outputs/a87b7580-.../final_master_with_voiceover.mp4` (91 MB, 1094.01s / 18'14") |
| Loudness | mean −21.8 dB, peak −3.0 dB |
| Clips | 155 file `clips/scene-001.mp4` … `scene-155.mp4` |
| DB | `status=final_approved`, `output_path` đã trỏ master |

### Services (phải bật lại sau mỗi lần reboot)
| Service | Port | Khởi động |
|---|---|---|
| flowkit (instance duy nhất) | 8100 (API), 9222 (WS) | `cd F:\truyen_ma\flowkit; python -m agent.main` |
| MCP server studio | 8200 | `.\scripts\start_studio.ps1` |
| VoiceStudio (OmniVoice CUDA) | 3900 | mở app VoiceStudio |

Chrome extension: profile riêng cho từng account tại `F:\truyen_ma\chrome-profiles\account-NN`.

> **Một** flowkit + đổi account **tuần tự**. `app/pool_manager.py` đã bị xoá (code chết).

### Đổi Google Flow account
```powershell
.\scripts\switch-account.ps1 -List        # registry + account đang active
.\scripts\switch-account.ps1 -Account 2   # restart Chromium profile account-NN, tạo project nếu cần
```
Account mới: đăng nhập Google trong cửa sổ Chromium của profile `account-NN`, script tự retry.

---

## Chốt giọng (đây là phần dễ làm sai nhất)

- Profile: **`mrkane`** (`ab36bbf3`), model `omnivoice`, CUDA local.
- `num_step=32`, `guidance_scale=2.0`, `language=en`, `speed=0.88`.
- Warm DSP: highpass 60Hz → +3dB @250Hz → +1dB @1.5kHz → −1dB @4kHz → opto-comp (−18dB, 2:1) → limiter 0.85.
- **Tuyệt đối không fallback pink noise/silence** — `.env` phải giữ `NIGHTMARE_AUDIO_MODE=voice_studio`.

---

## Sửa đổi code cho tập mới (đã bỏ)

Các script production giờ nhận `--episode-id <uuid>` (hoặc env `NIGHTMARE_EPISODE_ID`):

```bash
python scripts/resegment-narration.py            --episode-id <EPISODE_ID>
python scripts/regenerate-mrkane-warm-voiceover.py --episode-id <EPISODE_ID>   # --force để tạo lại hết
python scripts/build-master-voiceover-sync.py    --episode-id <EPISODE_ID>
```

Không còn hằng số `EPISODE_ID` hardcode trong các script này.

---

## Vấn đề đã biết / TODO

1. **`FIRECRAWL_API_KEY` chưa set** — discovery tự động chưa test được. Thêm vào `.env`, hoặc dùng
   `python -m app.cli queue <url>` với URL cụ thể.
2. **Reddit discovery hết story** — `data/studio.db` đã biết hết story top tháng → queue URL thủ công.
3. **Account Google Flow bị throttle** — account 1 còn ~57 credit và từng bị `PUBLIC_ERROR_UNUSUAL_ACTIVITY`
   (hold 3600s trong flowkit). Cần account 2: `.\scripts\switch-account.ps1 -Account 2`.
4. **GPU 1050 Ti 4GB** — đừng chạy app nặng song song khi synth; nếu TTS treo, restart VoiceStudio
   (xoá hàng đợi worker) thay vì retry liên tục.
5. **Quality gate chỉ chạy khi gọi `rate`** — muốn auto-block publish thì gọi `run_quality_gate()`
   trong `app/production.py` sau stage `video`.

---

## Test nhanh

```powershell
Invoke-RestMethod http://127.0.0.1:8100/health
Invoke-RestMethod http://127.0.0.1:3900/health
Invoke-RestMethod http://127.0.0.1:8200/
.\scripts\switch-account.ps1 -List
python -m app.cli status --limit 5
python -m app.cli rate a87b7580-84af-49b8-a658-36e94a851352
```
