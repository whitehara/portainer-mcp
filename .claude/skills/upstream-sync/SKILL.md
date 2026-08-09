---
name: upstream-sync
description: How to sync this fork (whitehara/portainer-mcp) with its upstream (portainer/portainer-mcp) — checking drift, predicting merge conflicts before touching the working tree, reconciling the fork's hand-written patches against upstream's `server.py`, and re-tagging for a fork release. Trigger this skill whenever the user mentions syncing with upstream, merging upstream changes, resolving an `upstream-drift` GitHub issue, checking how far behind upstream this fork is, or any phrasing like "let's catch up with upstream" — also consult it before touching `server.py`, `.github/workflows/release-*.yml`, or `docs/release.md`/`docs/versioning.md` if the change is upstream-drift-related rather than a fork-local fix.
---

# upstream-sync

This fork tracks `portainer/portainer-mcp` (the Python/FastMCP rewrite this fork itself
branched from at `1351ada`) via the `upstream` git remote
(`https://github.com/portainer/portainer-mcp`). Everything this fork adds on top is
enumerated in [`../../FORK-DELTA.md`](../../FORK-DELTA.md) — read that file before starting
a sync so you know exactly what has to survive the merge.

A weekly [`upstream-drift.yml`](../../../.github/workflows/upstream-drift.yml) workflow
opens/updates a GitHub issue labeled `upstream-drift` when `upstream/main` pulls ahead. That
issue is the usual trigger for running this skill; `git rev-list --count HEAD..upstream/main`
by hand works too.

## 1. Check drift and predict conflicts before touching anything

```bash
git fetch upstream
git log --oneline HEAD..upstream/main        # what's coming in
git diff --stat HEAD..upstream/main           # which files, roughly how much
```

Then predict the merge **without touching the working tree**:

```bash
git merge-tree --write-tree HEAD upstream/main
```

This lists exactly which files will conflict, with no side effects — safe to run
repeatedly. In the 2026-08-09 sync, this correctly predicted the only two conflicting files
(`pyproject.toml`, `src/portainer_mcp/server.py`) out of 28 incoming commits, which is what
made the rest of the merge low-risk.

Cross-reference the predicted conflict files against `FORK-DELTA.md`: any file listed there
is a file this fork has deliberately diverged on, so a conflict there is expected and the
resolution should preserve the fork's patch, not discard it. A conflict in a file **not**
listed in `FORK-DELTA.md` is a signal that something changed on the fork side outside the
tracked deltas — investigate before resolving.

## 2. Merge (never rebase or cherry-pick)

```bash
git checkout -b chore/upstream-sync-<upstream-version> main
git merge upstream/main
git config rerere.enabled true   # do this once; makes repeat syncs cheaper
```

Merge, not rebase or cherry-pick:

- **Rebase** rewrites commits already tagged and pushed to `origin` (the fork's own
  `hl-*` tags point at specific commits) — rewriting them breaks those tags and forces
  a `--force` push, which this repo's workflow avoids.
- **Cherry-pick** means resolving each upstream commit's conflicts individually — for a
  28-commit drift that's 28 chances to conflict instead of one merge's worth, and the spec
  YAML alone can be thousands of lines of diff per commit.
- **Merge + `rerere`** means a conflict resolution you've made once (e.g. how to reconcile
  `server.py`'s fork patches against upstream's new `build_server()`) gets replayed
  automatically on the next sync if the same lines conflict again.

## 3. Resolve `pyproject.toml` — always take upstream's side

Per `FORK-DELTA.md`'s invariant, `version` and all dependency/build config in
`pyproject.toml` mirror upstream exactly:

```bash
git checkout --theirs pyproject.toml
uv lock
```

The fork's own release identity lives entirely in git tags (`hl-<upstream-version>-<fork-rev>`),
never in this file.

## 4. Resolve `server.py` — reapply the fork's 4 patches onto upstream's new base

Take upstream's `server.py` as the base, then reapply — in this order, matching
`FORK-DELTA.md`'s entry for this file:

1. Add `swarm` to the `from portainer_mcp import (...)` block.
2. Restore the `_TOOL_NAME_REMAP` dict (see step 6 below for updating its contents).
3. Restore the one-line remap application inside `_annotate_read_only()`.
4. Insert `swarm.register(mcp, client, read_only=read_only)` immediately after
   `proxy.register(...)`, and **before** `guidance.register(...)` and
   `mcp.add_transform(shaping.SelectArgTransform())` — the select-universality assertion at
   the end of `build_server()` requires every registered tool to have `select` wired in
   before that transform runs.

Do not assume any 5th patch is needed (e.g. auth wiring) without checking current phase
decisions — the 2026-08-09 sync initially planned for conditional patches here but they
turned out to be unnecessary because upstream's per-user passthrough hooks into the shared
`httpx.AsyncClient` via `event_hooks`, so `swarm.py`/`proxy.py` inherit it automatically as
long as they're registered with that same client instance. Verify this assumption still
holds by reading `src/portainer_mcp/passthrough.py`'s `inject_api_key()` and confirming it's
still wired as a client-level request hook, not something requiring explicit per-tool calls.

## 5. Auth/TLS posture — re-verify, don't assume last sync's answer still holds

Upstream's HTTP auth and TLS posture requirements (`auth_posture.py`, `tls.py`) are two
**separate, both-mandatory** axes — this was missed in the first pass of the 2026-08-09 sync
and only caught during production deploy. Before deploying a synced version, confirm:

- **Auth posture**: exactly one of `PORTAINER_MCP_AUTH_TOKEN` (gate token) or
  `PORTAINER_MCP_TRUST_PROXY_AUTH=1` (trust-proxy) must be set. This fork's production
  deployment uses trust-proxy, because the front-door reverse proxy
  (`mcp-auth-proxy`) doesn't forward the `Authorization` header by default.
- **TLS posture**: exactly one of a server-held cert, `PORTAINER_MCP_TRUST_PROXY_TLS=1` +
  `PORTAINER_MCP_FORWARDED_ALLOW_IPS`, or the plaintext opt-out must be set on any
  non-loopback bind.

Both of these are upstream env vars, not fork patches — re-verify the *values* (proxy CIDR,
whether the front-door proxy still strips `Authorization`) rather than the *mechanism*,
since a homelab network topology change could invalidate them without any code changing.

## 6. Reconcile `_TOOL_NAME_REMAP` against the new spec

Every sync that bumps `src/portainer_mcp/data/portainer-patched.yaml` can add or remove
operations whose `operationId` exceeds Cloudflare's 40-char tool name limit. Diff the spec's
`operationId` entries between the old and new fork tag to find what changed:

```bash
git diff <previous-fork-tag>..HEAD -- src/portainer_mcp/data/portainer-patched.yaml \
  | grep -E '^[+-]\s+operationId:'
```

For each newly-added long name, add a `_TOOL_NAME_REMAP` entry (≤40 chars, no collision with
an existing tool name, name still recognizable as the same operation). For each name that no
longer appears in the spec (renamed or removed upstream), delete its remap entry — a stale
entry pointing at a name the spec no longer generates is silent dead weight, not a bug, but
clean it up anyway. `tests/test_tool_names.py` will fail loudly if a new long name is missed;
it will not warn about a stale removed entry, so check by hand.

Also check `profiles.py` for new tags in the incoming spec that should join the default
profile set — see [`../../../docs/profiles.md`](../../../docs/profiles.md).

## 7. Test, review, verify (mirrors the standard pre-commit flow)

```bash
uv sync
uv run pytest
uv build && unzip -l dist/*.whl | grep SKILL.md   # confirms the wheel packaging still works
docker build -t portainer-mcp:sync-test .          # needs registry egress; may not work in a sandboxed agent
```

Run the `reviewer` subagent before committing, same as any other change. If `docker build`
can't run in the current environment (e.g. no `ghcr.io` egress), defer that check to local
verification or the next CI-driven release build — don't skip it silently, note it as
pending.

## 8. Tag and deploy

Follow the fork's own tag convention (`docs/release.md`'s "Fork release notes" section):
`hl-<upstream-version>-<fork-rev>`. Pushing that tag triggers
[`release-docker.yml`](../../../.github/workflows/release-docker.yml), which publishes to
GHCR. Production deployment steps (env var changes, rollback recording) are a separate
concern from the code sync — if a `docs/phases/` or `.claude/phases/` deploy runbook exists
for the current sync, follow it; otherwise treat env var changes with the same care as any
other production config change (record the rollback point first).

## 9. Close the loop

Update `FORK-DELTA.md`'s "最終確認日" column for entries touched during the sync, and update
`.claude/ROADMAP.md` / phase docs with the sync's outcome. If an `upstream-drift` issue
triggered this sync, it closes automatically the next time the drift workflow runs and finds
zero commits behind — no manual close needed unless you want to close it immediately.
