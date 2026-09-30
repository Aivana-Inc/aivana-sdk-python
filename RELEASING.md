# Releasing

Publishing a GitHub Release publishes the `aivana` package to PyPI. No PyPI
token is involved: PyPI trusts this repository's `publish.yml` directly
(trusted publishing), and every release carries signed attestations of how it
was built.

## 1. Bump the version, in a pull request

PyPI never accepts the same version twice, so every release starts with a bump:
change `version` in `pyproject.toml`. It's the only place, because the package
and the `aivana` command read their version from the installed metadata. Merge
the pull request once CI is green.

## 2. Publish a GitHub Release

**Releases → Draft a new release**:

- **Tag:** `v` followed by the new version, for example `v0.2.3`, created on
  publish.
- **Target:** `main`.
- Optionally, **Generate release notes** to list the merged pull requests.

Then **Publish release**.

## 3. Watch the run

Actions → **Publish to PyPI**. The job:

1. runs the tests;
2. checks that the tag matches the version in `pyproject.toml`, and stops
   before building anything if it doesn't;
3. builds the wheel and sdist and checks them with `twine`;
4. uploads them to PyPI, with attestations.

If it fails, fix the cause and click **Re-run failed jobs**: files that are
already on PyPI are skipped, not uploaded twice. If the fix needs a code
change, merge it and release the next patch version instead.

## Keeping the two CLIs in step

`conformance/cli.json` is a byte-identical copy of the suite in
[aivana-sdk-node](https://github.com/Aivana-Inc/aivana-sdk-node). A change to
how the `aivana` command behaves updates the suite in both repositories, and
both SDKs are released so the two commands keep behaving the same.

## Manual fallback

`publish.sh` uploads from a laptop with a PyPI API token. It skips the checks
above, so use it only if GitHub Actions itself is unavailable.
