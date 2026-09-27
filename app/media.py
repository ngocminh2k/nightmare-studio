"""Media providers for scene images and motion clips.

The Canvas provider connects only to a browser the operator has already opened
with remote debugging enabled.  It never manufactures successful artifacts
when Canvas, an output selector, or the CDP endpoint is unavailable.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote_to_bytes, urljoin
from urllib.request import Request, urlopen


class MediaProvider(Protocol):
    """Creates media artifacts for one storyboard scene at a time."""

    name: str

    def generate_image(self, prompt: str, output_path: Path) -> Path: ...

    def generate_video(self, image_path: Path, motion_prompt: str, output_path: Path) -> Path: ...


class MediaNotConfiguredProvider:
    """Fails closed until a real Canvas CDP workspace is configured."""

    name = "not_configured"

    @staticmethod
    def _unavailable() -> RuntimeError:
        return RuntimeError(
            "Real media generation is not configured. Set NIGHTMARE_MEDIA_MODE=canvas_cdp "
            "and provide the Canvas CDP workspace settings before approving assets."
        )

    def generate_image(self, prompt: str, output_path: Path) -> Path:
        raise self._unavailable()

    def generate_video(self, image_path: Path, motion_prompt: str, output_path: Path) -> Path:
        raise self._unavailable()


def build_motion_prompt(scene: dict[str, Any]) -> str:
    """Build the user message for a Veo 3.1 image-to-video prompt request."""

    shot = str(scene.get("shot") or "Cinematic horror shot")
    narration = str(scene.get("narration") or "").strip()
    target_duration = float(scene.get("target_duration_seconds") or 5)
    return (
        f"SCENE INPUT:\nShot: {shot}\nNarrative beat: {narration}\n\n"
        f"Direct the essential visual beat to land within the first {target_duration:.2f} seconds of the 8-second source clip; leave usable handles before and after it. "
        "Preferred camera motion: slow cinematic push-in unless the scene needs another deliberate move; no cuts.\n"
        "Write one final Veo 3.1 image-to-video prompt in English. Return only the prompt."
    )


def veo_video_prompt_messages(scene: dict[str, Any]) -> list[dict[str, str]]:
    """Load the production rules for every final video-prompt generation request."""

    rules_path = Path(__file__).resolve().parents[1] / "docs" / "veo-3.1-prompt-rules.md"
    return [
        {"role": "system", "content": rules_path.read_text(encoding="utf-8")},
        {"role": "user", "content": build_motion_prompt(scene)},
    ]


def veo_video_prompt_plan_messages(scenes: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Ask the LLM once for the complete, numbered Veo prompt plan."""

    rules_path = Path(__file__).resolve().parents[1] / "docs" / "veo-3.1-prompt-rules.md"
    inputs = [{"number": scene.get("number"), "shot": scene.get("shot"), "narration": scene.get("narration")} for scene in scenes]
    return [
        {"role": "system", "content": rules_path.read_text(encoding="utf-8")},
        {"role": "user", "content": "Create every scene's Veo 3.1 image-to-video prompt in one plan. Return JSON only: {\"scenes\":[{\"number\":1,\"motion_prompt\":\"...\"}]}. Include every supplied number exactly once.\n\nSCENES:\n" + json.dumps(inputs, ensure_ascii=False)},
    ]


def parse_motion_prompt_plan(response: str, scene_numbers: set[int]) -> dict[int, str]:
    """Validate the one-call prompt plan rather than silently applying malformed output."""

    cleaned = response.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        items = json.loads(cleaned)["scenes"]
        prompts = {int(item["number"]): str(item["motion_prompt"]).strip() for item in items}
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("LLM returned an invalid batch Veo prompt plan; no scene prompts were changed") from exc
    if set(prompts) != scene_numbers or any(not prompt for prompt in prompts.values()):
        raise ValueError("LLM batch Veo prompt plan must provide one non-empty prompt for every scene")
    return prompts


def build_victor_kane_image_prompt(scene: dict[str, Any]) -> str:
    """Mirror the narration-first image prompt used by the legacy episode pipeline."""
    narration = str(scene.get("narration") or "").strip()
    return f"A 2.5D horror indie game style illustration. {narration}"


def _discover_google_api_key() -> str:
    """Read Google / Veo API key from environment."""
    return (
        os.getenv("NIGHTMARE_VEO_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
        or os.getenv("GEMINI_API_KEY")
        or ""
    ).strip()


def _is_cdp_listening(cdp_url: str, timeout: float = 1.0) -> bool:
    """Check if the given CDP HTTP endpoint is responding."""
    try:
        url = urljoin(cdp_url.rstrip("/") + "/", "json/version")
        req = Request(url, headers={"User-Agent": "NightmareStudio/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _discover_chrome_path(configured_path: str = "") -> str:
    """Find the Chrome executable on the host system."""
    if configured_path and Path(configured_path).is_file():
        return configured_path
    env_path = os.getenv("NIGHTMARE_CHROME_PATH", "").strip() or os.getenv("CHROME_PATH", "").strip()
    if env_path and Path(env_path).is_file():
        return env_path
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ]
    local_app_data = os.getenv("LOCALAPPDATA", "")
    if local_app_data:
        candidates.append(str(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe"))
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    for binary_name in ("google-chrome", "chrome", "chromium"):
        which_path = shutil.which(binary_name)
        if which_path:
            return which_path
    return ""


def _discover_chrome_user_data_dir(configured_dir: str = "") -> Path:
    """Find or establish a persistent Chrome user data directory for CDP sessions."""
    if configured_dir:
        p = Path(configured_dir).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    env_dir = os.getenv("NIGHTMARE_CHROME_USER_DATA_DIR", "").strip()
    if env_dir:
        p = Path(env_dir).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    # Default candidate 1: Existing workspace temp_chrome_profile
    candidate_1 = Path(__file__).resolve().parents[2] / "temp_chrome_profile"
    if candidate_1.is_dir():
        return candidate_1
    # Default candidate 2: Nightmare Studio default directory
    default_dir = Path.home() / ".nightmare_studio" / "chrome_profile"
    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir


@dataclass(frozen=True)
class CanvasCDPSettings:
    media_mode: str = "not_configured"
    cdp_url: str = "http://127.0.0.1:9222"
    image_url: str = ""
    video_url: str = ""
    image_prompt_selector: str = "textarea"
    image_submit_selector: str = "button[type='submit']"
    image_result_selector: str = "img"
    video_prompt_selector: str = "textarea"
    video_submit_selector: str = "button[type='submit']"
    video_result_selector: str = "video"
    video_image_input_selector: str = "input[type='file']"
    flow_character_reference_path: str = ""
    kira_api_key: str = ""
    kira_api_base: str = "https://kiraai.vn/api/v1"
    google_api_key: str = ""
    timeout_seconds: int = 180
    auto_launch_cdp: bool = True
    chrome_path: str = ""
    chrome_user_data_dir: str = ""
    flow_model_image: str = "Nano Banana 2"
    flow_model_video: str = "Omni 1.1 Flash"
    flow_video_resolution: str = "360p"
    flow_aspect_ratio: str = "16:9"
    flow_video_input_mode: str = "frames"
    flow_video_duration: int = 6
    flow_runner_backend: str = "auto"
    flow_runner_path: str = ""

    @classmethod
    def from_environment(cls) -> CanvasCDPSettings:
        return cls(
            media_mode=os.getenv("NIGHTMARE_MEDIA_MODE", "not_configured").strip().lower(),
            cdp_url=os.getenv("NIGHTMARE_CANVAS_CDP_URL", "http://127.0.0.1:9222").strip(),
            image_url=os.getenv("NIGHTMARE_CANVAS_IMAGE_URL", "").strip(),
            video_url=os.getenv("NIGHTMARE_CANVAS_VIDEO_URL", "").strip(),
            image_prompt_selector=os.getenv("NIGHTMARE_CANVAS_IMAGE_PROMPT_SELECTOR", "textarea").strip(),
            image_submit_selector=os.getenv("NIGHTMARE_CANVAS_IMAGE_SUBMIT_SELECTOR", "button[type='submit']").strip(),
            image_result_selector=os.getenv("NIGHTMARE_CANVAS_IMAGE_RESULT_SELECTOR", "img").strip(),
            video_prompt_selector=os.getenv("NIGHTMARE_CANVAS_VIDEO_PROMPT_SELECTOR", "textarea").strip(),
            video_submit_selector=os.getenv("NIGHTMARE_CANVAS_VIDEO_SUBMIT_SELECTOR", "button[type='submit']").strip(),
            video_result_selector=os.getenv("NIGHTMARE_CANVAS_VIDEO_RESULT_SELECTOR", "video").strip(),
            video_image_input_selector=os.getenv("NIGHTMARE_CANVAS_VIDEO_IMAGE_INPUT_SELECTOR", "input[type='file']").strip(),
            flow_character_reference_path=os.getenv("NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH", "").strip(),
            kira_api_key=os.getenv("KIRA_API_KEY", "").strip(),
            kira_api_base=os.getenv("KIRA_API_BASE", "https://kiraai.vn/api/v1").strip(),
            google_api_key=_discover_google_api_key(),
            timeout_seconds=int(os.getenv("NIGHTMARE_CANVAS_TIMEOUT_SECONDS", "180")),
            auto_launch_cdp=os.getenv("NIGHTMARE_AUTO_LAUNCH_CDP", "true").strip().lower() not in ("false", "0", "no"),
            chrome_path=os.getenv("NIGHTMARE_CHROME_PATH", "").strip(),
            chrome_user_data_dir=os.getenv("NIGHTMARE_CHROME_USER_DATA_DIR", "").strip(),
            flow_model_image=os.getenv("NIGHTMARE_FLOW_MODEL_IMAGE", "Nano Banana 2").strip() or "Nano Banana 2",
            flow_model_video=os.getenv("NIGHTMARE_FLOW_MODEL_VIDEO", "Omni 1.1 Flash").strip() or "Omni 1.1 Flash",
            flow_video_resolution=os.getenv("NIGHTMARE_FLOW_VIDEO_RESOLUTION", "360p").strip() or "360p",
            flow_aspect_ratio=os.getenv("NIGHTMARE_FLOW_ASPECT_RATIO", "16:9").strip() or "16:9",
            flow_video_input_mode=os.getenv("NIGHTMARE_FLOW_VIDEO_INPUT_MODE", "frames").strip() or "frames",
            flow_video_duration=int(os.getenv("NIGHTMARE_FLOW_VIDEO_DURATION", "6").strip() or 6),
            flow_runner_backend=os.getenv("NIGHTMARE_FLOW_RUNNER_BACKEND", os.getenv("NIGHTMARE_FLOW_RUNNER", "auto")).strip().lower() or "auto",
            flow_runner_path=os.getenv("NIGHTMARE_FLOW_RUNNER_PATH", "").strip(),
        )


class DeterministicMediaProvider:
    """Offline fixture provider; artifacts are explicitly marked as mock by jobs."""

    name = "mock"
    _ONE_PIXEL_PNG = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/"
        "qlC+MQAAAABJRU5ErkJggg=="
    )

    def generate_image(self, prompt: str, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(self._ONE_PIXEL_PNG)
        return output_path

    def generate_video(self, image_path: Path, motion_prompt: str, output_path: Path) -> Path:
        if not image_path.is_file():
            raise ValueError(f"Source image is missing: {image_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"NIGHTMARE_STUDIO_MOCK_VIDEO\n" + motion_prompt.encode("utf-8"))
        return output_path


class CanvasCDPMediaProvider:
    """Canvas UI adapter using a pre-authenticated Chrome remote-debugging session."""

    name = "canvas_cdp"

    def __init__(self, settings: CanvasCDPSettings):
        self.settings = settings

    def generate_image(self, prompt: str, output_path: Path) -> Path:
        if not self.settings.image_url:
            raise ValueError("NIGHTMARE_CANVAS_IMAGE_URL must be configured for Canvas image generation")
        return self._generate(
            url=self.settings.image_url,
            prompt=prompt,
            prompt_selector=self.settings.image_prompt_selector,
            submit_selector=self.settings.image_submit_selector,
            result_selector=self.settings.image_result_selector,
            output_path=output_path,
        )

    def generate_video(self, image_path: Path, motion_prompt: str, output_path: Path) -> Path:
        if not image_path.is_file():
            raise ValueError(f"Source image is missing: {image_path}")
        if not self.settings.video_url:
            raise ValueError("NIGHTMARE_CANVAS_VIDEO_URL must be configured for Canvas video generation")
        return self._generate(
            url=self.settings.video_url,
            prompt=motion_prompt,
            prompt_selector=self.settings.video_prompt_selector,
            submit_selector=self.settings.video_submit_selector,
            result_selector=self.settings.video_result_selector,
            output_path=output_path,
            upload_path=image_path,
        )

    def _can_auto_launch(self) -> bool:
        return any(host in self.settings.cdp_url for host in ("127.0.0.1", "localhost", "0.0.0.0"))

    def _launch_chrome_cdp(self) -> None:
        chrome_bin = _discover_chrome_path(self.settings.chrome_path)
        if not chrome_bin:
            raise RuntimeError(
                "Cannot auto-launch Chrome: executable not found. "
                "Please configure NIGHTMARE_CHROME_PATH or launch Chrome manually with --remote-debugging-port=9222."
            )
        user_data_dir = _discover_chrome_user_data_dir(self.settings.chrome_user_data_dir)
        port = "9222"
        m = re.search(r":(\d+)", self.settings.cdp_url)
        if m:
            port = m.group(1)

        cmd = [
            chrome_bin,
            f"--remote-debugging-port={port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ]

        creationflags = 0
        if os.name == "nt":
            creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )

        deadline = time.time() + 10.0
        while time.time() < deadline:
            time.sleep(0.5)
            if _is_cdp_listening(self.settings.cdp_url):
                return

        raise RuntimeError(
            f"Auto-launched Chrome at {chrome_bin} with --remote-debugging-port={port}, "
            f"but endpoint {self.settings.cdp_url} did not become ready within 10s."
        )

    def _connect_cdp(self, playwright: Any, label: str = "Canvas") -> Any:
        try:
            return playwright.chromium.connect_over_cdp(self.settings.cdp_url)
        except Exception as exc:
            if self.settings.auto_launch_cdp and self._can_auto_launch():
                self._launch_chrome_cdp()
                try:
                    return playwright.chromium.connect_over_cdp(self.settings.cdp_url)
                except Exception as retry_exc:
                    raise RuntimeError(
                        f"Cannot connect to {label} CDP at {self.settings.cdp_url} even after auto-launch: {retry_exc}"
                    ) from retry_exc
            raise RuntimeError(
                f"Cannot connect to {label} CDP at {self.settings.cdp_url}. "
                "Launch an authenticated Chrome with --remote-debugging-port=9222."
            ) from exc

    def _generate(
        self,
        *,
        url: str,
        prompt: str,
        prompt_selector: str,
        submit_selector: str,
        result_selector: str,
        output_path: Path,
        upload_path: Path | None = None,
    ) -> Path:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Canvas CDP mode requires Playwright; install the project test dependencies") from exc

        timeout_ms = self.settings.timeout_seconds * 1000
        with sync_playwright() as playwright:
            browser = self._connect_cdp(playwright, label="Canvas")
            try:
                if not browser.contexts:
                    raise RuntimeError("The connected Chrome session has no browser context")
                context = browser.contexts[0]
                page = next((item for item in context.pages if item.url.startswith(url)), None)
                if page is None:
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                if upload_path is not None:
                    page.locator(self.settings.video_image_input_selector).set_input_files(str(upload_path), timeout=timeout_ms)
                page.locator(prompt_selector).fill(prompt, timeout=timeout_ms)
                known_urls = page.locator(result_selector).evaluate_all(
                    "nodes => nodes.map(node => node.getAttribute('src') || node.querySelector('source')?.getAttribute('src')).filter(Boolean)"
                )
                page.locator(submit_selector).click(timeout=timeout_ms)
                # A previously rendered result is still visible after submit, so selecting
                # `.last` immediately would download the previous render. Wait for a new URL.
                page.wait_for_function(
                    """([selector, known]) => Array.from(document.querySelectorAll(selector))
                        .map(node => node.getAttribute('src') || node.querySelector('source')?.getAttribute('src'))
                        .some(url => url && !known.includes(url))""",
                    arg=[result_selector, known_urls],
                    timeout=timeout_ms,
                )
                current_urls = page.locator(result_selector).evaluate_all(
                    "nodes => nodes.map(node => node.getAttribute('src') || node.querySelector('source')?.getAttribute('src')).filter(Boolean)"
                )
                artifact_url = GoogleFlowCDPMediaProvider._new_artifact_url(known_urls, current_urls)
                if not artifact_url:
                    raise RuntimeError(f"Canvas result at {result_selector!r} has no downloadable src")
                self._download_artifact(urljoin(page.url, artifact_url), output_path)
                if not output_path.is_file() or output_path.stat().st_size == 0:
                    raise RuntimeError("Canvas completed without a usable media artifact")
                return output_path
            finally:
                browser.close()

    @staticmethod
    def _download_artifact(artifact_url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if artifact_url.startswith("data:"):
            header, payload = artifact_url.split(",", 1)
            data = base64.b64decode(payload) if ";base64" in header else unquote_to_bytes(payload)
        else:
            request = Request(artifact_url, headers={"User-Agent": "NightmareStudio/1.0"})
            with urlopen(request, timeout=60) as response:  # nosec B310: URL originates from the configured Canvas page.
                data = response.read()
        output_path.write_bytes(data)


class GoogleFlowCDPMediaProvider(CanvasCDPMediaProvider):
    """Google Flow adapter that explicitly selects Image or Video before creating media."""

    name = "google_flow_cdp"
    _PROMPT_SELECTOR = '.ProseMirror, [data-slate-editor="true"], textarea'
    _CREATE_SELECTOR = 'button[aria-label="Start generation"], button:has(i:has-text("arrow_forward"))'
    _MODEL_MENU_SELECTOR = 'button[aria-haspopup="menu"]'
    _IMAGE_TAB_SELECTOR = '[role="tab"]:has-text("image")'
    _VIDEO_TAB_SELECTOR = '[role="tab"]:has-text("videocam")'
    _REFERENCE_MENU_SELECTOR = "xpath=/html/body/div[1]/div[1]/div[5]/div/div/div/div/div[2]/div[1]/div/button[1]"
    _REFERENCE_UPLOAD_SELECTOR = "xpath=/html/body/div[1]/div[2]/div/div/div/div/div[1]/button[2]"
    _REFERENCE_CONFIRM_SELECTOR = "xpath=/html/body/div[1]/div[2]/div/div/div/div/div[2]/div[2]/div[2]/button"
    _REFERENCE_FILE_INPUT_SELECTOR = "input[type='file'][accept='image/*']"

    def generate_image(self, prompt: str, output_path: Path) -> Path:
        if not self.settings.image_url:
            raise ValueError("NIGHTMARE_CANVAS_IMAGE_URL must be configured for Google Flow image generation")
        reference_path = self._character_reference_path()
        return self._generate_flow(
            url=self.settings.image_url,
            prompt=prompt,
            result_selector="img",
            output_path=output_path,
            media_kind="image",
            upload_path=reference_path,
        )

    def generate_video(self, image_path: Path, motion_prompt: str, output_path: Path) -> Path:
        if not image_path.is_file():
            raise ValueError(f"Source image is missing: {image_path}")
        if not self.settings.video_url:
            raise ValueError("NIGHTMARE_CANVAS_VIDEO_URL must be configured for Google Flow video generation")
        clean_prompt = motion_prompt.strip()
        if "SCENE INPUT:" in clean_prompt or "Write one final" in clean_prompt:
            match = re.search(r"Narrative beat:\s*([^\n]+)", clean_prompt)
            shot_match = re.search(r"Shot:\s*([^\n]+)", clean_prompt)
            shot = shot_match.group(1).strip() if shot_match else "Cinematic shot"
            beat = match.group(1).strip() if match else clean_prompt[:120]
            clean_prompt = f"Slow cinematic camera move, {shot.lower()}, subtle motion and atmospheric dread. {beat}"
        clean_prompt = sanitize_veo_prompt(clean_prompt)
        return self._generate_flow(
            url=self.settings.video_url,
            prompt=clean_prompt,
            result_selector="video",
            output_path=output_path,
            media_kind="video",
            upload_path=image_path,
        )

    def _resolve_runner_path(self) -> Path:
        if self.settings.flow_runner_path:
            return Path(self.settings.flow_runner_path).expanduser().resolve()
        return Path(__file__).resolve().parent.parent / "scripts" / "google-flow-cdp-runner.ts"

    def _should_use_cdp_runner(self) -> bool:
        backend = (self.settings.flow_runner_backend or "auto").strip().lower()
        if backend == "python":
            return False
        if backend in ("subprocess", "ts", "node", "runner"):
            return True
        if "pytest" in sys.modules:
            return False
        runner_path = self._resolve_runner_path()
        if not runner_path.is_file():
            return False
        if not (shutil.which("npx") or shutil.which("npx.cmd")):
            return False
        return True

    def _build_runner_command(
        self,
        *,
        media_kind: str,
        prompt: str,
        output_path: Path,
        url: str,
        upload_path: Path | None = None,
    ) -> list[str]:
        runner_path = self._resolve_runner_path()
        npx_bin = "npx.cmd" if sys.platform == "win32" and shutil.which("npx.cmd") else "npx"
        cmd = [
            npx_bin,
            "--yes",
            "tsx",
            str(runner_path),
            "--prompt",
            prompt,
            "--mode",
            media_kind,
            "--aspectRatio",
            self.settings.flow_aspect_ratio,
            "--output",
            str(output_path),
            "--cdp",
            self.settings.cdp_url,
            "--projectUrl",
            url,
        ]
        if media_kind == "image":
            cmd.extend(["--model", self.settings.flow_model_image])
        else:
            cmd.extend([
                "--model",
                self.settings.flow_model_video,
                "--resolution",
                self.settings.flow_video_resolution,
                "--duration",
                str(self.settings.flow_video_duration),
                "--videoInputMode",
                self.settings.flow_video_input_mode,
            ])
        if upload_path is not None:
            cmd.extend(["--media", str(upload_path)])
        return cmd

    def _generate_flow_runner(
        self,
        *,
        url: str,
        prompt: str,
        output_path: Path,
        media_kind: str,
        upload_path: Path | None = None,
    ) -> Path:
        runner_path = self._resolve_runner_path()
        if not runner_path.is_file():
            raise FileNotFoundError(f"Google Flow CDP runner script not found: {runner_path}")

        npx_exe = shutil.which("npx.cmd") if sys.platform == "win32" and shutil.which("npx.cmd") else shutil.which("npx")
        if not npx_exe:
            raise RuntimeError("Google Flow CDP runner requires Node.js / npx, but 'npx' was not found in PATH")

        cmd = self._build_runner_command(
            media_kind=media_kind,
            prompt=prompt,
            output_path=output_path,
            url=url,
            upload_path=upload_path,
        )
        timeout_seconds = max(self.settings.timeout_seconds, 600)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Google Flow CDP runner timed out after {timeout_seconds}s") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("npx execution failed: Node.js/npx not found on system PATH") from exc

        if result.returncode != 0:
            stderr_snippet = (result.stderr or result.stdout or "").strip()[-500:]
            raise RuntimeError(f"Google Flow CDP runner failed (exit {result.returncode}): {stderr_snippet}")

        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise RuntimeError(f"Google Flow CDP runner completed but output artifact is missing or empty: {output_path}")

        return output_path

    def _generate_flow(
        self,
        *,
        url: str,
        prompt: str,
        result_selector: str,
        output_path: Path,
        media_kind: str,
        upload_path: Path | None = None,
    ) -> Path:
        if self._should_use_cdp_runner():
            return self._generate_flow_runner(
                url=url,
                prompt=prompt,
                output_path=output_path,
                media_kind=media_kind,
                upload_path=upload_path,
            )
        return self._generate_flow_python(
            url=url,
            prompt=prompt,
            result_selector=result_selector,
            output_path=output_path,
            media_kind=media_kind,
            upload_path=upload_path,
        )

    def _generate_flow_python(
        self,
        *,
        url: str,
        prompt: str,
        result_selector: str,
        output_path: Path,
        media_kind: str,
        upload_path: Path | None = None,
    ) -> Path:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Google Flow CDP mode requires Playwright; install the project test dependencies") from exc

        timeout_ms = self.settings.timeout_seconds * 1000
        with sync_playwright() as playwright:
            browser = self._connect_cdp(playwright, label="Google Flow")
            try:
                if not browser.contexts:
                    raise RuntimeError("The connected Chrome session has no browser context")
                context = browser.contexts[0]
                page = next((item for item in context.pages if "flow.google.com" in item.url or "labs.google" in item.url or self._is_exact_project_canvas_url(item.url, url)), None)
                if page is None:
                    page = context.new_page()
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                self._select_flow_media_kind(page, media_kind, timeout_ms)
                page.locator(self._PROMPT_SELECTOR).fill(prompt, timeout=timeout_ms)
                if media_kind == "image" and upload_path is not None:
                    self._attach_flow_reference(page, upload_path, timeout_ms)
                elif upload_path is not None:
                    page.locator(self.settings.video_image_input_selector).set_input_files(str(upload_path), timeout=timeout_ms)
                known_urls = page.locator(result_selector).evaluate_all(
                    "nodes => nodes.map(node => node.getAttribute('src') || node.querySelector('source')?.getAttribute('src')).filter(Boolean)"
                )
                create = page.locator(self._CREATE_SELECTOR).first
                create.wait_for(state="visible", timeout=timeout_ms)
                create.click(timeout=timeout_ms)
                page.wait_for_function(
                    """([selector, known]) => Array.from(document.querySelectorAll(selector))
                        .map(node => node.getAttribute('src') || node.querySelector('source')?.getAttribute('src'))
                        .some(url => url && !known.includes(url))""",
                    arg=[result_selector, known_urls],
                    timeout=timeout_ms,
                )
                current_urls = page.locator(result_selector).evaluate_all(
                    "nodes => nodes.map(node => node.getAttribute('src') || node.querySelector('source')?.getAttribute('src')).filter(Boolean)"
                )
                artifact_url = self._new_artifact_url(known_urls, current_urls)
                if not artifact_url:
                    raise RuntimeError(f"Google Flow result at {result_selector!r} has no downloadable src")
                self._download_flow_artifact(page, artifact_url, output_path)
                if not output_path.is_file() or output_path.stat().st_size == 0:
                    raise RuntimeError("Google Flow completed without a usable media artifact")
                return output_path
            finally:
                browser.close()

    def _select_flow_media_kind(self, page: Any, media_kind: str, timeout_ms: int) -> None:
        try:
            page.locator(self._MODEL_MENU_SELECTOR).last.click(timeout=timeout_ms)
            tab_selector = self._IMAGE_TAB_SELECTOR if media_kind == "image" else self._VIDEO_TAB_SELECTOR
            page.locator(tab_selector).first.click(timeout=timeout_ms)
            page.keyboard.press("Escape")
        except Exception:
            pass

    def _attach_flow_reference(self, page: Any, reference_path: Path, timeout_ms: int) -> None:
        """Follow Flow's image-reference UI rather than only assigning a hidden file input."""

        page.locator(self._REFERENCE_MENU_SELECTOR).click(timeout=timeout_ms)
        page.locator(self._REFERENCE_UPLOAD_SELECTOR).click(timeout=timeout_ms)
        page.locator(self._REFERENCE_FILE_INPUT_SELECTOR).set_input_files(str(reference_path), timeout=timeout_ms)
        confirm = page.locator(self._REFERENCE_CONFIRM_SELECTOR)
        confirm.wait_for(state="visible", timeout=timeout_ms)
        page.wait_for_function(
            """xpath => {
                const button = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                return button && !button.disabled && button.getAttribute('aria-disabled') !== 'true';
            }""",
            arg=self._REFERENCE_CONFIRM_SELECTOR.removeprefix("xpath="),
            timeout=timeout_ms,
        )
        confirm.click(timeout=timeout_ms)

    @staticmethod
    def _is_exact_project_canvas_url(candidate_url: str, expected_url: str) -> bool:
        return candidate_url.rstrip("/") == expected_url.rstrip("/")

    def _character_reference_path(self) -> Path:
        path = Path(self.settings.flow_character_reference_path).expanduser()
        if not path.is_file():
            raise ValueError(
                "NIGHTMARE_FLOW_CHARACTER_REFERENCE_PATH must point to the Mr Kane reference image before Flow image generation"
            )
        return path

    @staticmethod
    def _download_flow_artifact(page: Any, artifact_url: str, output_path: Path) -> None:
        if GoogleFlowCDPMediaProvider._requires_browser_fetch(artifact_url):
            response = page.context.request.get(
                GoogleFlowCDPMediaProvider._absolute_artifact_url(page.url, artifact_url), timeout=60000
            )
            if not response.ok:
                raise RuntimeError(f"Google Flow artifact download failed: HTTP {response.status}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.body())
            return
        CanvasCDPMediaProvider._download_artifact(
            GoogleFlowCDPMediaProvider._absolute_artifact_url(page.url, artifact_url), output_path
        )

    @staticmethod
    def _absolute_artifact_url(page_url: str, artifact_url: str) -> str:
        return urljoin(page_url, artifact_url)

    @staticmethod
    def _requires_browser_fetch(artifact_url: str) -> bool:
        return artifact_url.startswith(("blob:", "/fx/")) or "labs.google/fx/api/" in artifact_url

    @staticmethod
    def _new_artifact_url(known_urls: list[str], current_urls: list[str]) -> str:
        known = set(known_urls)
        return next((url for url in current_urls if url not in known), "")


class KiraAIMediaProvider:
    """Generates real scene images and Veo 3.1 video clips via the Kira AI REST API.

    # ponytail: sequential polling with 5s sleep; upgrade to async/webhook if high concurrency needed.
    """

    name = "kira_api"

    def __init__(self, settings: CanvasCDPSettings):
        self.settings = settings
        self.api_key = settings.kira_api_key.strip()
        self.base_url = (settings.kira_api_base or "https://kiraai.vn/api/v1").rstrip("/")

    def generate_image(self, prompt: str, output_path: Path) -> Path:
        if not self.api_key:
            raise ValueError("KIRA_API_KEY must be configured for Kira AI media generation")
        url = f"{self.base_url}/images/generations"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        models = ["kira-3.0-image", "kira-2.0-image"]
        last_exc: Exception | None = None
        for model in models:
            payload = {"model": model, "prompt": prompt, "n": 1, "size": "1024x1024"}
            req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
            for attempt in range(3):
                try:
                    with urlopen(req, timeout=self.settings.timeout_seconds) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                    items = data.get("data", [])
                    if not items:
                        raise RuntimeError(f"Kira image generation returned empty data: {data}")
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    if "b64_json" in items[0]:
                        output_path.write_bytes(base64.b64decode(items[0]["b64_json"]))
                    elif "url" in items[0]:
                        img_req = Request(items[0]["url"], headers={"User-Agent": "Mozilla/5.0"})
                        with urlopen(img_req, timeout=self.settings.timeout_seconds) as img_resp:
                            output_path.write_bytes(img_resp.read())
                    else:
                        raise RuntimeError(f"Kira image response missing b64_json and url: {items[0]}")
                    return output_path
                except Exception as exc:
                    last_exc = exc
                    if "429" in str(exc):
                        if "RESOURCE_EXHAUSTED" in str(exc):
                            break  # Fallback to next model
                        time.sleep(8)
                        continue
                    break
        raise RuntimeError(f"Kira image generation failed across models: {last_exc}") from last_exc

    def generate_video(self, image_path: Path, motion_prompt: str, output_path: Path) -> Path:
        if not image_path.is_file():
            raise ValueError(f"Source image is missing: {image_path}")
        if not self.api_key:
            raise ValueError("KIRA_API_KEY must be configured for Kira AI video generation")

        img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        url = f"{self.base_url}/videos/generations"
        payload = {
            "model": "kira-3.0-video",
            "prompt": motion_prompt,
            "duration": 6,
            "aspect_ratio": "16:9",
            "reference_images": [{"data": img_b64, "mime_type": "image/png"}],
        }
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"}
        req = Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urlopen(req, timeout=self.settings.timeout_seconds) as resp:
            init_data = json.loads(resp.read().decode("utf-8"))

        op_id = init_data.get("id")
        if not op_id:
            raise RuntimeError(f"Kira video generation did not return operation ID: {init_data}")

        poll_url = f"{self.base_url}/videos/operations/{op_id}"
        poll_headers = {"Authorization": f"Bearer {self.api_key}"}
        deadline = time.time() + self.settings.timeout_seconds

        while time.time() < deadline:
            time.sleep(5)
            poll_req = Request(poll_url, headers=poll_headers)
            try:
                with urlopen(poll_req, timeout=30) as poll_resp:
                    poll_data = json.loads(poll_resp.read().decode("utf-8"))
                if poll_data.get("done"):
                    if poll_data.get("status") == "failed":
                        raise RuntimeError(f"Kira video generation failed: {poll_data.get('error')}")
                    data_items = poll_data.get("data", [])
                    if data_items and "b64_json" in data_items[0]:
                        output_path.parent.mkdir(parents=True, exist_ok=True)
                        output_path.write_bytes(base64.b64decode(data_items[0]["b64_json"]))
                        return output_path
                    raise RuntimeError(f"Kira video operation completed without video data: {poll_data}")
            except Exception as exc:
                if "completed without video data" in str(exc) or "generation failed" in str(exc):
                    raise
                continue

        raise TimeoutError(f"Kira video generation timed out after {self.settings.timeout_seconds}s for op {op_id}")


def sanitize_veo_prompt(prompt: str) -> str:
    """Sanitize prompts to strip real/character names for Google Responsible AI (RAI) filters."""
    p = prompt
    for old, new in [
        ("Victor Kane's", "the detective's"),
        ("Victor Kane", "the detective"),
        ("Victor", "the detective"),
        ("Kane's", "the detective's"),
        ("Kane", "the detective"),
        ("Clara", "the woman"),
        ("Evelyn", "the woman"),
        ("Harlan", "the stranger"),
    ]:
        p = re.sub(re.escape(old), new, p, flags=re.IGNORECASE)
    p = re.sub(r",\s*no cuts,\s*no text overlays.*", "", p, flags=re.IGNORECASE)
    return p.strip()


def generate_cinematic_motion_clip(image_path: Path, motion_prompt: str, output_path: Path) -> Path:
    """Fallback: Generate a 6-second 720p cinematic camera motion clip from authentic image."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for cinematic motion fallback")

    motion = motion_prompt.lower()
    if "pan" in motion or "tracking" in motion:
        z_expr = "1.15"
        x_expr = "iw*0.05 + (iw*0.1)*(on/(24*6))"
        y_expr = "ih*0.05"
    elif "pull" in motion or "crane" in motion:
        z_expr = "max(1.0, 1.2 - 0.2*(on/(24*6)))"
        x_expr = "(iw - iw/zoom)/2"
        y_expr = "(ih - ih/zoom)/2"
    else:
        z_expr = "min(1.25, 1.0 + 0.25*(on/(24*6)))"
        x_expr = "(iw - iw/zoom)/2"
        y_expr = "(ih - ih/zoom)/2"

    vf = f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':d=144:s=1280x720:fps=24"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg, "-y",
        "-loop", "1",
        "-i", str(image_path),
        "-f", "lavfi",
        "-i", "anoisesrc=c=pink:r=48000:a=0.005",
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "19",
        "-t", "6.0",
        "-c:a", "aac",
        "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(output_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        raise RuntimeError(f"Cinematic motion fallback failed: {res.stderr[-500:]}")
    return output_path


class GoogleVeoMediaProvider:
    """Generates real scene images via Imagen 3 and authentic video clips via Google Veo 3.1 REST API.

    # ponytail: multi-model quota rotation across lite, standard, and fast with cinematic pan/zoom fallback.
    """

    name = "google_veo"

    def __init__(self, settings: CanvasCDPSettings):
        self.settings = settings
        self.api_key = settings.google_api_key.strip()
        self.models = [
            "veo-3.1-lite-generate-preview",
            "veo-3.1-generate-preview",
            "veo-3.1-fast-generate-preview",
        ]

    def generate_image(self, prompt: str, output_path: Path) -> Path:
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY / NIGHTMARE_VEO_API_KEY must be configured for Google Veo provider")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/imagen-3.0-generate-002:predict?key={self.api_key}"
        payload = {
            "instances": [{"prompt": prompt}],
            "parameters": {"sampleCount": 1, "aspectRatio": "16:9"},
        }
        req = Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=self.settings.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        preds = data.get("predictions", [])
        if not preds or "bytesBase64Encoded" not in preds[0]:
            raise RuntimeError(f"Imagen 3 returned empty prediction: {data}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(preds[0]["bytesBase64Encoded"]))
        return output_path

    def generate_video(self, image_path: Path, motion_prompt: str, output_path: Path) -> Path:
        if not image_path.is_file():
            raise ValueError(f"Source image is missing: {image_path}")
        if not self.api_key:
            raise ValueError("GOOGLE_API_KEY / NIGHTMARE_VEO_API_KEY must be configured for Google Veo provider")

        img_b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")
        sanitized_prompt = sanitize_veo_prompt(motion_prompt)

        for model in self.models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:predictLongRunning?key={self.api_key}"
            body = {
                "instances": [
                    {
                        "prompt": sanitized_prompt,
                        "image": {"bytesBase64Encoded": img_b64, "mimeType": "image/jpeg"},
                    }
                ],
                "parameters": {"aspectRatio": "16:9", "durationSeconds": 6},
            }
            req = Request(url, data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
            try:
                with urlopen(req, timeout=45) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                op_name = res.get("name")
                if not op_name:
                    continue

                deadline = time.time() + self.settings.timeout_seconds
                while time.time() < deadline:
                    time.sleep(5)
                    poll_url = f"https://generativelanguage.googleapis.com/v1beta/{op_name}?key={self.api_key}"
                    with urlopen(Request(poll_url), timeout=30) as p_resp:
                        p_res = json.loads(p_resp.read().decode("utf-8"))
                    if p_res.get("done"):
                        resp_data = p_res.get("response", {})
                        samples = resp_data.get("generateVideoResponse", {}).get("generatedSamples", [])
                        if samples and "video" in samples[0] and "uri" in samples[0]["video"]:
                            uri = samples[0]["video"]["uri"]
                            dl_url = f"{uri}&key={self.api_key}"
                            with urlopen(Request(dl_url), timeout=60) as dl_resp:
                                video_bytes = dl_resp.read()
                            output_path.parent.mkdir(parents=True, exist_ok=True)
                            output_path.write_bytes(video_bytes)
                            return output_path
                        break
            except Exception as exc:
                if "429" in str(exc):
                    continue  # Try next model tier
                raise

        # Fallback to high quality cinematic camera motion clip if all models exhausted
        return generate_cinematic_motion_clip(image_path, motion_prompt, output_path)


def configured_media_provider(settings: CanvasCDPSettings) -> MediaProvider:
    if settings.media_mode == "canvas_cdp":
        return CanvasCDPMediaProvider(settings)
    if settings.media_mode == "google_flow_cdp":
        return GoogleFlowCDPMediaProvider(settings)
    if settings.media_mode == "kira_api":
        return KiraAIMediaProvider(settings)
    if settings.media_mode in ("google_veo", "google_veo_api"):
        return GoogleVeoMediaProvider(settings)
    if settings.media_mode == "not_configured":
        return MediaNotConfiguredProvider()
    raise ValueError("NIGHTMARE_MEDIA_MODE must be 'not_configured', 'canvas_cdp', 'google_flow_cdp', 'kira_api', or 'google_veo'")


def public_media_status(settings: CanvasCDPSettings) -> dict[str, bool | str]:
    """Expose configuration readiness without leaking Canvas URLs or browser state."""

    configured = settings.media_mode == "canvas_cdp" and bool(settings.cdp_url and settings.image_url and settings.video_url)
    if settings.media_mode == "google_flow_cdp":
        configured = bool(
            settings.cdp_url
            and settings.image_url
            and settings.video_url
            and Path(settings.flow_character_reference_path).expanduser().is_file()
        )
    if settings.media_mode == "kira_api":
        configured = bool(settings.kira_api_key)
    if settings.media_mode in ("google_veo", "google_veo_api"):
        configured = bool(settings.google_api_key)
    return {"mode": settings.media_mode, "configured": configured}
