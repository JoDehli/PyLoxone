# Developer guide

PyLoxone is a Home Assistant custom integration. The code lives in `custom_components/loxone/`; the connection to the Miniserver is handled by the separate [`pyloxone-api`](pyloxone-api.md) package, which is pinned in `requirements.txt`.

## Repository layout

| Path | Content |
|---|---|
| `custom_components/loxone/` | The integration: one file per Home Assistant platform (`light.py`, `cover.py`, `climate.py`, …), `config_flow.py`, `miniserver.py`, `coordinator.py` |
| `tests/` | Offline test suite; runs the integration inside the Home Assistant test harness against `tests/fixtures/LoxAPP3.json`, no Miniserver needed |
| `blueprints/` | Home Assistant blueprints shipped with the integration |
| `config/` | Home Assistant configuration used by the dev container (git-ignored except `configuration.yaml`) |
| `scripts/` | Helper scripts, see below |
| `docs/` | Internal notes and the Loxone reference documents |
| `site-docs/` | Source of this documentation site |

## Getting started

The recommended setup is the [dev container](devcontainer.md). It contains Python 3.14, all dependencies and a Home Assistant instance that loads the integration from this repository.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/setup` | Installs system packages and dependencies, links the integration into `config/`; runs automatically when the dev container is created |
| `scripts/test` | Runs the test suite in its own virtualenv `.venv-test` |
| `scripts/lint` | Formats the code with `ruff format` |
| `scripts/docs` | Live preview of this documentation |

## Running the tests

```bash
./scripts/test                                  # whole suite
./scripts/test -q                               # quiet
./scripts/test tests/test_light_commands.py -x  # one file, stop at first failure
```

The test virtualenv is created on first use. It is separate from `.venv` on purpose: the test requirements pin a specific Home Assistant version.

## Working on the documentation

```bash
./scripts/docs            # live preview on http://127.0.0.1:8000/PyLoxone/
./scripts/docs --build    # strict build, fails on broken links
```

Pages are Markdown files in `site-docs/`; the navigation is defined in `mkdocs.yml`. Pushes to `master` that touch the docs are published to GitHub Pages by the `Docs` workflow.

!!! note
    `site-docs/blueprints.md` is generated from `BLUEPRINTS.md` and `site-docs/developer/devcontainer.md` and `connection-flow.md` are copies of `docs/DEVCONTAINER.md` and `docs/CONNECTION_FLOW.md`. Update the originals and copy the changes over.

## Further reading

- [pyloxone-api](pyloxone-api.md): the library that talks to the Miniserver, versioning and local development
- [UI and functionality](ui.md): config flow, options, services, repairs
- [Connection flow](connection-flow.md): HTTP bootstrap → WebSocket → authentication → operation → reconnect
