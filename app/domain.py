from __future__ import annotations

from enum import Enum


class EpisodeStatus(str, Enum):
    DISCOVERED = "discovered"
    SELECTED = "selected"
    REWRITTEN = "rewritten"
    AWAITING_SCRIPT_REVIEW = "awaiting_script_review"
    SCRIPT_APPROVED = "script_approved"
    STORYBOARDED = "storyboarded"
    AWAITING_ASSET_REVIEW = "awaiting_asset_review"
    ASSETS_APPROVED = "assets_approved"
    ASSETS_READY = "assets_ready"
    AUDIO_READY = "audio_ready"
    VIDEO_READY = "video_ready"
    AWAITING_FINAL_REVIEW = "awaiting_final_review"
    FINAL_APPROVED = "final_approved"
    PUBLISHED = "published"
    FAILED = "failed"


_TRANSITIONS: dict[EpisodeStatus, set[EpisodeStatus]] = {
    EpisodeStatus.DISCOVERED: {EpisodeStatus.SELECTED, EpisodeStatus.REWRITTEN, EpisodeStatus.FAILED},
    EpisodeStatus.SELECTED: {EpisodeStatus.REWRITTEN, EpisodeStatus.FAILED},
    EpisodeStatus.REWRITTEN: {EpisodeStatus.AWAITING_SCRIPT_REVIEW, EpisodeStatus.FAILED},
    EpisodeStatus.AWAITING_SCRIPT_REVIEW: {EpisodeStatus.SCRIPT_APPROVED, EpisodeStatus.FAILED},
    EpisodeStatus.SCRIPT_APPROVED: {EpisodeStatus.STORYBOARDED, EpisodeStatus.FAILED},
    EpisodeStatus.STORYBOARDED: {EpisodeStatus.AWAITING_ASSET_REVIEW, EpisodeStatus.FAILED},
    EpisodeStatus.AWAITING_ASSET_REVIEW: {EpisodeStatus.ASSETS_APPROVED, EpisodeStatus.FAILED},
    EpisodeStatus.ASSETS_APPROVED: {EpisodeStatus.ASSETS_READY, EpisodeStatus.FAILED},
    EpisodeStatus.ASSETS_READY: {EpisodeStatus.AUDIO_READY, EpisodeStatus.VIDEO_READY, EpisodeStatus.FAILED},
    EpisodeStatus.AUDIO_READY: {EpisodeStatus.VIDEO_READY, EpisodeStatus.FAILED},
    EpisodeStatus.VIDEO_READY: {EpisodeStatus.ASSETS_READY, EpisodeStatus.AWAITING_FINAL_REVIEW, EpisodeStatus.FAILED},
    EpisodeStatus.AWAITING_FINAL_REVIEW: {EpisodeStatus.ASSETS_READY, EpisodeStatus.FINAL_APPROVED, EpisodeStatus.FAILED},
    EpisodeStatus.FINAL_APPROVED: {EpisodeStatus.PUBLISHED, EpisodeStatus.FAILED},
    EpisodeStatus.PUBLISHED: set(),
    EpisodeStatus.FAILED: {EpisodeStatus.SELECTED, EpisodeStatus.REWRITTEN, EpisodeStatus.STORYBOARDED},
}

_REVIEW_GATES = {
    "script": EpisodeStatus.AWAITING_SCRIPT_REVIEW,
    "assets": EpisodeStatus.AWAITING_ASSET_REVIEW,
    "final": EpisodeStatus.AWAITING_FINAL_REVIEW,
}

_APPROVED_GATES = {
    "script": EpisodeStatus.SCRIPT_APPROVED,
    "assets": EpisodeStatus.ASSETS_APPROVED,
    "final": EpisodeStatus.FINAL_APPROVED,
}


def can_transition(current: EpisodeStatus | str, target: EpisodeStatus | str) -> bool:
    current_status = EpisodeStatus(current)
    target_status = EpisodeStatus(target)
    return target_status in _TRANSITIONS[current_status]


def next_review_status(gate: str) -> EpisodeStatus:
    try:
        return _REVIEW_GATES[gate]
    except KeyError as exc:
        raise ValueError(f"Unknown review gate: {gate}") from exc


def approved_status(gate: str) -> EpisodeStatus:
    try:
        return _APPROVED_GATES[gate]
    except KeyError as exc:
        raise ValueError(f"Unknown review gate: {gate}") from exc


def status_label(status: EpisodeStatus | str) -> str:
    return str(EpisodeStatus(status).value).replace("_", " ").title()
