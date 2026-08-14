# Legacy Victor Kane narrative flow — TDD evidence

Source: journey derived during this fix.

User journey: As an editor, I want a rewrite to preserve the old Victor Kane narrative flow and voice, so the generated story feels like the established long-form horror episodes rather than a generic adaptation.

| Guarantee | Test | Result |
|---|---|---|
| Rewrite prompt rejects screenplay formatting and requires the Victor Kane narrative flow. | `test_rewrite_job_requests_the_legacy_victor_kane_narrative_flow` | PASS |
| Rewrite prompt requires the established cold, darkly humorous narrative voice and recurring motifs. | `test_rewrite_job_requests_the_legacy_victor_kane_narrative_flow` | PASS |
| Storyboard splits scenes by the configured legacy rhythm and preserves 1:1 image-prompt mapping. | `test_storyboard_job_uses_the_legacy_two_phase_llm_prompt_flow` | PASS |
| Existing editorial and media job flows remain intact. | all 10 functions in `tests/test_jobs.py` | PASS |

RED evidence: the new regression test initially failed because the rewrite prompt did not identify screenplay output as incorrect.

GREEN evidence: the focused storyboard flow and Nano Banana rule attachment tests passed, and `python -m compileall -q app tests` passed. The full job module currently fails in the asset stage with `Image CSV export and video-prompt preparation require an approved storyboard`; this is outside the changed storyboard prompt path.

Known gap: `pytest` is not installed in the active Python environment, and importing the complete suite is blocked by missing `beautifulsoup4`; therefore a full `pytest`/coverage run was not available in this workspace.
