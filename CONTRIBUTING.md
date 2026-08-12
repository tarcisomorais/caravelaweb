# Contributing

Thank you for helping improve CaravelaWeb.

## Before starting

- Read the [Code of Conduct](CODE_OF_CONDUCT.md).
- Search existing issues before opening a new one.
- Use a security report, not a public issue, for vulnerabilities.
- Keep changes inside the repository-root skill boundary. Do not add package
  distribution scaffolding, a public Python SDK, or a nested skill directory.
  The `.claude-plugin/` manifests are the one exception: they publish the
  repository root itself as a Claude Code plugin and add no runtime layer.

For behavior changes, describe the target capability, current result,
expected result, platform, Python version, and a minimal synthetic
reproduction. Never attach a real Knowledge Root, credential, cookie, browser
profile, or private target corpus.

## Development

Use Python 3.11 or newer. The project intentionally uses the standard library
and has no package installation step.

Run the full deterministic suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Before submitting a pull request:

```bash
git diff --check
python3 scripts/preflight --help
```

Add the smallest regression test that proves a non-trivial behavior change.
Preserve Linux and native-Windows behavior, UTF-8 output, SQLite safety,
fail-closed authority, and the public CLI contract.

## Pull requests

- Keep one coherent change per pull request.
- Explain user-visible behavior and safety implications.
- Update public English documentation when the supported surface changes.
- Do not regenerate frozen characterization output merely to make a test pass.
- Confirm that repository history and tracked files contain no secrets or
  private data.
- Allow CI to complete on Linux and native Windows.

Contributions submitted to this repository are licensed under Apache-2.0.
