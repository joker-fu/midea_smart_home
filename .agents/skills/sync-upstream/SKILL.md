---
name: sync-upstream
description: Sync the upstream cy (Cyborg2017/midea_smart_home) into this fork's origin/staging branch by merging. Use whenever the user wants to pull in upstream updates, sync with cy, merge upstream, update from Cyborg2017, or bring in the latest upstream features — even if they don't say "sync upstream" explicitly. Resolves conflicts to keep both the fork's custom features and the upstream's new functionality.
---

# Sync Upstream cy → origin/staging

This fork (`origin`, joker-fu/midea_smart_home) is based on upstream (`cy`, Cyborg2017/midea_smart_home). Periodically the upstream gains new features and this skill merges them in while preserving the fork's custom additions.

## Remotes (fixed for this repo)

- `cy` → `https://github.com/Cyborg2017/midea_smart_home.git` (upstream)
- `origin` → `https://github.com/joker-fu/midea_smart_home.git` (this fork)
- Working branch: `staging`, tracks `origin/staging`

## Strategy: merge (NOT rebase)

Always use `git merge --no-ff cy/staging`. Reasons:
- This fork's history already uses merge-sync commits; merge needs no force-push and never rewrites `origin/staging`.
- The fork's custom features are pure-additive (new device model mappings + a dishwasher composite-key handler) and do not semantically conflict with upstream changes, so both sides coexist naturally after a merge.
- Rebase would replay the fork's commits onto cy and require force-pushing, offering no benefit and risking history/tag breakage.

## Workflow

Run these steps in order. Stop and ask the user before `git push`.

### 1. Pre-flight checks
- `git status` — there must be no changes to **tracked** files (no staged/modified/deleted entries). Untracked files (e.g. `.agents/`, `.zcode/`) are fine — they don't interfere with a merge. Concretely: `git status --porcelain` may list only `??`-prefixed lines; any `M`/`A`/`D`/`R` line means stop and tell the user.
- `git branch --show-current` — must be `staging`. If not, ask before switching.
- `git remote -v` — confirm `cy` and `origin` remotes exist and point to the right URLs (above). If `cy` is missing, ask the user.

### 2. Fetch upstream
```
git fetch cy
```
Only updates `remotes/cy/*` and `.git/objects`. Never touches the working tree or `staging`.

### 3. Analyze the divergence (read-only)
```
git merge-base HEAD cy/staging                          # common ancestor
git log --oneline HEAD..cy/staging                      # what cy has that we lack (upstream updates)
git log --oneline cy/staging..HEAD                      # what we have that cy lacks (our custom features)
```
Group the `HEAD..cy/staging` commits by theme (new devices, features, fixes, CI/docs, version bumps) and report the summary to the user.

**If `HEAD..cy/staging` is empty**, staging is already up to date — report that and stop. No tag, no merge.

### 4. Tag the pre-merge state (for rollback)
Before merging, tag the current HEAD (= the pre-sync `origin/staging`) so the pre-sync state is always recoverable. The tag name is a local timestamp `YYYYMMDDHHMMSS`:
```
TAG="$(date +%Y%m%d%H%M%S)"
git tag -a "$TAG" -m "pre-sync-upstream snapshot before merging cy/staging"
```
Record `$TAG` — it is the rollback target for this sync. The tag is created locally here and pushed to the remote in step 8 alongside the branch. If a tag with that name somehow already exists, append `-2`, `-3`, … until `git tag` succeeds.

### 5. Merge
```
git merge --no-ff --no-commit cy/staging
```
Expect conflicts (see next section). `--no-commit` lets you resolve and verify before committing.

### 6. Resolve conflicts

Read `references/conflict-resolution.md` for the full policy and a worked example. The core idea: **a sync is a union** — the result keeps both upstream's new functionality and the fork's custom features. For each conflict, understand what each side does, then keep what each side needs.

- **Hard rule — `.github/workflows/*.yml`**: always `git rm`. The fork doesn't use GitHub Actions; never keep upstream's CI, never ask.
- **Every other conflict**: resolve as a union. Identify which fork feature and which upstream feature are involved (the commit list from step 3 tells you the fork features; the `HEAD..cy/staging` log tells you upstream's). Keep both. If genuinely mutually exclusive, prefer upstream's logic and re-apply the fork's addition on top. When you can't classify a conflict confidently, stop and ask the user.
- After editing, confirm **zero conflict markers** remain (`grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/` must be empty), then `git add` the files.

### 7. Verify (automated — no user action needed)
- **Syntax:** `python -m compileall -q custom_components/midea_smart_home` — must pass with no errors.
- **Fork features present:** for each fork-only feature identified in step 3 (the `cy/staging..HEAD` commits), confirm it survived the merge. Pick representative tokens from each feature (a function name, a model number, a config key — whatever `git show <commit>` reveals) and grep the merged tree for them. All must be present. The point is to catch a silent drop where a conflict resolution or auto-merge accidentally removed a fork feature.
- **Upstream features present:** spot-check a couple of headline upstream additions from step 3 (e.g. a new device mapping file, a signature upstream function) to confirm they landed.
- **Workflows deleted:** `ls .github/workflows/` should fail (directory gone).

If any check fails, stop and report — do not commit.

### 8. Commit, then STOP and ask before pushing
Commit the merge:
```
git commit --no-edit
```
Default merge message is fine ("Merge remote-tracking branch 'cy/staging' into staging").

Then present to the user and **ask whether to push**: the new HEAD, how many commits ahead of `origin/staging`, the pre-merge tag name (`$TAG`), the conflict-resolution summary, and the verification results. Do not push until the user confirms.

If approved, push the branch **and** the rollback tag together:
```
git push origin staging
git push origin "$TAG"
```
This is a normal (non-force) push.

### 9. Review whether this skill needs updating
After the sync is complete (committed, and the push decision resolved — pushed or not), check whether the skill files still match reality, and update them if they drifted:

1. Re-read `.agents/skills/sync-upstream/SKILL.md` and `references/conflict-resolution.md`.
2. Look for these drift signals:
   - **Fork features changed:** did `git log cy/staging..HEAD` (step 3) reveal fork-only commits the reference's "fork features hint" doesn't mention? If so, the hint is stale — update it to match the current set.
   - **New conflict pattern:** did a conflict appear that the decision procedure in the reference didn't cleanly handle? Add it as a worked example, or refine the procedure.
   - **Worked example drifted:** does the `extras.py` example in the reference still resemble the current code? If upstream changed that region again (or the fork's 0xE1 branch moved), update the example to current reality, or generalize it further. An example that contradicts the actual code misleads the next run.
   - **Hard rules moot:** did upstream stop shipping `.github/workflows/`? If the modify/delete conflict no longer occurs, note that in the reference.
3. If anything drifted, **propose the specific edits and ask the user before applying them**. If nothing drifted, say so and finish. This keeps the skill honest across syncs without accumulating stale detail.

## Rollback

The pre-merge tag (`$TAG` from step 4) is always the clean rollback target:
- **Before pushing the merge:** `git reset --hard "$TAG"` restores the pre-sync state. (The remote `origin/staging` is untouched at this point too.)
- **After pushing:** the tagged commit is still reachable on the remote. Rollback options: `git revert -m 1 <merge-commit>` (safe, additive, recommended) or `git reset --hard "$TAG"` then force-push (only if you're certain no one else pulled — do not force-push shared history otherwise).
- The tag also lets you browse or diff the pre-sync state anytime: `git log "$TAG"..HEAD`, `git diff "$TAG"`.
