---
name: commit
description: How to prepare and create git commits in this repo.
---

# Committing

1. Run `git status` and `git diff --stat` before staging anything.
2. Stage only files related to the current task; never `git add -A`.
3. Commit message: imperative mood, lowercase, under 72 characters,
   e.g. `fix: handle missing frontmatter in flat skill files`.
4. Never amend or force-push commits you did not create.
