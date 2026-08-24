"""Rebuild docs/index.html from the newest briefing data + advice.

Runs automatically at the end of advise.py; run standalone to re-render
without fetching fresh data.

Usage: uv run scripts/build_site.py
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from analysis.site import build_site


def render_latest(project_root: Path) -> Path:
    briefings = project_root / "data" / "briefings"
    data_files = sorted(briefings.glob("*_data.json"))
    if not data_files:
        sys.exit("No briefing data found — run scripts/advise.py first.")
    data_file = data_files[-1]
    stamp = data_file.name.removesuffix("_data.json")
    advice_file = briefings / f"{stamp}_advice.md"
    if advice_file.exists():
        advice_md = advice_file.read_text()
    else:
        # Data refreshed without a new advice run — show the most recent advice
        # and say how old it is, rather than leaving the section empty.
        previous = sorted(briefings.glob("*_advice.md"))
        if previous:
            when = datetime.strptime(previous[-1].name.removesuffix("_advice.md"), "%Y-%m-%d_%H%M%S")
            advice_md = (
                f"_Advice from {when.strftime('%d.%m.%Y %H:%M')} — the data above is newer._\n\n"
                + previous[-1].read_text()
            )
        else:
            advice_md = "_No advice generated yet._"

    data = json.loads(data_file.read_text())
    generated_at = datetime.strptime(stamp, "%Y-%m-%d_%H%M%S")
    out = project_root / "docs" / "index.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(build_site(data, advice_md, generated_at))
    return out


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    path = render_latest(root)
    print(f"Site rendered: {path.relative_to(root)}")
