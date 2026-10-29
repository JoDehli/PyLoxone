"""Tests for the ``--format web`` view of the pyloxone-cli.

The page is rendered entirely in Python (aiohttp) and uses a plain HTML
``meta http-equiv="refresh"`` for live values - no JavaScript anywhere.
"""

import custom_components.loxone.pyloxone_api.__main__ as cli

STRUCTURE = {
    "controls": {
        "<ctl-a>": {
            "name": "Fenster Buero",
            "type": "Jalousie",
            "uuidAction": "<ctl-a>",
            "states": {"up": "<uuid-up>", "position": "<uuid-pos>"},
            "subControls": {
                "<ctl-a-sub>": {
                    "name": "Sub A",
                    "uuidAction": "<ctl-a-sub>",
                    "states": {"active": "<uuid-active>"},
                }
            },
        },
        "<ctl-b>": {"name": "Radio Bad", "type": "Radio", "uuidAction": "<ctl-b>", "states": {}},
    },
    "autopilot": {
        "<ctl-ap>": {
            "name": "Automatik-Regeln",
            "uuidAction": "<ctl-ap>",
            "states": {"changed": "<uuid-changed>"},
        }
    },
}


def _ui(states: dict | None = None) -> cli.WebUi:
    ui = cli.WebUi(port=8999)
    ui.set_structure(STRUCTURE)
    if states:
        ui.states.update(states)
    return ui


# --- _tree_nodes: the server-side tree model ---------------------------------


def test_tree_sections_cover_controls_and_autopilot():
    ui = _ui()

    assert [section["name"] for section in ui.sections] == ["controls", "autopilot"]


def test_tree_nodes_keep_json_order_and_type():
    nodes = _ui().sections[0]["nodes"]

    assert nodes[0]["name"] == "Fenster Buero"
    assert nodes[0]["type"] == "Jalousie"
    assert nodes[1]["name"] == "Radio Bad"


def test_tree_states_carry_labels():
    node = _ui().sections[0]["nodes"][0]

    assert node["states"] == [
        {"key": "up", "uuid": "<uuid-up>", "label": "Fenster Buero.states.up"},
        {
            "key": "position",
            "uuid": "<uuid-pos>",
            "label": "Fenster Buero.states.position",
        },
    ]


def test_tree_sub_controls_are_nested():
    nodes = _ui().sections[0]["nodes"]

    assert nodes[0]["subControls"][0]["name"] == "Sub A"
    assert nodes[0]["subControls"][0]["states"][0]["label"] == "Fenster Buero / Sub A.states.active"


def test_autopilot_states_are_labelled_by_section():
    node = _ui().sections[1]["nodes"][0]

    assert node["states"][0]["label"] == "autopilot.states.changed"


# --- message intake -----------------------------------------------------------


def test_message_updates_states():
    ui = _ui()

    ui.message({"<uuid-up>": 0.0, "<uuid-pos>": 1.0})

    assert ui.states["<uuid-up>"] == 0.0
    assert ui.states["<uuid-pos>"] == 1.0


def test_message_ignores_replies_and_keepalive():
    ui = _ui()

    ui.message({"control": "jdev/sps/io/x", "Code": 200, "value": "1"})
    ui.message({"keep_alive": "received"})

    assert ui.states == {}


# --- page rendering -----------------------------------------------------------


def test_page_contains_refresh_and_no_javascript():
    ui = _ui({"<uuid-up>": 0.0})
    page = ui._render_page("")

    assert '<meta http-equiv="refresh" content="2">' in page
    assert "<script" not in page


def test_page_shows_states_with_labels_and_values():
    ui = _ui({"<uuid-up>": 0.0})
    page = ui._render_page("")

    assert "Fenster Buero.states.up" in page
    assert '[&lt;uuid-up&gt;]' in page
    assert '<span class="value off">0</span>' in page  # {:g} renders 0.0 as 0


def test_page_escapes_names_and_values():
    ui = cli.WebUi()
    ui.set_structure({"controls": {"<x>": {"name": "<b>Bold</b>", "uuidAction": "<x>", "states": {"t": "<s>"}}}})
    ui.states["<s>"] = "<img onerror>"
    page = ui._render_page("")

    assert "&lt;b&gt;Bold&lt;/b&gt;" in page
    assert "&lt;img onerror&gt;" in page


def test_page_filter_narrows_the_tree():
    ui = _ui()

    page = ui._render_page("radio bad")
    assert "Radio Bad" in page
    assert "Fenster Buero" not in page

    empty = ui._render_page("nothing matches this")
    assert "Fenster Buero" not in empty


def test_page_colors_values_by_state():
    ui = _ui({"<uuid-up>": 1.0, "<uuid-pos>": 0.0})
    page = ui._render_page("")

    assert '<span class="value on">1</span>' in page
    assert '<span class="value off">0</span>' in page


def test_value_class_text_values_stay_neutral():
    assert cli._value_class(1.0) == "on"
    assert cli._value_class(0) == "off"
    assert cli._value_class(True) == "on"
    assert cli._value_class("Off / Lock") == ""
    assert cli._value_class(None) == ""


def test_paused_page_has_no_refresh_and_keeps_pause_across_filter():
    ui = _ui()

    page = ui._render_page("radio", paused=True)

    assert "http-equiv" not in page
    assert '<input type="hidden" name="pause" value="1">' in page
    assert 'name="pause" value="1">Pause updates' not in page
    assert 'href="/?q=radio"' in page  # resume link drops the pause flag


def test_page_has_render_time_footer():
    ui = _ui()

    assert "rendered at" in ui._render_page("")
