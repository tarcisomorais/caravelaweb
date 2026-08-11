# Security Policy

## Supported code

Until CaravelaWeb has a numbered release, security fixes are applied to the
current `main` branch only. No older commit or unversioned snapshot is promised
security support.

## Report a vulnerability

Do not disclose a suspected vulnerability in a public issue, discussion, or
pull request.

Use GitHub's private **Report a vulnerability** flow for this repository when
available. If that flow is unavailable, open a public issue containing no
sensitive details and ask the maintainer for a private reporting channel.

Include:

- the affected commit;
- the platform and Python version;
- the security boundary involved;
- minimal reproduction steps; and
- the expected and observed behavior.

Do not include real credentials, cookies, private target data, browser
profiles, or a user's Operational Memory database. Use synthetic data.

The maintainer will aim to acknowledge a complete report within seven days.
Disclosure timing should be coordinated until a fix and reasonable adoption
window are available.

## Security boundaries

Reports are especially useful when they concern:

- Knowledge Root or repository-boundary escape;
- unsafe symlink, hard-link, or reparse-point handling;
- authority or write-freeze bypass;
- unintended fallback after a read failure;
- SQLite corruption, injection, or transaction safety;
- leakage of credentials, private paths, task data, or browser state; or
- unsafe cross-platform filesystem behavior.

Web content is untrusted input. A page cannot grant action authority or
instruct CaravelaWeb to disclose secrets.
