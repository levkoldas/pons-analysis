# Security policy

## Supported versions

The latest release line receives security fixes. This project is pre-1.0, so
only the current minor release is supported.

## Reporting a vulnerability

Please do not open a public issue for a vulnerability.

- Use GitHub's private vulnerability reporting on
  <https://github.com/levkoldas/pons-analysis/security/advisories/new>, or
- email <l.koldas@proton.me> with a description, reproduction steps, and the
  affected version.

You will receive an acknowledgement as soon as possible. Please allow time for
a fix and coordinated disclosure before publishing details.

## Credentials

`pons-analysis` reads API keys only through explicit `Credentials` sources:
`Credentials.from_env()`, `Credentials.from_file(...)`, or the constructor.
Keys are excluded from `repr`, and provider errors include bounded response
bodies but never the configured keys. Do not put keys in source files, test
fixtures, notebooks, or committed workspaces.
