# External Dependencies

CaravelaWeb owns routing and result contracts, not browser installation or
version management. The required runtime is Python 3.11+ with stdlib `sqlite3`.
`DIRECT_READ` needs no browser dependency.

| Optional component | Linux / WSL2 | Native Windows | macOS |
| --- | --- | --- | --- |
| `agent-browser` | available upstream | available upstream | unvalidated here |
| Chrome | detectable when installed | detectable when installed | unvalidated here |
| Lightpanda | available upstream | `PLATFORM_UNSUPPORTED` natively | unvalidated here |

`READY` means the core Knowledge Root and Operational Memory are usable; it
does not guarantee browser coverage. Preflight reports browser control,
browser-engine detection, and `NOT_CHECKED` launch runtime separately.

Check the shell directly (`agent-browser --version`) and use upstream install
instructions only with explicit user authorization. Normal upstream remediation
is to install `agent-browser`, run `agent-browser install` when browser
provisioning is required, and use `agent-browser doctor --json` when diagnosis
is appropriate. CaravelaWeb does not wrap, vendor, install, pin, or track these
tools. A missing optional transport does not reduce platform support and never
becomes target knowledge. Do not substitute Playwright, Puppeteer, Selenium,
CDP/MCP tooling, or another browser-control stack when `agent-browser` is
unavailable or broken.

A separate, intentionally chosen Linux/WSL2 runtime may support Lightpanda;
CaravelaWeb does not bridge Windows and WSL2 automatically.
