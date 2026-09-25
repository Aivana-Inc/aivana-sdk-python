# Security policy

## Reporting a vulnerability

Please don't report security problems in public issues, pull requests or
discussions.

Report them privately instead: on this repository's **Security** tab, click
**Report a vulnerability**. Only the maintainers can see what you send. We'll
acknowledge the report and keep you updated while we work on a fix.

This repository holds the SDK and the `aivana` command. If the problem is in the
Aivana API itself rather than in this code, report it the same way and we'll
route it.

## Supported versions

Security fixes go into the latest release. Please check that the problem still
happens on it before reporting.

## Keeping your API key safe

The SDK authenticates with a long-lived API key, so treat it like a password:

- Use it only in server-side code. Never ship it in a browser or mobile app,
  where anyone can read it.
- Keep it out of source control. Read it from the `AIVANA_API_KEY` environment
  variable or your secrets manager.
- If a key leaks, revoke it in AI Studio under **API Keys** and create a new one.
