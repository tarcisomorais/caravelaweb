# Contributing

Thank you for helping improve CaravelaWeb.

## Before starting

- Read the [Code of Conduct](CODE_OF_CONDUCT.md).
- Search existing issues before opening a new one.
- Use a security report, not a public issue, for vulnerabilities.
- Keep changes inside the repository-root skill boundary. Do not add package
  distribution scaffolding, a public Python SDK, or duplicate runtime under a
  nested skill directory. Plugin manifests and thin discovery adapters publish
  the repository root without adding another runtime layer.

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

## Where a rule lives

Callers reliably read `SKILL.md` and little else. Before adding or moving a
rule:

- Anything required for correct behavior on every ordinary call must be in
  `SKILL.md`, be enforced by code, or be surfaced by tool output.
- `references/` is not reliably read. It holds rationale, examples, and
  detail needed only on a path the model knows it is on, such as building a
  Discovery payload.
- Prefer code, then tool output, then `SKILL.md`.
- `SKILL.md` has a hard word budget enforced by tests. Pay for every addition
  with a cut, and prefer a short copyable form (an exact command, a table) to
  a prohibition inside a long paragraph.

## Pull requests

- Keep one coherent change per pull request.
- Explain user-visible behavior and safety implications.
- Update public English documentation when the supported surface changes.
- Do not regenerate frozen characterization output merely to make a test pass.
- Confirm that repository history and tracked files contain no secrets or
  private data.
- Allow CI to complete on Linux and native Windows.

Contributions submitted to this repository are licensed under Apache-2.0.
