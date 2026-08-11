# CaravelaWeb

This repository is itself the CaravelaWeb skill root. The canonical CaravelaWeb
contract is [`SKILL.md`](SKILL.md) at the repository root. Read it before acting
on a web task; this file does not repeat it.

## Web tasks

- Use CaravelaWeb whenever a task needs web access, and follow root `SKILL.md`.
- Consult Operational Memory with `scripts/knowledge-lookup` before treating a
  capability as unknown. Enter bounded Discovery only when the caller authorizes
  it, and finalize it with `scripts/discovery-finalize`.
- Preserve caller authority. Technical reachability authorizes nothing: stop
  before authentication, consent, account mutation, submission, upload, payment,
  or external communication.
- Keep the transport order `DIRECT_READ -> LIGHTPANDA -> CHROME` and stop at the
  first transport that reliably proves the capability.
- Do not modify CaravelaWeb source to accomplish an ordinary web task.

## Development work

- Read [`CONTRIBUTING.md`](CONTRIBUTING.md) before you change this repository.
- Run the deterministic suite from the repository root:
  `python3 -m unittest discover -s tests -p 'test_*.py'`. On native Windows, use
  `python` instead of `python3`.
