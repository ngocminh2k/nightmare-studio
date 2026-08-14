from app.domain import EpisodeStatus
from app.repository import StudioRepository


def test_repository_persists_project_episode_and_editorial_metadata(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project(name="Victor Kane", description="Weekly first-person horror")
    episode = repo.create_episode(
        project_id=project["id"],
        title="The last passenger",
        source_url="https://www.reddit.com/r/nosleep/example",
        source_text="A short source story.",
    )

    stored = repo.get_episode(episode["id"])

    assert stored["project_id"] == project["id"]
    assert stored["status"] == EpisodeStatus.DISCOVERED.value
    assert stored["source_url"].endswith("/example")
    assert stored["cost_total"] == 0


def test_repository_rejects_cross_project_episode_access(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    first = repo.create_project(name="First", description="")
    second = repo.create_project(name="Second", description="")
    episode = repo.create_episode(first["id"], "Private story", "", "")

    assert repo.get_project_episode(second["id"], episode["id"]) is None


def test_repository_records_review_and_valid_state_transition(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project(name="Victor Kane", description="")
    episode = repo.create_episode(project["id"], "A house that listens", "", "")

    repo.transition_episode(episode["id"], EpisodeStatus.SELECTED, note="Selected by editor")
    review = repo.add_review(episode["id"], gate="source", decision="approved", note="Original enough")

    assert review["decision"] == "approved"
    assert repo.get_episode(episode["id"])["status"] == EpisodeStatus.SELECTED.value


def test_approved_script_review_advances_only_an_episode_waiting_at_that_gate(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project(name="Victor Kane", description="")
    episode = repo.create_episode(project["id"], "The radio knew", "", "A voice used my name.")
    repo.transition_episode(episode["id"], EpisodeStatus.REWRITTEN)
    repo.transition_episode(episode["id"], EpisodeStatus.AWAITING_SCRIPT_REVIEW)

    repo.add_review(episode["id"], gate="script", decision="approved", note="Ready to board")

    assert repo.get_episode(episode["id"])["status"] == EpisodeStatus.SCRIPT_APPROVED.value
