"""Media providers for scene images and motion clips.

The Canvas provider connects only to a browser the operator has already opened
with remote debugging enabled.  It never manufactures successful artifacts
when Canvas, an output selector, or the CDP endpoint is unavailable.
"""

from __future__ import annotations

import base64
import json
import os
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
    rules_path = Path(__file__).resolve().parents[1] / "docs" / "veo-3.1-prompt-rules.md"
    rules = rules_path.read_text(encoding="utf-8")
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
    timeout_seconds: int = 180

    @classmethod
    def from_environment(cls) -> "CanvasCDPSettings":
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
            timeout_seconds=int(os.getenv("NIGHTMARE_CANVAS_TIMEOUT_SECONDS", "180")),
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
            try:
                browser = playwright.chromium.connect_over_cdp(self.settings.cdp_url)
            except Exception as exc:
                raise RuntimeError(
                    f"Cannot connect to Canvas CDP at {self.settings.cdp_url}. "
                    "Launch an authenticated Chrome with --remote-debugging-port=9222."
                ) from exc
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
                page.locator(submit_selector).click(timeout=timeout_ms)
                result = page.locator(result_selector).last
                result.wait_for(state="visible", timeout=timeout_ms)
                artifact_url = result.get_attribute("src")
                if not artifact_url:
                    raise RuntimeError(f"Canvas result at {result_selector!r} has no downloadable src")
                self._download_artifact(artifact_url, output_path)
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
    _PROMPT_SELECTOR = '[data-slate-editor="true"]'
    _CREATE_SELECTOR = 'button:has(i:has-text("arrow_forward"))'
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
        return self._generate_flow(
            url=self.settings.video_url,
            prompt=motion_prompt,
            result_selector="video",
            output_path=output_path,
            media_kind="video",
            upload_path=image_path,
        )

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
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Google Flow CDP mode requires Playwright; install the project test dependencies") from exc

        timeout_ms = self.settings.timeout_seconds * 1000
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.connect_over_cdp(self.settings.cdp_url)
            except Exception as exc:
                raise RuntimeError(
                    f"Cannot connect to Google Flow CDP at {self.settings.cdp_url}. "
                    "Launch an authenticated Chrome with --remote-debugging-port=9222."
                ) from exc
            try:
                if not browser.contexts:
                    raise RuntimeError("The connected Chrome session has no browser context")
                context = browser.contexts[0]
                page = next((item for item in context.pages if self._is_exact_project_canvas_url(item.url, url)), None)
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
                create = page.locator(self._CREATE_SELECTOR)
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
        page.locator(self._MODEL_MENU_SELECTOR).last.click(timeout=timeout_ms)
        tab_selector = self._IMAGE_TAB_SELECTOR if media_kind == "image" else self._VIDEO_TAB_SELECTOR
        page.locator(tab_selector).first.click(timeout=timeout_ms)
        page.keyboard.press("Escape")

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


def configured_media_provider(settings: CanvasCDPSettings) -> MediaProvider:
    if settings.media_mode == "canvas_cdp":
        return CanvasCDPMediaProvider(settings)
    if settings.media_mode == "google_flow_cdp":
        return GoogleFlowCDPMediaProvider(settings)
    if settings.media_mode == "not_configured":
        return MediaNotConfiguredProvider()
    raise ValueError("NIGHTMARE_MEDIA_MODE must be 'not_configured', 'canvas_cdp', or 'google_flow_cdp'")


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
    return {"mode": settings.media_mode, "configured": configured}
