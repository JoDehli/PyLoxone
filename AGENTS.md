# AGENTS.md

Project guidance for OpenCode/coding agents in this repository (Home Assistant Loxone integration, pyloxone-api).

## Key Entry Points

- Home Assistant integration: `custom_components/loxone/`
- Loxone connection library: `pyloxone-api`, an external package and not part of this repo. The pinned version is listed in `custom_components/loxone/manifest.json`. Upstream repo: https://github.com/JoDehli/pyloxone-api (`src/pyloxone_api/connection.py`, `src/pyloxone_api/const.py`).
- Documentation on Miniserver communication: `docs/CommunicatingWithMiniserver.pdf` (also at https://www.loxone.com/wp-content/uploads/datasheets/CommunicatingWithMiniserver.pdf)
- Connection flow (from manual + code): `docs/CONNECTION_FLOW.md`
- Structure file `LoxoneStructureFile.pdf`: not checked into the repo
- Implemented control types: `docs/IMPLEMENTED_CONTROL_TYPES.md`

## Notes

- Connection flow (HTTP bootstrap → WebSocket → Auth → operation → reconnect): see `docs/CONNECTION_FLOW.md`.
- Control types from the structure file and their HA implementation: see `docs/IMPLEMENTED_CONTROL_TYPES.md`.
- Python, available via `.venv`/`.venv-test`; tests under `tests/`.
- Keep changes consistent with existing patterns; no unnecessary refactors.
- Docs stay in sync: whenever a change is relevant to the documentation (connection flow, control types, supported devices, setup/config), update the affected docs in the same change, even if not explicitly asked.
