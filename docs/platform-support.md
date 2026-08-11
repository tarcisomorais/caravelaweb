# Platform support

CaravelaWeb requires Python 3.11 or newer and standard-library SQLite.

| Platform | Runtime status | Notes |
| --- | --- | --- |
| Linux | CI validated | Full deterministic suite and path gate. |
| Native Windows | CI validated | Full deterministic suite plus a real CLI lifecycle exercise. |
| WSL2 | Supported as Linux | Keep the Knowledge Root on a Linux-native path. |
| macOS | Not currently CI validated | The portable runtime avoids Linux-only imports on read paths, but no support claim is made without CI evidence. |

## Filesystem placement

Use a path native to the running platform. SQLite coordination across an OS
boundary is not considered safe for this workload.

- On native Windows, do not place the active Knowledge Root under a WSL UNC
  path such as `\\wsl.localhost\...`.
- Under WSL2, prefer the Linux filesystem rather than `/mnt/<drive>`.
- Do not let Windows and WSL2 write the same database concurrently.
- Network and other remote filesystems are reported as unproven; prefer a
  native local path.

Preflight reports boundary-crossing paths as warnings. It does not silently
move or rewrite an installation.

## Optional transports

`DIRECT_READ` is always available as policy and requires no browser install.

| Component | Linux / WSL2 | Native Windows | macOS |
| --- | --- | --- | --- |
| `agent-browser` | Optional | Optional | Unvalidated |
| Chrome | Optional | Optional | Unvalidated |
| Lightpanda | Optional | Platform unsupported; use WSL2 | Unvalidated |

When Lightpanda is physically unavailable on a platform, that fact produces
no target observation, Candidate, or degradation. After DIRECT_READ is shown
insufficient, Chrome may be tested if available.

## Encoding and markers

CLI output is configured for UTF-8. Marker files must be ordinary,
singly-linked files; symlinks, hard links, and Windows reparse points fail
closed where authority depends on the marker.
