import base64
import playwright.sync_api

import pytest

from app.media import (
    CanvasCDPMediaProvider,
    CanvasCDPSettings,
    DeterministicMediaProvider,
    GoogleFlowCDPMediaProvider,
    build_motion_prompt,
    configured_media_provider,
    public_media_status,
)


def test_motion_prompt_preserves_scene_composition_and_uses_controlled_camera_motion():
    prompt = build_motion_prompt({"narration": "A train door opens into darkness.", "shot": "Wide establishing shot"})

    assert "Wide establishing shot" in prompt
    assert "A train door opens into darkness." in prompt
    assert "slow cinematic push-in" in prompt
    assert "no cuts" in prompt


def test_canvas_cdp_mode_selects_the_configured_live_provider(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_MEDIA_MODE", "canvas_cdp")

    provider = configured_media_provider(CanvasCDPSettings.from_environment())

    assert isinstance(provider, CanvasCDPMediaProvider)


def test_google_flow_mode_selects_a_provider_that_switches_between_image_and_video(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_MEDIA_MODE", "google_flow_cdp")
    monkeypatch.setenv("NIGHTMARE_CANVAS_IMAGE_URL", "https://labs.google/fx/vi/tools/flow/project/example")
    monkeypatch.setenv("NIGHTMARE_CANVAS_VIDEO_URL", "https://labs.google/fx/vi/tools/flow/project/example")

    provider = configured_media_provider(CanvasCDPSettings.from_environment())

    assert isinstance(provider, GoogleFlowCDPMediaProvider)


def test_media_defaults_to_not_configured_instead_of_generating_mock_artifacts(monkeypatch):
    monkeypatch.delenv("NIGHTMARE_MEDIA_MODE", raising=False)

    settings = CanvasCDPSettings.from_environment()
    status = public_media_status(settings)

    assert settings.media_mode == "not_configured"
    assert status == {"mode": "not_configured", "configured": False}


def test_mock_media_provider_writes_local_image_and_video_artifacts(tmp_path):
    provider = DeterministicMediaProvider()
    image_path = provider.generate_image("foggy station", tmp_path / "image.png")
    video_path = provider.generate_video(image_path, "slow push-in", tmp_path / "clip.mp4")

    assert image_path.read_bytes().startswith(b"\x89PNG")
    assert video_path.read_bytes().startswith(b"NIGHTMARE_STUDIO_MOCK_VIDEO")


def test_canvas_settings_and_public_status_do_not_expose_workspace_urls(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_MEDIA_MODE", "canvas_cdp")
    monkeypatch.setenv("NIGHTMARE_CANVAS_IMAGE_URL", "https://canvas.example/image")
    monkeypatch.setenv("NIGHTMARE_CANVAS_VIDEO_URL", "https://canvas.example/video")

    settings = CanvasCDPSettings.from_environment()
    status = public_media_status(settings)

    assert settings.image_url.endswith("/image")
    assert status == {"mode": "canvas_cdp", "configured": True}
    assert "canvas.example" not in str(status)


def test_canvas_provider_rejects_missing_workspace_configuration(tmp_path):
    provider = CanvasCDPMediaProvider(CanvasCDPSettings(media_mode="canvas_cdp"))

    with pytest.raises(ValueError, match="IMAGE_URL"):
        provider.generate_image("a corridor", tmp_path / "image.png")
    (tmp_path / "image.png").write_bytes(b"image")
    with pytest.raises(ValueError, match="VIDEO_URL"):
        provider.generate_video(tmp_path / "image.png", "slow push-in", tmp_path / "clip.mp4")


def test_canvas_artifact_downloader_decodes_data_url(tmp_path):
    output_path = tmp_path / "artifact.bin"
    encoded = base64.b64encode(b"canvas-artifact").decode("ascii")

    CanvasCDPMediaProvider._download_artifact(f"data:application/octet-stream;base64,{encoded}", output_path)

    assert output_path.read_bytes() == b"canvas-artifact"


def test_google_flow_resolves_a_relative_artifact_url_against_its_workspace_page():
    artifact_url = GoogleFlowCDPMediaProvider._absolute_artifact_url(
        "https://labs.google/fx/vi/tools/flow/project/example",
        "/fx/api/trpc/media.getMediaUrlRedirect?name=artifact",
    )

    assert artifact_url == "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=artifact"


def test_google_flow_uses_the_authenticated_browser_session_for_its_media_endpoint():
    assert GoogleFlowCDPMediaProvider._requires_browser_fetch(
        "/fx/api/trpc/media.getMediaUrlRedirect?name=artifact"
    )


def test_google_flow_downloads_protected_artifacts_through_the_browser_request_context(tmp_path):
    class Response:
        ok = True
        status = 200

        @staticmethod
        def body():
            return b"authenticated-flow-artifact"

    class RequestContext:
        @staticmethod
        def get(url, timeout):
            assert url == "https://labs.google/fx/api/trpc/media.getMediaUrlRedirect?name=artifact"
            assert timeout == 60000
            return Response()

    class Context:
        request = RequestContext()

    class Page:
        url = "https://labs.google/fx/vi/tools/flow/project/example"
        context = Context()

    output_path = tmp_path / "artifact.jpg"
    GoogleFlowCDPMediaProvider._download_flow_artifact(
        Page(), "/fx/api/trpc/media.getMediaUrlRedirect?name=artifact", output_path
    )

    assert output_path.read_bytes() == b"authenticated-flow-artifact"


def test_google_flow_rejects_the_removed_storyboard_creator_url():
    project_url = "https://labs.google/fx/vi/tools/flow/project/example"
    tool_url = f"{project_url}/tool-version/8dbf5f31-dc6a-45f6-ac7b-4b46e525474c"

    assert GoogleFlowCDPMediaProvider._is_exact_project_canvas_url(project_url, project_url)
    assert GoogleFlowCDPMediaProvider._is_exact_project_canvas_url(f"{project_url}/", project_url)
    assert not GoogleFlowCDPMediaProvider._is_exact_project_canvas_url(f"{project_url}/tools", project_url)
    assert not GoogleFlowCDPMediaProvider._is_exact_project_canvas_url(tool_url, project_url)
    assert not hasattr(GoogleFlowCDPMediaProvider, "_is_storyboard_tool_url")


def test_google_flow_generates_image_and_video_through_the_authenticated_cdp_session(monkeypatch, tmp_path):
    calls: list[tuple[str, object]] = []

    class Response:
        ok = True
        status = 200

        @staticmethod
        def body():
            return b"real-flow-artifact"

    class RequestContext:
        @staticmethod
        def get(url, timeout):
            calls.append(("download", url))
            return Response()

    class Locator:
        def __init__(self, selector):
            self.selector = selector

        @property
        def first(self):
            return self

        @property
        def last(self):
            return self

        def count(self):
            return 0

        def click(self, timeout):
            calls.append(("click", self.selector))
            if self.selector == GoogleFlowCDPMediaProvider._CREATE_SELECTOR:
                page.generation += 1

        def fill(self, value, timeout):
            calls.append(("fill", value))

        def wait_for(self, state, timeout):
            calls.append(("wait", self.selector))

        def get_attribute(self, name):
            return "/fx/api/trpc/media.getMediaUrlRedirect?name=artifact" if name == "src" else None

        def evaluate_all(self, script):
            return ["profile.jpg", *[f"/fx/api/trpc/media.getMediaUrlRedirect?name=scene-{number}" for number in range(page.generation, 0, -1)]]

        def locator(self, selector):
            return Locator(selector)

        def set_input_files(self, path, timeout):
            calls.append(("upload", (self.selector, path)))

    class Keyboard:
        @staticmethod
        def press(key):
            calls.append(("key", key))

    class Page:
        url = "https://labs.google/fx/vi/tools/flow/project/example"
        generation = 0
        context = type("Context", (), {"request": RequestContext()})()
        keyboard = Keyboard()

        @staticmethod
        def locator(selector):
            return Locator(selector)

        @staticmethod
        def wait_for_function(script, arg, timeout):
            calls.append(("result", arg))

    page = Page()

    class Context:
        pages = [page]

        @staticmethod
        def new_page():
            return page

    class Browser:
        contexts = [Context()]

        @staticmethod
        def close():
            calls.append(("browser", "closed"))

    class Session:
        chromium = type("Chromium", (), {"connect_over_cdp": staticmethod(lambda url: Browser())})()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(playwright.sync_api, "sync_playwright", lambda: Session())
    reference_path = tmp_path / "mrkane.jpg"
    reference_path.write_bytes(b"reference")
    settings = CanvasCDPSettings(
        media_mode="google_flow_cdp",
        image_url=page.url,
        video_url=page.url,
        flow_character_reference_path=str(reference_path),
    )
    provider = GoogleFlowCDPMediaProvider(settings)
    image_path = provider.generate_image("A corridor", tmp_path / "image.jpg")
    video_path = provider.generate_video(image_path, "Slow push-in", tmp_path / "clip.mp4")

    assert image_path.read_bytes() == b"real-flow-artifact"
    assert video_path.read_bytes() == b"real-flow-artifact"
    assert ("upload", (settings.video_image_input_selector, str(image_path))) in calls
    assert ("upload", (GoogleFlowCDPMediaProvider._REFERENCE_FILE_INPUT_SELECTOR, str(reference_path))) in calls
    assert ("click", GoogleFlowCDPMediaProvider._IMAGE_TAB_SELECTOR) in calls
    assert ("click", GoogleFlowCDPMediaProvider._VIDEO_TAB_SELECTOR) in calls
    assert ("click", GoogleFlowCDPMediaProvider._REFERENCE_MENU_SELECTOR) in calls
    assert ("click", GoogleFlowCDPMediaProvider._REFERENCE_UPLOAD_SELECTOR) in calls
    assert ("click", GoogleFlowCDPMediaProvider._REFERENCE_CONFIRM_SELECTOR) in calls
    assert calls.index(("fill", "A corridor")) < calls.index(("click", GoogleFlowCDPMediaProvider._REFERENCE_MENU_SELECTOR))
    assert calls.index(("click", GoogleFlowCDPMediaProvider._REFERENCE_MENU_SELECTOR)) < calls.index(
        ("click", GoogleFlowCDPMediaProvider._REFERENCE_UPLOAD_SELECTOR)
    )
    assert calls.index(("click", GoogleFlowCDPMediaProvider._REFERENCE_UPLOAD_SELECTOR)) < calls.index(
        ("upload", (GoogleFlowCDPMediaProvider._REFERENCE_FILE_INPUT_SELECTOR, str(reference_path)))
    )
    assert calls.index(("upload", (GoogleFlowCDPMediaProvider._REFERENCE_FILE_INPUT_SELECTOR, str(reference_path)))) < calls.index(
        ("click", GoogleFlowCDPMediaProvider._REFERENCE_CONFIRM_SELECTOR)
    )


def test_google_flow_uploads_the_mr_kane_reference_before_generating_an_image(monkeypatch, tmp_path):
    reference = tmp_path / "mrkane.jpg"
    reference.write_bytes(b"reference-image")
    settings = CanvasCDPSettings(
        media_mode="google_flow_cdp",
        image_url="https://labs.google/fx/vi/tools/flow/project/example",
        video_url="https://labs.google/fx/vi/tools/flow/project/example",
        flow_character_reference_path=str(reference),
    )
    provider = GoogleFlowCDPMediaProvider(settings)
    captured: dict[str, object] = {}

    def record(**kwargs):
        captured.update(kwargs)
        return tmp_path / "scene.jpg"

    monkeypatch.setattr(provider, "_generate_flow", record)

    provider.generate_image("A midnight corridor", tmp_path / "scene.jpg")

    assert captured["upload_path"] == reference


def test_google_flow_selects_an_artifact_added_after_submission_not_an_older_preview():
    artifact_url = GoogleFlowCDPMediaProvider._new_artifact_url(
        ["profile.jpg", "old-scene.jpg"],
        ["profile.jpg", "new-scene-a.jpg", "new-scene-b.jpg", "old-scene.jpg"],
    )

    assert artifact_url == "new-scene-a.jpg"
