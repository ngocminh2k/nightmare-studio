"""Static contract checks for scripts/google-flow-cdp-runner.ts.

The runner has no JS test harness in this repo, so the two rules that matter
(never ask Flow for more than 10s, allow Omni Flash 1.2) are asserted against
the source text here.
"""

import re
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "scripts" / "google-flow-cdp-runner.ts"


def _set_literal(name: str) -> set[int]:
    match = re.search(rf"export const {name} = new Set\(\[([^\]]*)\]\)", RUNNER.read_text(encoding="utf-8"))
    assert match, f"{name} not found in the runner"
    return {int(value) for value in re.findall(r"\d+", match.group(1))}


def test_runner_never_requests_more_than_ten_seconds():
    durations = _set_literal("VIDEO_DURATIONS")
    assert durations == {4, 6, 8, 10}
    assert max(durations) <= 10


def test_runner_accepts_omni_flash_1_2_under_both_ui_spellings():
    source = RUNNER.read_text(encoding="utf-8")
    assert "'Omni Flash 1.2'" in source
    assert "'Omni 1.2 Flash'" in source
