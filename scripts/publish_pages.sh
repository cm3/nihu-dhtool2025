#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKTREE="${TMPDIR:-/tmp}/nihu-dhtool2025-gh-pages"
MESSAGE="${1:-Publish Quarto site}"

cd "$ROOT"

current_branch="$(git branch --show-current)"
if [[ "$current_branch" != "main" ]]; then
  echo "ERROR: run this script from the main branch; current branch is '$current_branch'" >&2
  exit 1
fi

if ! git diff --quiet -- _quarto.yml index.qmd pair_relation_viewer.html data/entity_opinions.json data/pair_relations.json; then
  echo "ERROR: commit or stash source changes before publishing Pages." >&2
  echo "       This keeps gh-pages tied to a source commit." >&2
  exit 1
fi

rm -rf _site
quarto render
touch _site/.nojekyll

if git worktree list --porcelain | grep -q "^worktree $WORKTREE$"; then
  git worktree remove --force "$WORKTREE"
elif [[ -e "$WORKTREE" ]]; then
  echo "ERROR: $WORKTREE exists but is not this repository's worktree." >&2
  echo "       Remove it manually or set TMPDIR to another location." >&2
  exit 1
fi

if git show-ref --verify --quiet refs/heads/gh-pages; then
  git worktree add "$WORKTREE" gh-pages
else
  git worktree add --detach "$WORKTREE" HEAD
  git -C "$WORKTREE" switch --orphan gh-pages
fi

find "$WORKTREE" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$ROOT/_site/." "$WORKTREE/"

git -C "$WORKTREE" add -A
if git -C "$WORKTREE" diff --cached --quiet; then
  echo "No Pages changes to commit."
else
  git -C "$WORKTREE" commit -m "$MESSAGE"
fi

git worktree remove "$WORKTREE"

echo
echo "Pages branch is ready. Push with:"
echo "  git push origin main"
echo "  git push origin gh-pages"
