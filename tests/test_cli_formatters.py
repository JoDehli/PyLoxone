"""Unit tests for the pyloxone-cli output formatters.

The connection no longer forwards auth command responses to the
callback, so what reaches a formatter contains no sensitive material:
the pretty formatter therefore prints command replies in full again.
"""

import custom_components.loxone.pyloxone_api.__main__ as cli


def _capture(formatter, data) -> str:
    lines: list[str] = []
    cli._write = lines.append
    formatter.message(data)
    return lines[-1] if lines else None


def test_pretty_reply_is_printed_in_full():
    """Previously the reply was cut to its command name to hide
    getjwt/token paths; auth replies no longer reach the formatter."""
    formatter = cli.PrettyFormatter()

    line = _capture(
        formatter,
        {"control": "dev/sps/enablebinstatusupdate", "value": "1", "Code": 200},
    )

    assert "reply" in line
    assert "dev/sps/enablebinstatusupdate" in line
    assert "1" in line
    assert "code=200" in line


def test_pretty_state_line_with_label():
    formatter = cli.PrettyFormatter()
    formatter.labels["<uuid-state>"] = "Buero.states.position"

    line = _capture(formatter, {"<uuid-state>": 1.0})

    assert "Buero.states.position" in line
    assert "[<uuid-state>]" in line
    assert "1.0" in line


def test_pretty_state_line_without_label_keeps_uuid():
    formatter = cli.PrettyFormatter()

    line = _capture(formatter, {"<uuid-other>": "text"})

    assert "[<uuid-other>]" in line
    assert "text" in line


def test_pretty_keepalive():
    formatter = cli.PrettyFormatter()

    line = _capture(formatter, {"keep_alive": "received"})

    assert "keep-alive" in line


def test_raw_formatter_prints_everything():
    formatter = cli.RawFormatter()
    data = {"control": "x", "Code": 200}

    line = _capture(formatter, data)

    assert line == str(data)
