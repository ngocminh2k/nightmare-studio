from pathlib import Path
import os
import socket
import subprocess
import sys
import time
import re

from playwright.sync_api import sync_playwright


def test_dashboard_document_declares_a_usable_creator_workspace():
    document = Path(__file__).parents[2] / "app" / "static" / "index.html"

    content = document.read_text(encoding="utf-8")

    assert "Nightmare Studio" in content
    assert "data-testid=\"create-project\"" in content


def test_creator_can_create_a_project_and_episode_in_the_browser(tmp_path):
    port = _available_port()
    database_path = tmp_path / "studio.db"
    environment = {**os.environ, "NIGHTMARE_STUDIO_DB": str(database_path)}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=Path(__file__).parents[2],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_server(port)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_test_id("create-project").click()
            page.locator("#project-form input[name='name']").fill("Night Shift")
            page.locator("#project-form textarea[name='description']").fill("First-person horror")
            page.get_by_role("button", name="Create project").click()
            page.get_by_role("button", name="New episode").click()
            page.locator("#episode-form input[name='title']").fill("The empty elevator")
            page.locator("#episode-form textarea[name='source_text']").fill("The elevator stopped at an impossible floor.")
            page.get_by_role("button", name="Create episode").click()

            page.get_by_role("heading", name="The empty elevator").wait_for(state="visible")
            assert page.get_by_role("button", name=re.compile("The empty elevator")).count() == 1
            page.get_by_test_id("script-editor").fill("Final editorial cut.")
            page.get_by_role("button", name="Save script").click()
            page.get_by_text("Editorial script saved.").wait_for(state="visible")
            assert page.get_by_test_id("script-editor").input_value() == "Final editorial cut."
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_creator_can_cancel_the_log_episode_dialog_without_submitting(tmp_path):
    port = _available_port()
    environment = {**os.environ, "NIGHTMARE_STUDIO_DB": str(tmp_path / "studio.db")}
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=Path(__file__).parents[2],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_server(port)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_test_id("create-project").click()
            page.locator("#project-form input[name='name']").fill("Night Shift")
            page.get_by_role("button", name="Create project").click()
            page.get_by_role("button", name="New episode").click()

            page.locator("#episode-dialog").get_by_role("button", name="Cancel").click()

            assert page.locator("#episode-dialog[open]").count() == 0
            browser.close()
    finally:
        process.terminate()
        process.wait(timeout=10)


def _available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(port: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("Nightmare Studio did not start for the browser test")
