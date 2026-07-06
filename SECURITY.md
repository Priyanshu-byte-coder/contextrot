# Security Policy

## Scope

contextrot reads local files and makes **zero network calls** — no telemetry,
no uploads, no HTTP client in the dependency tree. The main security surface
is the parsing of local transcript files and the generated HTML report.

Reports we care about most:

- Anything that makes contextrot transmit data off the machine
- HTML/JS injection into the generated report via crafted transcript content
- Path traversal or file writes outside the requested output path
- Crashes with attacker-controlled transcript files that could hide malicious
  content from review

## Supported versions

Only the latest release on PyPI receives security fixes.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/Priyanshu-byte-coder/contextrot/security/advisories/new)
— or email doshipriyanshu3@gmail.com if you prefer.

Please do not open a public issue for security reports. You'll get an initial
response within 72 hours.
