"""HTTP-surface tests for endpoints the workflow tests do not exercise."""

from fastapi.testclient import TestClient

from app.main import create_app


def _client(tmp_path):
    return TestClient(create_app(tmp_path / "studio.db"))


def test_provider_status_is_safe_and_media_configured(tmp_path):
    body = _client(tmp_path).get("/api/providers").json()

    assert body["llm"]["mode"].startswith("mock")
    assert "media" in body
    assert "api_key" not in str(body).lower()


def test_missing_records_return_404(tmp_path):
    client = _client(tmp_path)

    assert client.get("/api/projects/nope").status_code == 404
    assert client.get("/api/episodes/nope").status_code == 404
    assert client.get("/api/episodes/nope/manifest").status_code == 404
    assert client.get("/api/episodes/nope/transitions").status_code == 404
    assert client.get("/api/episodes/nope/reviews").status_code == 404
    assert client.get("/api/episodes/nope/activity").status_code == 404
    assert client.get("/api/episodes/nope/jobs").status_code == 404
    assert client.get("/api/jobs/nope/events").status_code == 404


def test_project_brand_bible_patch_and_episode_listing(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/projects", json={"name": "Night Shift", "description": ""}).json()

    patched = client.patch(f"/api/projects/{project['id']}", json={"brand_bible": "Cold dread."}).json()
    created = client.post("/api/episodes", json={"project_id": project["id"], "title": "Eins", "source_url": "", "source_text": "src"}).json()

    assert patched["brand_bible"] == "Cold dread."
    assert client.get(f"/api/projects/{project['id']}/episodes").json()[0]["id"] == created["id"]
    assert client.get("/api/episodes", params={"project_id": project["id"]}).status_code == 200
    assert client.post("/api/episodes", json={"project_id": "ghost", "title": "X"}).status_code == 404


def test_episode_text_fields_are_editable(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/projects", json={"name": "P", "description": ""}).json()
    episode = client.post("/api/episodes", json={"project_id": project["id"], "title": "Old", "source_url": "", "source_text": "s"}).json()

    updated = client.patch(f"/api/episodes/{episode['id']}", json={"title": "Renamed", "script_final": "Final prose."}).json()

    assert updated["title"] == "Renamed"
    assert updated["script_final"] == "Final prose."


def test_invalid_job_kind_and_illegal_override_are_rejected(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/projects", json={"name": "P", "description": ""}).json()
    episode = client.post("/api/episodes", json={"project_id": project["id"], "title": "E", "source_url": "", "source_text": "s"}).json()

    assert client.post(f"/api/episodes/{episode['id']}/jobs/banana").status_code == 422
    assert client.post(f"/api/episodes/{episode['id']}/transition/published").status_code == 409
    assert client.post(f"/api/episodes/{episode['id']}/media-revision").status_code == 409


def test_reviews_and_job_history_are_recorded(tmp_path):
    client = _client(tmp_path)
    project = client.post("/api/projects", json={"name": "P", "description": ""}).json()
    episode = client.post("/api/episodes", json={"project_id": project["id"], "title": "E", "source_url": "", "source_text": "s"}).json()

    queued = client.post(f"/api/episodes/{episode['id']}/jobs/rewrite").json()
    run = client.post(f"/api/episodes/{episode['id']}/jobs/rewrite/run").json()

    assert run["job"]["status"] == "completed"
    assert client.get(f"/api/episodes/{episode['id']}/jobs").json()[0]["id"] == queued["id"]
    assert client.get(f"/api/jobs/{queued['id']}/events").json()
    assert client.post(f"/api/episodes/{episode['id']}/reviews", json={"gate": "script", "decision": "approved", "note": "ok"}).status_code == 201
    assert client.post(f"/api/episodes/{episode['id']}/reviews", json={"gate": "script", "decision": "weird"}).status_code == 422
