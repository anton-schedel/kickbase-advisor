"""Run the advisor stages through the `claude` CLI and assemble the advice.

Each stage is a separate headless call: its own prompt, its own slice of the
briefing, plus the conclusions of the stages before it. A stage that fails does
not sink the run — the later stages are told what is missing and the finished
document says so, which is more useful than no advice at all.
"""

import subprocess

from analysis.briefing import compose
from advisor.prompts import DOCUMENT_ORDER, STAGES, Stage, stage_prompt

STAGE_TIMEOUT_SECONDS = 900


def _run_claude(prompt: str, briefing: str, timeout: int) -> tuple[str | None, str]:
    """Returns (answer, error message). Exactly one of the two is set."""
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            input=briefing,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout}s"
    if result.returncode != 0:
        return None, f"claude CLI exited {result.returncode}: {result.stderr.strip()[:300]}"
    answer = result.stdout.strip()
    return (answer, "") if answer else (None, "claude returned nothing")


def _stage_input(stage: Stage, sections: dict, answers: dict[str, str]) -> str:
    briefing = compose(sections, stage.sections, title=f"Kickbase briefing — {stage.title}")
    carried = []
    for key in stage.context_from:
        if key in answers:
            title = next(s.title for s in STAGES if s.key == key)
            carried.append(f"# Already decided — {title}\n\n{answers[key]}")
        else:
            carried.append(
                f"# Already decided — {key}\n\n_This stage failed to run; decide without it "
                f"and say that you did._"
            )
    return "\n\n---\n\n".join([briefing, *carried])


def run_stages(
    sections: dict,
    progress=print,
    timeout: int = STAGE_TIMEOUT_SECONDS,
    on_stage=None,
) -> tuple[str | None, dict]:
    """Run every stage in order. Returns (assembled document, per-stage answers).

    `on_stage(key, answer)` is called as each stage lands, so a stage that
    finishes is saved even if a later one hangs.
    """
    answers: dict[str, str] = {}
    failures: list[str] = []
    for stage in STAGES:
        payload = _stage_input(stage, sections, answers)
        progress(f"  stage '{stage.key}' ({len(payload):,} chars of briefing)...")
        answer, error = _run_claude(stage_prompt(stage), payload, timeout)
        if answer:
            answers[stage.key] = answer
            if on_stage:
                on_stage(stage.key, answer)
            progress(f"  stage '{stage.key}' done ({len(answer):,} chars)")
        else:
            failures.append(f"{stage.key}: {error}")
            progress(f"  stage '{stage.key}' FAILED — {error}")

    if not answers:
        return None, answers
    return assemble(answers, failures), answers


def assemble(answers: dict[str, str], failures: list[str]) -> str:
    parts = []
    for number, key in enumerate(DOCUMENT_ORDER, 1):
        title = next(s.title for s in STAGES if s.key == key)
        if key in answers:
            parts.append(f"## {number}. {title}\n\n{answers[key]}")
        else:
            parts.append(f"## {number}. {title}\n\n_Not available — this stage did not complete._")
    if failures:
        parts.append("## Run notes\n\n" + "\n".join(f"- {f}" for f in failures))
    return "\n\n".join(parts) + "\n"
