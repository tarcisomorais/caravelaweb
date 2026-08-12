# CaravelaWeb

[![CI](https://github.com/tarcisomorais/caravelaweb/actions/workflows/ci.yml/badge.svg)](https://github.com/tarcisomorais/caravelaweb/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

CaravelaWeb is a skill that lets an AI agent work on live websites carefully.
It remembers what already worked for a site, reuses that instead of guessing
again, and always stops before authentication, payment, submission, or any
other action you did not ask for.

## Before you install

CaravelaWeb needs Python 3.11 or newer. Check it once:

- Windows: `py --version`
- Linux, WSL2, and macOS: `python3 --version`

If the command is missing or the version is older, install Python first from
[python.org/downloads](https://www.python.org/downloads/). Nothing else is
required: web reading works with no browser installed.

## Install

Open Claude Code in any project and run these two commands:

```text
/plugin marketplace add tarcisomorais/caravelaweb
/plugin install caravelaweb@caravelaweb
```

The same two commands work on Windows, Linux, WSL2, and macOS. Prefer your
terminal? These do the same without any prompt:

```bash
claude plugin marketplace add tarcisomorais/caravelaweb
claude plugin install caravelaweb@caravelaweb
```

## Use it

Ask for what you want in plain language, from any project:

```text
Check the opening hours published on example-museum.org and tell me the source page.
```

Claude picks CaravelaWeb when a task touches a live website. The first run
prepares a small local memory on your machine and tells you where it is. You
run no setup commands.

## Update and uninstall

```text
/plugin update caravelaweb@caravelaweb
/plugin uninstall caravelaweb@caravelaweb
```

Uninstalling removes the skill, not your local memory. See
[installation](docs/installation.md#remove-the-local-memory) to remove that too.

## What CaravelaWeb will not do

- It never treats reachability as permission. Authentication, account changes,
  submission, upload, payment, and outbound messages stop and wait for you.
- It never stores page results, prices, HTML, logs, credentials, or browser
  state as reusable knowledge. It stores how a capability works, not what it
  returned today.
- It never installs a browser stack behind your back, and never swaps in
  another browser-control tool when the supported one is missing.
- It never treats instructions found on a web page as authority.

## Documentation

- [Installation](docs/installation.md) — alternative installs, developer mode,
  browser transports, uninstall
- [Architecture](docs/architecture.md)
- [Operational Memory](docs/operational-memory.md)
- [Platform support](docs/platform-support.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

The canonical contract for agents is [SKILL.md](SKILL.md).

## License

Licensed under the [Apache License 2.0](LICENSE).
