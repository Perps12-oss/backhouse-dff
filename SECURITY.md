# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x (main) | Yes |

## Reporting a vulnerability

Please report security issues privately by opening a GitHub Security Advisory on the repository,
or contact the maintainers directly. Do not file public issues for exploitable vulnerabilities.

Include:

- Affected version / commit
- Steps to reproduce
- Impact assessment (local vs remote)

## Threat model

CEREBRO is a **local desktop application**. It scans user-selected folders and may delete or
move files to managed trash. There is no network-facing API in the default configuration.

Primary risks:

- Malicious or tampered files under `~/.cerebro/` (session/snapshot JSON)
- Supply-chain compromise during source installs (`pip install` bootstrap)
- Unsafe deletion of hardlinked or system paths

## Release expectations

- Frozen builds must not auto-install dependencies from PyPI at runtime.
- **Enterprise / from-source installs:** set `CEREBRO_SKIP_AUTO_DEPS=1` by default (disable runtime `pip install` from PyPI). Install from `requirements.lock` or vendored wheels offline instead.
- Permanent deletes require an explicit deletion gate token; trash uses pipeline validation.
