# Release Tickwork

v0.1.0 was published on 2026-10-10. The configured Trusted Publisher uses:

| PyPI field | Value |
| --- | --- |
| Project name | tickwork-cli |
| GitHub owner | Kepler452Byte |
| Repository | tickwork-cli |
| Workflow filename | publish.yml |
| Environment | pypi |

The GitHub environment is `pypi`. The owner has configured PyPI; no API token needs to be shared. See [PyPI Trusted Publisher documentation](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

For each subsequent release, with publication authorization:

1. Verify the source and its three-platform CI/native evidence. Keep version, release notes and wheel metadata consistent. Never claim authenticated AI execution on platforms where credentials have not been tested.
2. Create and push an annotated `v<version>` tag on the verified commit. Once pushed, its object and target are immutable; never delete/recreate or force-update it.
3. Run `uv run python scripts/release_check.py --tag v<version>` on the clean tagged checkout.
4. Dispatch **publish** on GitHub Actions with `tag=v<version>`. This checks the immutable tag, tests all three platforms (including actual scheduled triggers), builds source/wheel distributions and only then uploads via OIDC.
5. Verify PyPI files/version, install the actual published package in isolation and test help/version. Publish the GitHub release and update the Vault release checklist/date only after successful upload.

Pushing source does not upload to PyPI. The publish workflow only runs on manual dispatch; preparing it does not publish a release. For a failed upload retry the same immutable tag, inspect existing PyPI files and preserve release identity.

Initial release evidence: [publish workflow](https://github.com/Kepler452Byte/tickwork-cli/actions/runs/38038458653), [PyPI](https://pypi.org/project/tickwork-cli/0.1.0/), [GitHub Release](https://github.com/Kepler452Byte/tickwork-cli/releases/tag/v0.1.0). Immutable tag object: `2916e2c024281acf81d50576c6e91ea56d050390`; target: `ccf392a60cd31419c64b97ed28332fdf68120247`.
