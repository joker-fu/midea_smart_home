---
name: sync-upstream
description: Sync the upstream (Cyborg2017/midea_smart_home) into this fork's (joker-fu/midea_smart_home) staging branch by merging. Use whenever the user wants to pull in upstream updates, sync with upstream, merge upstream, update from Cyborg2017, or bring in the latest upstream features — even if they don't say "sync upstream" explicitly. Resolves conflicts to keep both the fork's custom features and the upstream's new functionality. Works regardless of what the upstream remote is named on the local clone.
---

# Sync Upstream → origin/staging

This fork (joker-fu/midea_smart_home) is based on upstream (Cyborg2017/midea_smart_home). Periodically the upstream gains new features and this skill merges them in while preserving the fork's custom additions.

## Remotes (resolved dynamically — NOT hardcoded)

The remote **names** differ across clones (the upstream might be `cy`, `upstream`, or anything else; this fork might be `origin` or something else). **Resolve them by URL substring at the start of every run**, so the skill works on any PC. The identities are fixed; only the names vary:

- **upstream** = the remote whose fetch URL contains `Cyborg2017/midea_smart_home`
- **fork** = the remote whose fetch URL contains `joker-fu/midea_smart_home`
- Working branch: `staging`, tracks `<fork>/staging`

Resolution uses the bundled helper `scripts/resolve_remote.sh`, which matches a remote by URL substring and exits non-zero if none matches. See step 1.

## Strategy: merge (NOT rebase)

Always use `git merge --no-ff "$UP/staging"` (where `$UP` is the resolved upstream remote). Reasons:
- This fork's history already uses merge-sync commits; merge needs no force-push and never rewrites `<fork>/staging`.
- The fork's custom features are pure-additive (new device model mappings + a dishwasher composite-key handler) and do not semantically conflict with upstream changes, so both sides coexist naturally after a merge.
- Rebase would replay the fork's commits onto upstream and require force-pushing, offering no benefit and risking history/tag breakage.

## Workflow

Run these steps in order. Stop and ask the user before `git push`.

### 1. Pre-flight checks & remote resolution
- **Working tree:** no changes to **tracked** files. `git status --porcelain` may list only `??`-prefixed lines (untracked files like `.agents/`, `.zcode/` are fine); any `M`/`A`/`D`/`R` line means stop and tell the user.
- **Branch:** `git branch --show-current` must be `staging`. If not, ask before switching.
- **Resolve remotes by URL** (do this every run — names vary per clone):
  ```
  SCRIPT="$(dirname "$0")/../scripts/resolve_remote.sh"   # or the absolute path to scripts/resolve_remote.sh
  UP="$(bash "$SCRIPT" Cyborg2017/midea_smart_home)"      # upstream remote name
  OR="$(bash "$SCRIPT" joker-fu/midea_smart_home)"        # fork remote name
  ```
  If either resolution fails (helper exits non-zero), the remote isn't configured on this clone — tell the user which one is missing (e.g. "no remote points at Cyborg2017/midea_smart_home; add one with `git remote add <name> <url>`") and stop. `$UP`/`$OR` are used in every later step.

### 2. Fetch both remotes
```
git fetch "$UP"
git fetch "$OR"
```
Only updates remote-tracking refs and `.git/objects`; never touches the working tree or `staging`. Fetching the fork remote up front lets step 3 detect immediately whether another clone already pushed (including an equivalent upstream sync), so a push rejection is prevented rather than discovered at push time.

### 3. Align with the fork remote, then analyze the divergence

**Align first** (before touching upstream), so you never build a merge on a stale base:
```
git log --oneline HEAD.."$OR/staging"                     # what the fork remote has that local lacks
```
- **Empty** → local staging is current with `$OR/staging`; continue below.
- **Non-empty** → another clone pushed. Integrate it now: `git merge --ff-only "$OR/staging"` when local has no unique commits; if local also has unpushed commits, `git merge "$OR/staging"` and report (stop and ask if it conflicts). Then re-check: if `HEAD.."$UP/staging"` is now empty, that push WAS this upstream sync — report "already synced by another clone" and stop. No tag, no merge.

Then analyze the upstream divergence:
```
git merge-base HEAD "$UP/staging"                         # common ancestor
git log --oneline HEAD.."$UP/staging"                     # what upstream has that we lack (upstream updates)
git log --oneline "$UP/staging"..HEAD                     # what we have that upstream lacks (our custom features)
```
Group the `HEAD.."$UP/staging"` commits by theme (new devices, features, fixes, CI/docs, version bumps) and report the summary to the user.

**If `HEAD.."$UP/staging"` is empty**, staging is already up to date — report that and stop. No tag, no merge.

### 4. Tag the pre-merge state (for rollback) — REQUIRED before EVERY merge
**Hard rule: every `git merge` in step 5 MUST be preceded by a fresh tag on the current HEAD. Never reuse an existing tag — even if HEAD points to the same commit an older tag already marks.** Each merge gets its own dedicated rollback point, and all historical tags are retained, so every previous sync boundary stays recoverable (`git reset --hard <older-tag>`).

The tag name is a local timestamp `YYYYMMDDHHMMSS`:
```
TAG="$(date +%Y%m%d%H%M%S)"
git tag -a "$TAG" -m "pre-sync-upstream snapshot before merging $UP/staging"
```
Record `$TAG` — it is the rollback target for this merge. The tag is created locally here and pushed to the remote in step 8 alongside the branch. If a tag with that name already exists (e.g. two merges in the same second), append `-2`, `-3`, … until `git tag` succeeds.

**Re-merge within the same run:** if you discover upstream advanced after a first merge attempt (re-running `git log --oneline HEAD.."$UP/staging"` is non-empty again) and you `git reset --hard` back to fold the new commits into a single fresh merge, you MUST create a **new** `$TAG` after the reset and before the re-merge — do not reuse the tag from the first attempt. Invariant: one fresh tag per merge attempt, all kept.

### 5. Merge
```
git merge --no-ff --no-commit "$UP/staging"
```
Expect conflicts (see next section). `--no-commit` lets you resolve and verify before committing.

**Pre-condition:** a fresh tag from step 4 must exist on HEAD before running this. If you `git reset --hard` and re-run this step (re-merge), create a new tag first — see step 4's "Re-merge within the same run".

### 6. Resolve conflicts

Read `references/conflict-resolution.md` for the full policy and a worked example. The core idea: **a sync is a union** — the result keeps both upstream's new functionality and the fork's custom features. For each conflict, understand what each side does, then keep what each side needs.

- **Hard rule — `.github/workflows/*.yml`**: always `git rm`. The fork doesn't use GitHub Actions; never keep upstream's CI, never ask.
- **Every other conflict**: resolve as a union. Identify which fork feature and which upstream feature are involved (the commit list from step 3 tells you the fork features; the `HEAD.."$UP/staging"` log tells you upstream's). Keep both. If genuinely mutually exclusive, prefer upstream's logic and re-apply the fork's addition on top. When you can't classify a conflict confidently, stop and ask the user.
- After editing, confirm **zero conflict markers** remain (`grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/` must be empty), then `git add` the files.

### 7. Verify (automated — no user action needed)
- **Syntax:** `python -m compileall -q custom_components/midea_smart_home` — must pass with no errors.
- **Fork features present:** for each fork-only feature identified in step 3 (the `"$UP/staging"..HEAD` commits), confirm it survived the merge. Pick representative tokens from each feature (a function name, a model number, a config key — whatever `git show <commit>` reveals) and grep the merged tree for them. All must be present. The point is to catch a silent drop where a conflict resolution or auto-merge accidentally removed a fork feature.
- **Upstream features present:** spot-check a couple of headline upstream additions from step 3 (e.g. a new device mapping file, a signature upstream function) to confirm they landed.
- **Workflows deleted:** `ls .github/workflows/` should fail (directory gone).

If any check fails, stop and report — do not commit.

### 8. Commit, then push (risk-tiered)
Commit the merge:
```
git commit --no-edit
```
Default merge message is fine (git will write "Merge remote-tracking branch '<upstream-name>/staging' into staging").

**Push policy is tiered by whether step 6 resolved any conflicts:**
- **Clean auto-merge (no conflicts in step 6) AND step 7 verification passed → push automatically, no confirmation.** Structural correctness is already verified and the rollback tag from step 4 covers the residual risk:
  ```
  git push "$OR" staging
  git push "$OR" "$TAG"
  ```
- **Any conflict was resolved in step 6 → STOP and ask the user before pushing.** Conflict resolution is where silent semantic regressions sneak in (the union looked right but the logic broke), and step 7's automated checks can't catch those — only a human glance at the resolution summary can. Present: the new HEAD, how many commits ahead of `$OR/staging`, `$TAG`, the conflict-resolution summary (what each conflict was and how it was resolved), and the verification results. Do not push until the user confirms; then run the two `git push` commands above.

Either way this is a normal (non-force) push. **If step 7 verification failed**, do not commit and do not push — see Rollback.

**If the branch push is still rejected** (rare race: another clone pushed after your step-2 fetch): `git fetch "$OR"` and repeat the step-3 alignment — if the remote now contains an equivalent sync (`git merge-base --is-ancestor "$UP/staging" "$OR/staging"` succeeds AND `git diff HEAD "$OR/staging"` is empty), `git reset --hard "$OR/staging"` and push just the tag; otherwise `git merge "$OR/staging"`, re-run the step 7 checks, and report to the user before pushing. Never force-push.

Regardless of path, report the outcome (see step 9 notification).

### 9. Review whether this skill needs updating
After the sync is complete (committed, and the push decision resolved — pushed or not), check whether the skill files still match reality, and update them if they drifted:

1. Re-read `.agents/skills/sync-upstream/SKILL.md` and `references/conflict-resolution.md`.
2. Look for these drift signals:
   - **Fork features changed:** did `git log "$UP/staging"..HEAD` (step 3) reveal fork-only commits the reference's "fork features hint" doesn't mention? If so, the hint is stale — update it to match the current set.
   - **New conflict pattern:** did a conflict appear that the decision procedure in the reference didn't cleanly handle? Add it as a worked example, or refine the procedure.
   - **Worked example drifted:** does the `extras.py` example in the reference still resemble the current code? If upstream changed that region again (or the fork's 0xE1 branch moved), update the example to current reality, or generalize it further. An example that contradicts the actual code misleads the next run.
   - **Hard rules moot:** did upstream stop shipping `.github/workflows/`? If the modify/delete conflict no longer occurs, note that in the reference.
3. If anything drifted, **propose the specific edits and ask the user before applying them**. If nothing drifted, say so and finish. This keeps the skill honest across syncs without accumulating stale detail.

## Rollback

The pre-merge tag (`$TAG` from step 4) is always the clean rollback target:
- **Before pushing the merge:** `git reset --hard "$TAG"` restores the pre-sync state. (The remote `$OR/staging` is untouched at this point too.)
- **After pushing:** the tagged commit is still reachable on the remote. Rollback options: `git revert -m 1 <merge-commit>` (safe, additive, recommended) or `git reset --hard "$TAG"` then force-push (only if you're certain no one else pulled — do not force-push shared history otherwise).
- The tag also lets you browse or diff the pre-sync state anytime: `git log "$TAG"..HEAD`, `git diff "$TAG"`.
- **Any prior sync's tag works too:** every sync keeps its own pre-merge tag (step 4 never reuses or deletes tags), so you can roll back across multiple syncs with `git reset --hard <older-tag>`, or compare two sync boundaries with `git diff <older-tag> <newer-tag>`.
