from app.domain import EpisodeStatus, can_transition, next_review_status, transitions, status_label


def test_episode_workflow_allows_editorial_happy_path():
    path = [
        EpisodeStatus.DISCOVERED,
        EpisodeStatus.SELECTED,
        EpisodeStatus.REWRITTEN,
        EpisodeStatus.AWAITING_SCRIPT_REVIEW,
        EpisodeStatus.SCRIPT_APPROVED,
        EpisodeStatus.STORYBOARDED,
        EpisodeStatus.AWAITING_ASSET_REVIEW,
        EpisodeStatus.ASSETS_APPROVED,
        EpisodeStatus.ASSETS_READY,
        EpisodeStatus.AUDIO_READY,
        EpisodeStatus.VIDEO_READY,
        EpisodeStatus.AWAITING_FINAL_REVIEW,
        EpisodeStatus.FINAL_APPROVED,
        EpisodeStatus.PUBLISHED,
    ]

    assert all(can_transition(current, following) for current, following in zip(path, path[1:]))


def test_episode_workflow_blocks_publishing_without_final_review():
    assert not can_transition(EpisodeStatus.STORYBOARDED, EpisodeStatus.PUBLISHED)


def test_episode_workflow_blocks_bypassing_a_human_review_gate():
    assert not can_transition(EpisodeStatus.AWAITING_SCRIPT_REVIEW, EpisodeStatus.STORYBOARDED)


def test_review_action_moves_episode_to_the_correct_gate():
    assert next_review_status("script") is EpisodeStatus.AWAITING_SCRIPT_REVIEW
    assert next_review_status("assets") is EpisodeStatus.AWAITING_ASSET_REVIEW
    assert next_review_status("final") is EpisodeStatus.AWAITING_FINAL_REVIEW


def test_transitions_expose_every_legal_override_target():
    assert set(transitions(EpisodeStatus.AWAITING_ASSET_REVIEW)) == {"assets_approved", "storyboarded", "failed"}
    assert set(transitions(EpisodeStatus.VIDEO_READY)) == {"assets_ready", "awaiting_final_review", "failed"}
    assert transitions(EpisodeStatus.PUBLISHED) == []
    for status in EpisodeStatus:
        assert all(can_transition(status, target) for target in transitions(status))


def test_failed_is_a_retryable_terminal_with_label():
    assert transitions(EpisodeStatus.FAILED) == ["rewritten", "selected", "storyboarded"]
    assert status_label(EpisodeStatus.FAILED) == "Failed"
