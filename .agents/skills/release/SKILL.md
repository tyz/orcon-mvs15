---
name: Release
description: Use when preparing, tagging or publishing an orcon_mvs15 release, including the version bump, HACS minimum version, release gate, PR and GitHub release.
---

# Releasing orcon_mvs15

## Permission gates

* The user merges the release PR. Never merge your own PR unless explicitly asked.
* Do not push the tag or create the GitHub release until the PR is merged and the
  user gives explicit permission.
* Do not force-push or rewrite a published tag.

## Version and metadata

* The version lives in `custom_components/orcon_mvs15/manifest.json`. HACS reads
  it, so the git tag must be `v<version>` and match it exactly.
* `hacs.json` declares the minimum Home Assistant version. Raise it only when the
  integration actually needs a newer Home Assistant.
* Keep `quality_scale.yaml` truthful; a release does not turn a `todo` rule into
  `done`.
* Update `README.md` and `docs/protocol.md` when behaviour or known limitations
  change. There is no `CHANGELOG.md`; the GitHub release notes are the changelog.

## Checklist

1. Branch from a clean, up-to-date `master` and bump the manifest version.
2. Run the full gate and require it to pass:

   ```sh
   pre-commit run --all-files
   pre-commit run --all-files
   mypy custom_components/
   python -m pytest -q tests/
   python scripts/check_coverage.py
   python -m compileall -q custom_components/orcon_mvs15
   ```

3. Open one release PR describing the changes and the known limitations. Wait for
   CI to pass and for the user to merge it.
4. After explicit permission, pull `master`, confirm the manifest version, then
   create and push an annotated tag:

   ```sh
   git pull
   grep '"version"' custom_components/orcon_mvs15/manifest.json
   git tag -a vX.Y.Z -m "Release X.Y.Z"
   git push origin vX.Y.Z
   ```

   If SSH is unavailable, push the tag over HTTPS with the authenticated `gh`
   credential helper. Do not change the stored remote.
5. Create the GitHub release with notes covering highlights, fixes, compatibility,
   configuration changes and known limitations:

   ```sh
   gh release create vX.Y.Z --title "X.Y.Z" \
     --notes-file /tmp/opencode/release-notes-X.Y.Z.md --verify-tag
   ```

6. Verify the tag points at the merged commit and the release is published, not a
   draft:

   ```sh
   git rev-parse vX.Y.Z^{commit}
   gh release view vX.Y.Z --json tagName,isDraft,isPrerelease,publishedAt
   ```

## Notes

* A patch release fixes behaviour without configuration changes; a minor release
  adds backwards-compatible functionality. Do not call a release major without a
  breaking change.
* HACS installs from the tag, so a missing or mismatched tag means no update.
* Keep release notes user-facing; internal milestone names do not belong in them.
