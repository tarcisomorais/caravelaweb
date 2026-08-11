# External Dependencies

CaravelaWeb owns routing and result contracts, not browser installation or
version management. The required runtime is Python 3.11+ with stdlib `sqlite3`.
`DIRECT_READ` needs no browser dependency.

| Optional component | Linux / WSL2 | Native Windows | macOS |
| --- | --- | --- | --- |
| `agent-browser` | available upstream | available upstream | unvalidated here |
| Chrome | detectable when installed | detectable when installed | unvalidated here |
| Lightpanda | available upstream | `PLATFORM_UNSUPPORTED`; use WSL2 | unvalidated here |

Check the shell directly (`agent-browser --version`) and use upstream install
instructions. CaravelaWeb does not wrap, vendor, install, pin, or track these
tools. A missing optional transport does not reduce platform support and never
becomes target knowledge.
