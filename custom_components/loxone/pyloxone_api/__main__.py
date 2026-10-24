"""
Connect to a Miniserver and print what it sends, without Home Assistant.

Run it through the launcher, which loads this package on its own::

    scripts/pyloxone-cli <host> <port> <username> [--format raw|pretty] [--uuid UUID ...]

Without ``--format`` the output is ``raw``.

``--uuid`` limits the output to one or more controls, including all their
states and sub-controls. The password is asked for (or read from
``LOXONE_PASSWORD``), never taken from the command line, where other users
could read it from the process list. ``python -m
custom_components.loxone.pyloxone_api`` does not work: it imports the
integration package, and with it Home Assistant.

Output formats are classes in ``FORMATTERS``. To add one, subclass
``Formatter``, implement ``connection`` and ``message``, and register it
there; it then shows up in ``--format`` automatically.
"""

import argparse
import asyncio
import datetime
import getpass
import logging
import os
import sys

from .connection import LoxoneConnection

_LOGGER = logging.getLogger(__package__ or "pyloxone_api")


_LABEL_WIDTH = 60


def _write(text: str) -> None:
    print(text)  # noqa: T201 - printing is this tool's purpose


def _error(text: str) -> None:
    print(text, file=sys.stderr)  # noqa: T201 - printing is this tool's purpose


def _text(value) -> str:
    return value if isinstance(value, str) else repr(value)


class Formatter:
    """How connection state and Miniserver messages are shown.

    ``labels`` maps uuids to readable names, filled in once connected. A
    subclass that defines ``__init__`` must call ``super().__init__()``.
    """

    def __init__(self) -> None:
        self.labels: dict[str, str] = {}

    def connection(self, connected: bool) -> None:
        raise NotImplementedError

    def message(self, data) -> None:
        raise NotImplementedError


class RawFormatter(Formatter):
    """Every message exactly as the connection hands it over."""

    def connection(self, connected: bool) -> None:
        _write("connected" if connected else "disconnected")

    def message(self, data) -> None:
        _write(str(data))


class PrettyFormatter(Formatter):
    """One timestamped line per state; other messages as single lines.

    Command replies are printed in full: the connection no longer
    forwards auth command responses (keys, tokens), so what reaches the
    formatter carries no sensitive material.
    """

    def connection(self, connected: bool) -> None:
        self._line("connected" if connected else "disconnected")

    def message(self, data) -> None:
        if not isinstance(data, dict):
            self._line(str(data))
        elif "control" in data:
            self._line(
                f"reply     {data.get('control')}  {_text(data.get('value'))}  code={data.get('Code')}"
            )
        elif "keep_alive" in data:
            self._line("keep-alive")
        else:
            for uuid, value in data.items():
                label = self.labels.get(uuid, "")
                self._line(f"state     {label:<{_LABEL_WIDTH}}  [{uuid}]  {_text(value)}")

    @staticmethod
    def _line(text: str) -> None:
        _write(f"{datetime.datetime.now().strftime('%H:%M:%S')}  {text}")


FORMATTERS: dict[str, type[Formatter]] = {
    "raw": RawFormatter,
    "pretty": PrettyFormatter,
}


def _strings(value) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [item for item in value if isinstance(item, str)]
    else:
        values = []
    return [item for item in values if item]


def _controls(structure: dict) -> dict:
    """All controls, including the autopilot section, which is outside ``controls``."""
    controls = dict(structure.get("autopilot") or {})
    controls.update(structure.get("controls") or {})
    return controls


def _control_uuids(structure: dict, roots: list[str]) -> frozenset[str]:
    """Every uuid of the given controls: their own, their states and their sub-controls."""
    controls = _controls(structure)
    found: set[str] = set()
    pending: list[tuple[str, object]] = []
    for root in roots:
        if root not in controls:
            raise ValueError(f"unknown control uuid: {root}")
        pending.append((root, controls[root]))
    while pending:
        uuid, control = pending.pop()
        found.add(uuid)
        if not isinstance(control, dict):
            continue
        found.update(_strings(control.get("uuidAction")))
        for value in (control.get("states") or {}).values():
            found.update(_strings(value))
        pending.extend((sub_uuid, sub) for sub_uuid, sub in (control.get("subControls") or {}).items())
    return frozenset(found)


def _state_labels(structure: dict) -> dict[str, str]:
    """Readable names: ``<control>`` for controls, ``<control>.states.<key>`` for states."""
    labels: dict[str, str] = {}

    def walk(uuid: str, control: object, parent: str, name: str = "") -> None:
        if not isinstance(control, dict):
            return
        name = name or str(control.get("name") or uuid)
        label = f"{parent} / {name}" if parent else name
        labels.setdefault(uuid, label)
        for own in _strings(control.get("uuidAction")):
            labels.setdefault(own, label)
        for key, value in (control.get("states") or {}).items():
            for state_uuid in _strings(value):
                labels.setdefault(state_uuid, f"{label}.states.{key}")
        for sub_uuid, sub in (control.get("subControls") or {}).items():
            walk(sub_uuid, sub, label)

    for uuid, control in (structure.get("controls") or {}).items():
        walk(uuid, control, "")
    # The autopilot section has no names of its own: it is labelled by section.
    for uuid, control in (structure.get("autopilot") or {}).items():
        walk(uuid, control, "", name="autopilot")
    return labels


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="pyloxone-cli",
        description="Connect to a Miniserver and print what it sends.",
    )
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("username")
    parser.add_argument(
        "--format",
        choices=sorted(FORMATTERS),
        default="raw",
        help="output format (default: %(default)s)",
    )
    parser.add_argument(
        "--uuid",
        action="append",
        default=[],
        metavar="UUID",
        help="show only this control and its states and sub-controls; repeat for more",
    )
    return parser.parse_args(argv)


async def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    password = os.environ.get("LOXONE_PASSWORD") or getpass.getpass(
        f"Password for {args.username}@{args.host}: "
    )
    formatter = FORMATTERS[args.format]()
    api = LoxoneConnection(
        host=args.host, port=args.port, username=args.username, password=password
    )
    wanted: frozenset[str] | None = None

    def on_state(connected: bool) -> None:
        nonlocal wanted
        # The structure file is loaded before the connection is reported up.
        if connected:
            formatter.labels = _state_labels(api.structure_file)
        formatter.connection(connected)
        if connected and args.uuid and wanted is None:
            try:
                wanted = _control_uuids(api.structure_file, args.uuid)
            except ValueError as error:
                _error(str(error))
                wanted = frozenset()

    def on_message(data) -> None:
        if not args.uuid:
            formatter.message(data)
            return
        if wanted is None or not isinstance(data, dict):
            return
        if "control" in data or "keep_alive" in data:
            return
        states = {uuid: value for uuid, value in data.items() if uuid in wanted}
        if states:
            formatter.message(states)

    try:
        await api.run(on_state, callback=on_message)
    finally:
        await api.close()
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG if os.environ.get("LOXONE_DEBUG") else logging.INFO)
    try:
        sys.exit(asyncio.run(main(sys.argv[1:])))
    except KeyboardInterrupt:
        sys.exit(130)
