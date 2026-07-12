"""Tests for Loxone Radio block to select option mapping."""

from custom_components.loxone.select import (
    ALL_OFF_DEFAULT_LABEL,
    ALL_OFF_VALUE,
    build_option_maps,
)


# Sample "Ventilatie" Radio block taken from a real LoxAPP3.json structure file.
VENTILATIE_DETAILS = {
    "jLockable": True,
    "allOff": "",
    "outputs": {
        "1": "Stand 1",
        "2": "Stand 2",
        "3": "Stand 3",
        "4": "Stand 4",
    },
}


class TestBuildOptionMaps:
    """Test build_option_maps — the pure Radio-to-select mapping function."""

    def test_outputs_become_options(self):
        options, _, _ = build_option_maps(VENTILATIE_DETAILS)
        assert "Stand 1" in options
        assert "Stand 4" in options

    def test_options_are_sorted_by_output_number(self):
        options, _, _ = build_option_maps(VENTILATIE_DETAILS)
        # The "all off" entry is first, followed by outputs in numeric order.
        assert options == [
            ALL_OFF_DEFAULT_LABEL,
            "Stand 1",
            "Stand 2",
            "Stand 3",
            "Stand 4",
        ]

    def test_empty_all_off_uses_default_label(self):
        options, num_to_opt, opt_to_num = build_option_maps(VENTILATIE_DETAILS)
        assert ALL_OFF_DEFAULT_LABEL in options
        assert num_to_opt[ALL_OFF_VALUE] == ALL_OFF_DEFAULT_LABEL
        assert opt_to_num[ALL_OFF_DEFAULT_LABEL] == ALL_OFF_VALUE

    def test_custom_all_off_label(self):
        details = {"allOff": "Uit", "outputs": {"1": "Stand 1"}}
        options, num_to_opt, opt_to_num = build_option_maps(details)
        assert options == ["Uit", "Stand 1"]
        assert num_to_opt[ALL_OFF_VALUE] == "Uit"
        assert opt_to_num["Uit"] == ALL_OFF_VALUE

    def test_no_all_off_when_detail_absent(self):
        details = {"outputs": {"1": "Stand 1", "2": "Stand 2"}}
        options, num_to_opt, opt_to_num = build_option_maps(details)
        assert options == ["Stand 1", "Stand 2"]
        assert ALL_OFF_VALUE not in num_to_opt

    def test_number_to_option_mapping(self):
        _, num_to_opt, _ = build_option_maps(VENTILATIE_DETAILS)
        assert num_to_opt[1] == "Stand 1"
        assert num_to_opt[2] == "Stand 2"
        assert num_to_opt[3] == "Stand 3"
        assert num_to_opt[4] == "Stand 4"

    def test_option_to_number_mapping(self):
        _, _, opt_to_num = build_option_maps(VENTILATIE_DETAILS)
        assert opt_to_num["Stand 1"] == 1
        assert opt_to_num["Stand 4"] == 4

    def test_round_trip_number_option_number(self):
        _, num_to_opt, opt_to_num = build_option_maps(VENTILATIE_DETAILS)
        for number in (0, 1, 2, 3, 4):
            assert opt_to_num[num_to_opt[number]] == number

    def test_duplicate_output_names_are_deduplicated(self):
        details = {"outputs": {"1": "Stand", "2": "Stand", "3": "Stand"}}
        options, _, opt_to_num = build_option_maps(details)
        # All labels remain unique as required by Home Assistant.
        assert len(options) == len(set(options))
        assert options == ["Stand", "Stand (2)", "Stand (3)"]
        assert opt_to_num["Stand"] == 1
        assert opt_to_num["Stand (2)"] == 2
        assert opt_to_num["Stand (3)"] == 3

    def test_missing_outputs_key(self):
        options, num_to_opt, opt_to_num = build_option_maps({})
        assert options == []
        assert num_to_opt == {}
        assert opt_to_num == {}
