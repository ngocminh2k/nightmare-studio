import base64
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

_spec = importlib.util.find_spec("playwright.sync_api")
if _spec is not None:
    import playwright.sync_api
else:
    playwright = pytest.importorskip("playwright")

from app.media import (
    CanvasCDPMediaProvider,
    CanvasCDPSettings,
    DeterministicMediaProvider,
    GoogleFlowCDPMediaProvider,
    GoogleVeoMediaProvider,
    KiraAIMediaProvider,
    MediaNotConfiguredProvider,
    _discover_chrome_path,
    _discover_chrome_user_data_dir,
    _is_cdp_listening,
    build_motion_prompt,
    configured_media_provider,
    parse_motion_prompt_plan,
    public_media_status,
    sanitize_veo_prompt,
    veo_video_prompt_messages,
    veo_video_prompt_plan_messages,
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

        @staticmethod
        def type(text, delay=0):
            calls.append(("type", text))

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


def test_kira_api_mode_selects_the_configured_live_provider(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_MEDIA_MODE", "kira_api")
    monkeypatch.setenv("KIRA_API_KEY", "test-kira-key")

    settings = CanvasCDPSettings.from_environment()
    provider = configured_media_provider(settings)

    assert isinstance(provider, KiraAIMediaProvider)
    assert provider.api_key == "test-kira-key"
    assert public_media_status(settings) == {"mode": "kira_api", "configured": True}


def test_kira_provider_rejects_missing_api_key(tmp_path):
    provider = KiraAIMediaProvider(CanvasCDPSettings(media_mode="kira_api", kira_api_key=""))
    with pytest.raises(ValueError, match="KIRA_API_KEY"):
        provider.generate_image("horror hallway", tmp_path / "img.png")
    (tmp_path / "img.png").write_bytes(b"dummy")
    with pytest.raises(ValueError, match="KIRA_API_KEY"):
        provider.generate_video(tmp_path / "img.png", "slow push-in", tmp_path / "clip.mp4")


def test_google_veo_mode_selects_configured_provider(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_MEDIA_MODE", "google_veo")
    monkeypatch.setenv("NIGHTMARE_VEO_API_KEY", "test-veo-key")

    settings = CanvasCDPSettings.from_environment()
    provider = configured_media_provider(settings)

    assert isinstance(provider, GoogleVeoMediaProvider)
    assert provider.api_key == "test-veo-key"
    assert public_media_status(settings) == {"mode": "google_veo", "configured": True}


def test_sanitize_veo_prompt_strips_character_names_for_rai_compliance():
    raw = "Victor Kane's eyes widen as Clara looks away from Harlan, no cuts, no text overlays"
    sanitized = sanitize_veo_prompt(raw)

    assert "Victor" not in sanitized
    assert "Kane" not in sanitized
    assert "Clara" not in sanitized
    assert "Harlan" not in sanitized
    assert "the detective" in sanitized
    assert "the woman" in sanitized
    assert "the stranger" in sanitized


def test_google_veo_provider_rejects_missing_api_key(tmp_path):
    provider = GoogleVeoMediaProvider(CanvasCDPSettings(media_mode="google_veo", google_api_key=""))
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        provider.generate_image("horror room", tmp_path / "img.jpg")
    (tmp_path / "img.jpg").write_bytes(b"dummy")
    with pytest.raises(ValueError, match="GOOGLE_API_KEY"):
        provider.generate_video(tmp_path / "img.jpg", "slow pan", tmp_path / "clip.mp4")


def test_auto_launch_cdp_settings_default_and_env(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_AUTO_LAUNCH_CDP", "false")
    monkeypatch.setenv("NIGHTMARE_CHROME_PATH", "/custom/chrome")
    monkeypatch.setenv("NIGHTMARE_CHROME_USER_DATA_DIR", "/custom/profile")

    settings = CanvasCDPSettings.from_environment()
    assert settings.auto_launch_cdp is False
    assert settings.chrome_path == "/custom/chrome"
    assert settings.chrome_user_data_dir == "/custom/profile"


def test_connect_cdp_auto_launches_browser_when_offline(monkeypatch):
    calls: list[str] = []

    class MockBrowser:
        pass

    mock_browser = MockBrowser()
    connect_attempts = 0

    def mock_connect(url):
        nonlocal connect_attempts
        connect_attempts += 1
        if connect_attempts == 1:
            raise ConnectionRefusedError("Port 9222 not open")
        return mock_browser

    mock_playwright = type("Playwright", (), {
        "chromium": type("Chromium", (), {"connect_over_cdp": staticmethod(mock_connect)})()
    })()

    settings = CanvasCDPSettings(
        media_mode="canvas_cdp",
        cdp_url="http://127.0.0.1:9222",
        auto_launch_cdp=True,
    )
    provider = CanvasCDPMediaProvider(settings)

    def mock_launch():
        calls.append("launched_chrome")

    monkeypatch.setattr(provider, "_launch_chrome_cdp", mock_launch)

    result = provider._connect_cdp(mock_playwright, label="Canvas")
    assert result is mock_browser
    assert calls == ["launched_chrome"]
    assert connect_attempts == 2


def test_connect_cdp_fails_closed_when_auto_launch_disabled():
    def mock_connect(url):
        raise ConnectionRefusedError("Port 9222 not open")

    mock_playwright = type("Playwright", (), {
        "chromium": type("Chromium", (), {"connect_over_cdp": staticmethod(mock_connect)})()
    })()

    settings = CanvasCDPSettings(
        media_mode="canvas_cdp",
        cdp_url="http://127.0.0.1:9222",
        auto_launch_cdp=False,
    )
    provider = CanvasCDPMediaProvider(settings)

    with pytest.raises(RuntimeError, match="Cannot connect to Canvas CDP"):
        provider._connect_cdp(mock_playwright, label="Canvas")


def test_discover_chrome_helpers(monkeypatch, tmp_path):
    fake_chrome = tmp_path / "chrome.exe"
    fake_chrome.write_bytes(b"binary")
    assert _discover_chrome_path(str(fake_chrome)) == str(fake_chrome)

    fake_profile = tmp_path / "profile"
    dir_path = _discover_chrome_user_data_dir(str(fake_profile))
    assert dir_path == fake_profile
    assert fake_profile.is_dir()


def test_google_flow_runner_delegates_to_subprocess_for_image_and_video(monkeypatch, tmp_path):
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"reference")
    runner_script = tmp_path / "runner.ts"
    runner_script.write_bytes(b"// mock runner")

    settings = CanvasCDPSettings(
        media_mode="google_flow_cdp",
        image_url="https://flow.google.com/project/test-project",
        video_url="https://flow.google.com/project/test-project",
        flow_character_reference_path=str(reference),
        flow_runner_backend="ts",
        flow_runner_path=str(runner_script),
        flow_model_image="Nano Banana 2",
        flow_model_video="Omni Flash",
        flow_aspect_ratio="16:9",
        flow_video_duration=6,
        flow_video_input_mode="ingredients",
    )
    provider = GoogleFlowCDPMediaProvider(settings)
    executed_cmds = []

    def mock_run(cmd, *args, **kwargs):
        executed_cmds.append(cmd)
        out_idx = cmd.index("--output") + 1
        Path(cmd[out_idx]).write_bytes(b"generated-artifact")
        return subprocess.CompletedProcess(cmd, 0, stdout="success", stderr="")

    monkeypatch.setattr(shutil, "which", lambda exe: "/fake/npx")
    monkeypatch.setattr(subprocess, "run", mock_run)

    img_out = tmp_path / "test-image.png"
    result_img = provider.generate_image("A dark hall", img_out)
    assert result_img.read_bytes() == b"generated-artifact"
    assert "--mode" in executed_cmds[0]
    assert executed_cmds[0][executed_cmds[0].index("--mode") + 1] == "image"
    assert "--model" in executed_cmds[0]
    assert executed_cmds[0][executed_cmds[0].index("--model") + 1] == "Nano Banana 2"
    assert "--media" in executed_cmds[0]
    assert executed_cmds[0][executed_cmds[0].index("--media") + 1] == str(reference)

    vid_out = tmp_path / "test-video.mp4"
    result_vid = provider.generate_video(img_out, "Cinematic push-in", vid_out)
    assert result_vid.read_bytes() == b"generated-artifact"
    assert "--mode" in executed_cmds[1]
    assert executed_cmds[1][executed_cmds[1].index("--mode") + 1] == "video"
    assert "--model" in executed_cmds[1]
    assert executed_cmds[1][executed_cmds[1].index("--model") + 1] == "Omni Flash"
    assert "--resolution" in executed_cmds[1]
    assert executed_cmds[1][executed_cmds[1].index("--resolution") + 1] == "360p"
    assert "--duration" in executed_cmds[1]
    assert executed_cmds[1][executed_cmds[1].index("--duration") + 1] == "6"
    assert "--videoInputMode" in executed_cmds[1]
    assert executed_cmds[1][executed_cmds[1].index("--videoInputMode") + 1] == "ingredients"
    assert "--media" in executed_cmds[1]
    assert executed_cmds[1][executed_cmds[1].index("--media") + 1] == str(img_out)


def test_google_flow_runner_reports_clean_error_when_npx_missing(monkeypatch, tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"ref")
    runner_script = tmp_path / "runner.ts"
    runner_script.write_bytes(b"// mock runner")
    settings = CanvasCDPSettings(
        media_mode="google_flow_cdp",
        image_url="https://flow.google.com/project/test",
        flow_character_reference_path=str(ref),
        flow_runner_backend="ts",
        flow_runner_path=str(runner_script),
    )
    provider = GoogleFlowCDPMediaProvider(settings)
    monkeypatch.setattr(shutil, "which", lambda exe: None)

    with pytest.raises(RuntimeError, match="requires Node.js / npx"):
        provider.generate_image("prompt", tmp_path / "out.png")


def test_google_flow_runner_reports_clean_error_when_script_missing(monkeypatch, tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"ref")
    settings = CanvasCDPSettings(
        media_mode="google_flow_cdp",
        image_url="https://flow.google.com/project/test",
        flow_character_reference_path=str(ref),
        flow_runner_backend="ts",
        flow_runner_path=str(tmp_path / "missing-runner.ts"),
    )
    provider = GoogleFlowCDPMediaProvider(settings)
    monkeypatch.setattr(shutil, "which", lambda exe: "/fake/npx")

    with pytest.raises(FileNotFoundError, match="runner script not found"):
        provider.generate_image("prompt", tmp_path / "out.png")


def test_google_flow_runner_reports_clean_error_on_subprocess_failure(monkeypatch, tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"ref")
    runner_script = tmp_path / "runner.ts"
    runner_script.write_bytes(b"// mock runner")
    settings = CanvasCDPSettings(
        media_mode="google_flow_cdp",
        image_url="https://flow.google.com/project/test",
        flow_character_reference_path=str(ref),
        flow_runner_backend="ts",
        flow_runner_path=str(runner_script),
    )
    provider = GoogleFlowCDPMediaProvider(settings)
    monkeypatch.setattr(shutil, "which", lambda exe: "/fake/npx")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="", stderr="Error: CDP port 9222 connection refused"
        ),
    )

    with pytest.raises(RuntimeError, match="exit 1.*CDP port 9222 connection refused"):
        provider.generate_image("prompt", tmp_path / "out.png")


def test_google_flow_settings_from_environment_loads_runner_options(monkeypatch):
    monkeypatch.setenv("NIGHTMARE_FLOW_RUNNER_BACKEND", "subprocess")
    monkeypatch.setenv("NIGHTMARE_FLOW_MODEL_IMAGE", "Imagen 4")
    monkeypatch.setenv("NIGHTMARE_FLOW_MODEL_VIDEO", "Veo 3.1 - Quality")
    monkeypatch.setenv("NIGHTMARE_FLOW_VIDEO_RESOLUTION", "720p")
    monkeypatch.setenv("NIGHTMARE_FLOW_VIDEO_INPUT_MODE", "frames")
    monkeypatch.setenv("NIGHTMARE_FLOW_ASPECT_RATIO", "9:16")
    monkeypatch.setenv("NIGHTMARE_FLOW_VIDEO_DURATION", "8")
    monkeypatch.setenv("NIGHTMARE_FLOW_RUNNER_PATH", "scripts/custom-runner.ts")

    settings = CanvasCDPSettings.from_environment()
    assert settings.flow_runner_backend == "subprocess"
    assert settings.flow_model_image == "Imagen 4"
    assert settings.flow_model_video == "Veo 3.1 - Quality"
    assert settings.flow_video_resolution == "720p"
    assert settings.flow_video_input_mode == "frames"
    assert settings.flow_aspect_ratio == "9:16"
    assert settings.flow_video_duration == 8
    assert settings.flow_runner_path == "scripts/custom-runner.ts"


def test_disabled_media_provider_raises_clean_error(tmp_path):
    provider = MediaNotConfiguredProvider()
    with pytest.raises(RuntimeError, match="Real media generation is not configured"):
        provider.generate_image("A prompt", tmp_path / "img.png")
    with pytest.raises(RuntimeError, match="Real media generation is not configured"):
        provider.generate_video(tmp_path / "img.png", "A prompt", tmp_path / "vid.mp4")


def test_veo_prompt_messages_and_planning():
    scene = {"number": 1, "shot": "Extreme close-up", "narration": "A shadowy hand grasps the rail."}
    messages = veo_video_prompt_messages(scene)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert "Extreme close-up" in messages[1]["content"]

    plan_messages = veo_video_prompt_plan_messages([scene])
    assert len(plan_messages) == 2
    assert plan_messages[0]["role"] == "system"
    assert "SCENES:" in plan_messages[1]["content"]


def test_parse_motion_prompt_plan():
    valid_json = '{"scenes": [{"number": 1, "motion_prompt": "Slow camera push-in on subject"}]}'
    plan = parse_motion_prompt_plan(valid_json, {1})
    assert plan[1] == "Slow camera push-in on subject"

    with pytest.raises(ValueError, match="invalid batch Veo prompt plan"):
        parse_motion_prompt_plan("not-json", {1})

    with pytest.raises(ValueError, match="must provide one non-empty prompt for every scene"):
        parse_motion_prompt_plan('{"scenes": [{"number": 1, "motion_prompt": ""}]}', {1})


def test_cdp_port_open_and_chrome_discovery(monkeypatch, tmp_path):
    assert _is_cdp_listening("http://127.0.0.1:59999", timeout=0.05) is False

    fake_chrome = tmp_path / "chrome.exe"
    fake_chrome.write_bytes(b"")
    assert _discover_chrome_path(str(fake_chrome)) == str(fake_chrome)

    monkeypatch.setenv("NIGHTMARE_CHROME_PATH", str(fake_chrome))
    assert _discover_chrome_path("") == str(fake_chrome)

    custom_profile = tmp_path / "custom_profile"
    assert _discover_chrome_user_data_dir(str(custom_profile)) == custom_profile
    assert custom_profile.is_dir()





