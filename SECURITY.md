# Security Policy

## Supported version

Security fixes are applied to the current `main` branch.

## Reporting a vulnerability

Please do not publish an exploitable vulnerability, secret, or user data in a public issue.

When reporting a security problem, include:

- the affected feature or endpoint;
- clear reproduction steps;
- the expected and actual behavior;
- impact and any known workaround;
- logs or screenshots with credentials and personal data removed.

## Project-specific security notes

OpenTune is designed primarily as a local/self-hosted application. Reports are especially useful for issues involving authentication bypasses, session handling, stored account data, path traversal, cross-site scripting, request forgery, or accidental exposure of the local SQLite database.

The built-in recovery-question flow is intentionally simple. Do not reuse important passwords or recovery answers from other services.

## Secrets

Do not commit credentials, tokens, cookies, local databases, or other private runtime data to the repository.
