# pyloxone-api

The connection to the Miniserver is not part of this repository. It lives in the separate package **[pyloxone-api](https://github.com/JoDehli/pyloxone-api)** ([PyPI](https://pypi.org/project/pyloxone-api/)), which handles:

- the HTTP bootstrap (API key, structure file `LoxAPP3.json`, public key)
- the WebSocket connection, encryption and token authentication
- keepalive, token refresh, reconnect and backoff
- encrypted and secured commands

The integration only consumes this package. Everything that talks to the Miniserver protocol belongs in `pyloxone-api`; everything that maps controls to Home Assistant entities belongs in `custom_components/loxone/`. The [connection flow](connection-flow.md) describes what the package does step by step.

## Version pinning

The version must be identical in two places:

| File | Used for |
|---|---|
| `custom_components/loxone/manifest.json` (`requirements`) | Home Assistant installs the package from here for users |
| `requirements.txt` | Development and tests |

## Developing against a local checkout

To test changes in `pyloxone-api` together with the integration, clone it next to this repository:

```text
Programmierung/
├── PyLoxone/
└── pyloxone-api/
```

`./scripts/test` installs a sibling checkout in editable mode. If its version equals the pin, the tests run against that local code; otherwise the pinned release from PyPI is used. Set `PYLOXONE_API_SRC` to a path that does not exist to always test against PyPI:

```bash
PYLOXONE_API_SRC=/nonexistent ./scripts/test
```

To run Home Assistant itself (the local runtime in `.venv`) against the checkout, use `./scripts/install-local-pyloxone-api`. It installs the checkout as an editable package without changing Home Assistant's pinned dependencies.

## Token storage

After a successful login the integration stores the Loxone token in its config entry (`.storage/core.config_entries`). The token is bound to host, port and user; a token for a different combination is ignored. See [Token storage](../setup.md#token-storage) for the user-facing details.
