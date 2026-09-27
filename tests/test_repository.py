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


def test_requesting_changes_sends_the_episode_back_instead_of_stranding_it(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project(name="Victor Kane", description="")
    episode = repo.create_episode(project["id"], "The radio knew", "", "A voice used my name.")
    repo.transition_episode(episode["id"], EpisodeStatus.REWRITTEN)
    repo.transition_episode(episode["id"], EpisodeStatus.AWAITING_SCRIPT_REVIEW)

    review = repo.add_review(episode["id"], gate="script", decision="changes_requested", note="Too soft")

    assert review["decision"] == "changes_requested"
    assert repo.get_episode(episode["id"])["status"] == EpisodeStatus.REWRITTEN.value


def test_every_review_gate_can_send_work_back_to_an_editable_status(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project(name="Victor Kane", description="")
    script_path = [
        EpisodeStatus.SELECTED,
        EpisodeStatus.REWRITTEN,
        EpisodeStatus.AWAITING_SCRIPT_REVIEW,
    ]
    for gate, path, editable in [
        ("script", script_path, EpisodeStatus.REWRITTEN),
        ("assets", script_path + [
            EpisodeStatus.SCRIPT_APPROVED,
            EpisodeStatus.STORYBOARDED,
            EpisodeStatus.AWAITING_ASSET_REVIEW,
        ], EpisodeStatus.STORYBOARDED),
        ("final", script_path + [
            EpisodeStatus.SCRIPT_APPROVED,
            EpisodeStatus.STORYBOARDED,
            EpisodeStatus.AWAITING_ASSET_REVIEW,
            EpisodeStatus.ASSETS_APPROVED,
            EpisodeStatus.ASSETS_READY,
            EpisodeStatus.AUDIO_READY,
            EpisodeStatus.VIDEO_READY,
            EpisodeStatus.AWAITING_FINAL_REVIEW,
        ], EpisodeStatus.ASSETS_READY),
    ]:
        episode = repo.create_episode(project["id"], f"Gate {gate}", "", "")
        for status in path:
            repo.transition_episode(episode["id"], status)
        assert repo.get_episode(episode["id"])["status"] == path[-1].value

        repo.add_review(episode["id"], gate=gate, decision="changes_requested", note="Rework")

        assert repo.get_episode(episode["id"])["status"] == editable.value


def test_record_only_review_gate_does_not_move_the_episode(tmp_path):
    repo = StudioRepository(tmp_path / "studio.db")
    project = repo.create_project(name="Victor Kane", description="")
    episode = repo.create_episode(project["id"], "A house that listens", "", "")

    repo.add_review(episode["id"], gate="source", decision="changes_requested", note="Not ours")

    assert repo.get_episode(episode["id"])["status"] == EpisodeStatus.DISCOVERED.value
