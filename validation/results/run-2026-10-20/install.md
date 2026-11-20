# Aivana - clean install checks

aivana 0.3.1 | Darwin arm64 | uv 0.11.16 | pipx 1.8.0 | live: https://dev-developers.aivana.ai | 2026-10-20T17:29:08

Totals: PASS 8, FAIL 0

| ID | Check | Result | Detail |
|---|---|---|---|
| INS-PIP-310 | pip install aivana==0.3.1 on Python 3.10 (fresh venv) | PASS | aivana 0.3.1; import OK; live: exit 0 answer='ok'; installed: aivana annotated-types anyio certifi exceptiongroup h11 httpcore httpx idna packaging pip pydantic pydantic_core setuptools typing_extensions typing-inspection wheel  |
| INS-PIP-312 | pip install aivana==0.3.1 on Python 3.12 (fresh venv) | PASS | aivana 0.3.1; import OK; live: exit 0 answer='ok'; installed: aivana annotated-types anyio certifi h11 httpcore httpx idna pip pydantic pydantic_core typing_extensions typing-inspection  |
| INS-PIP-313 | pip install aivana==0.3.1 on Python 3.13 (fresh venv) | PASS | aivana 0.3.1; import OK; live: exit 0 answer='ok'; installed: aivana annotated-types anyio certifi h11 httpcore httpx idna pip pydantic pydantic_core typing_extensions typing-inspection  |
| INS-PIP-314 | pip install aivana==0.3.1 on Python 3.14 (fresh venv) | PASS | aivana 0.3.1; import OK; live: exit 0 answer='ok'; installed: aivana annotated-types anyio certifi h11 httpcore httpx idna pip pydantic pydantic_core typing_extensions typing-inspection  |
| INS-PIP-39 | Python 3.9 (below the documented 3.10) is refused by pip | PASS | ERROR: Ignored the following versions that require a different python version: 0.2.0 Requires-Python >=3.10; 0.2.1 Requires-Python >=3.10; 0.2.2 Requires-Python |
| INS-PIPX | pipx install aivana puts a working `aivana` on PATH | PASS | aivana 0.3.1; live: exit 0 answer='ok' |
| INS-UVX | uvx --from aivana==0.3.1 aivana runs without installing | PASS | aivana 0.3.1; live: exit 0 answer='ok' |
| INS-UVX-LATEST | The Docs' exact form `uvx aivana` resolves to the latest release (0.3.1) | PASS | aivana 0.3.1 |
