# Conflict Resolution Policy

Read this whenever the merge produces conflicts. The goal of every sync is to end up with **both** the upstream's new functionality **and** the fork's custom features — a union, not a choice between sides.

## Core principle: merge takes the UNION

Conflicts happen when two sides touch the same region of a file. They are almost never "pick one side." Resolve them by keeping what *each* side needs:

- Upstream changes represent features/fixes the user wants to receive.
- Fork changes represent custom features the user wants to keep.
- The resolved version must carry both. If you can't see how to carry both, stop and ask the user before deciding.

## What the fork's custom features are (derive fresh each time)

Do not trust a hardcoded list — the fork evolves too. Before resolving, derive the authoritative list of the fork's additions from history (`$UP` is the upstream remote name resolved in SKILL.md step 1):

```
git log --oneline "$UP/staging"..HEAD
```

Each commit there is a fork-only change whose intent must survive the merge. Read the commit messages and `git show --stat <commit>` to learn what each one touches and why. Keep this list in mind as you resolve conflicts.

As of the last sync the fork's additions were roughly: new device model mappings (T0xDB/DC/E1洗衣/干衣/洗碗机), a dishwasher (0xE1) composite-key control handler in `extras.py`, `in`/`not_in` entity conditions in `entity.py`, `command_on`/`command_off` switches in `switch.py`, a 60s `control_timeout` for 0xE1 in `device.py`, and the removal of `.github/workflows/`. Treat this as a hint, then confirm against the actual `git log` output.

## Decision procedure for any conflict

For each conflicted region:

1. **Understand both sides.** What does the `<<<<<<< HEAD` (fork) side do, and what does `>>>>>>> "$UP/staging"` (upstream) side do? Read enough surrounding code to know which feature each change belongs to. Don't just read the diff hunk — read the enclosing function/class so you understand intent.

2. **Classify the conflict:**
   - **Different features in the same spot** (most common here — e.g. fork added device model X, upstream added device model Y in the same mapping file): take the **union**, keep both. This is the default.
   - **Same feature, evolved on both sides**: **reconcile** — usually take upstream's version (it's the newer baseline) and re-apply the fork's specific delta on top.
   - **Genuinely mutually exclusive** (same line, opposite intent, cannot both be true): prefer upstream's logic, unless that removes a fork feature — in which case re-apply the fork's addition after. If you still can't decide, stop and describe both sides to the user.

3. **After editing:** confirm zero conflict markers remain (`grep -rn '<<<<<<<\|=======\|>>>>>>>' custom_components/` must be empty), then `git add` the file.

## Hard policies (never override, never ask)

- **`.github/workflows/*.yml`** (`auto_prerelease.yml`, `auto_version_bump.yml`, `validate.yml`): the fork intentionally does not use GitHub Actions. These appear as `CONFLICT (modify/delete)`. **Always `git rm` them.** Never keep upstream's CI changes, never ask the user.
- **Do not force-push.** This skill uses merge; rollback before pushing is `git reset --hard origin/staging`.

## Worked example: `extras.py` `prepare_control_data`

This illustrates the decision procedure — it is **not** a template to paste verbatim. Upstream will change and the exact lines will differ; apply the reasoning, not the code.

**What happened at the last sync:** the fork had added an `elif self.device_type == 0xE1:` branch (calls `self._prepare_dishwasher_control(...)`) inside `prepare_control_data`, right after the `if self.device_type == 0xD9:` block. Upstream independently rewrote the *body* of that same `if 0xD9:` block to detect multiple drum prefixes (`da_location`/`dc_location`). Git flagged a conflict because both touched adjacent lines.

**Classification:** *different features in the same spot* — upstream's multi-drum logic lives inside the D9 block; the fork's 0xE1 branch is a separate `elif`. They don't compete.

**Resolution:** keep upstream's D9 multi-drum logic intact, and re-add the fork's `elif self.device_type == 0xE1:` branch after it. The union.

**Generalizing:** if a future upstream change rewrites `prepare_control_data` again, don't try to reproduce last sync's exact text. Instead: locate where the fork's 0xE1 dishwasher branch belongs (it's a sibling `elif` to the other `device_type` checks), confirm upstream's changes to the rest of the method are kept, and re-insert the fork's 0xE1 branch. The invariant is "the fork's `_prepare_dishwasher_control` call path must remain reachable for 0xE1 devices" — however that's spelled in the current code.

## Same principle applies elsewhere

- **`extras.py` `apply_special_handling`**: upstream changed the signature (added `status=None`) and refactored the D9 branch; the fork added an `elif 0xE1:` arm. Usually auto-merges. If it conflicts, take upstream's signature + D9 changes, re-add the fork's 0xE1 `elif` arm in the same chain.
- **`device_mapping/*.py` and `translations/*.json`**: fork and upstream both add model entries / translation keys to the same dicts. These should merge cleanly as additive dict entries. If two changes touch the exact same key, keep both values if they're different keys; if the same key got different values, prefer upstream and only override if the fork's value is load-bearing for a fork-only device.
- **`device.py` / `entity.py` / `switch.py` / `select.py`**: the fork's changes here are small, localized additions (a timeout line, a condition branch, a switch feature). Keep upstream's broader refactors and re-apply the fork's localized additions on top.

When a conflict doesn't fit any of these and you can't confidently classify it, stop and describe both sides to the user before resolving.
