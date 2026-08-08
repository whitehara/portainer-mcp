# Releasing

> **Fork note**: everything below except "Fork release notes"
> describes upstream's PyPI release process (`release.yml` /
> `release-test.yml`), which this fork doesn't run — those workflow files
> don't exist here. This fork's actual release process (GHCR image, `hl-*`
> tags) is documented in the "Fork release notes" section.

The release workflow at
[`../.github/workflows/release.yml`](../.github/workflows/release.yml) builds
the wheel and publishes to PyPI on every tag push matching `X.Y.Z`. Auth is
OIDC via PyPI Trusted Publishing — no API tokens or repo secrets.

## One-time setup

A Pending Publisher must exist on PyPI **and** TestPyPI. Do once per
distribution name:

- **pypi.org → Account → Publishing → Add pending publisher**
  - Repository: `portainer/portainer-mcp`
  - Workflow: `release.yml`
  - Environment: leave blank (any)
- **test.pypi.org → Account → Publishing → Add pending publisher**
  - Repository: `portainer/portainer-mcp`
  - Workflow: `release-test.yml`
  - Environment: leave blank (any)

No GitHub secrets, no environments, no token rotation. If you ever rename the
distribution, register new Pending Publishers under the new name.

### Fork release notes (whitehara/portainer-mcp)

This fork does **not** publish to PyPI or Docker Hub — the `release.yml` /
`release-test.yml` workflows referenced above, and the Docker Hub section that
used to live here, don't apply. The only release artifact is the container
image, published to GHCR by
[`release-docker.yml`](../.github/workflows/release-docker.yml) via
`GITHUB_TOKEN` (no separate registry credentials needed).

**Tag convention**: `hl-<upstream-version>-<fork-rev>` (e.g. `hl-2.44.0-1`),
never bare `X.Y.Z` — this fork tracks `upstream/main`
(`https://github.com/portainer/portainer-mcp`) and upstream also tags releases
as bare `X.Y.Z`, so a fork tag in the same namespace would collide with (or
even overwrite) an upstream tag pointing at a different commit. `<fork-rev>`
increments per fork-only release against the same upstream version.

**`pyproject.toml`'s `version` field always mirrors the upstream version it
was merged from — this fork never edits it independently.** Bump it only as
part of merging a newer `upstream/main` (see the `upstream-sync` skill), never
to cut a fork-only release; fork-only changes get a new `<fork-rev>` instead.

Image tags emitted per push of `hl-<upstream-version>-<fork-rev>`:
`:<upstream-version>-<fork-rev>` (e.g. `:2.44.0-1`, pins the exact fork
build), `:<upstream-version>` (e.g. `:2.44.0`, floats to the latest fork
revision for that upstream version), and `:latest`.

## Dry run on TestPyPI

Before tagging a real release, do a dry run against TestPyPI to confirm the
build and OIDC publish path work end-to-end:

1. Bump `version` in [`../pyproject.toml`](../pyproject.toml) and commit.
2. **GitHub → Actions → Release (TestPyPI) → Run workflow** on the branch
   carrying the bump.
3. The workflow ([`release-test.yml`](../.github/workflows/release-test.yml))
   runs tests, builds, and publishes to TestPyPI.
4. Verify at `https://test.pypi.org/project/mcp-portainer/X.Y.Z/`.

TestPyPI doesn't allow re-uploading the same version (separate from PyPI's
copy of the rule). If the dry run finds a problem, fix it and bump to
`X.Y.Z.post1` for the next TestPyPI attempt — PyPI itself stays free to
receive plain `X.Y.Z`.

## Cutting a release

1. Decide the version per [`versioning.md`](versioning.md).
2. Bump `version` in [`../pyproject.toml`](../pyproject.toml).
3. `uv lock` to refresh [`../uv.lock`](../uv.lock).
4. Move the `[Unreleased]` block in [`../CHANGELOG.md`](../CHANGELOG.md) under
   a new `[X.Y.Z] — YYYY-MM-DD` heading; leave a fresh empty `[Unreleased]`
   block on top.
5. Commit: `Release X.Y.Z`.
6. Tag and push:
   ```bash
   git tag X.Y.Z
   git push origin X.Y.Z
   ```
7. The workflow verifies the tag matches `pyproject.version`, runs tests,
   builds, and publishes.
8. Once green, the new version is live at
   `https://pypi.org/project/mcp-portainer/X.Y.Z/`.

## Recovery

- **Tag/version mismatch:** workflow fails fast. Delete the tag locally and
  remotely (`git tag -d X.Y.Z && git push --delete origin X.Y.Z`), fix the
  version, retag.
- **PyPI rejects upload (version exists):** PyPI doesn't allow re-uploading
  the same version, even after a yank. Bump the patch and retag.
- **Trusted Publishing OIDC failure:** the Pending Publisher's repo /
  workflow values must match exactly (case-sensitive).
