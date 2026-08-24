#!/bin/zsh
# Daily Kickbase pipeline: pull latest code, fetch data, get advice, rebuild site, push.
# Run by launchd (com.anton.kickbase-advisor) from the automation clone in
# ~/kickbase-advisor-auto — launchd cannot read ~/Documents (macOS TCC).
set -e

# launchd starts with a minimal PATH; make brew/uv/claude/git resolvable.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin"

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT"

echo "=== run $(date '+%Y-%m-%d %H:%M:%S') in $PROJECT ==="
git pull --rebase -q
uv run scripts/advise.py

if ! git diff --quiet docs/; then
  git add docs/
  git commit -m "Daily update $(date '+%Y-%m-%d')"
  git push
  echo "pushed site update"
else
  echo "no site changes"
fi
