from custom_components.test.fuzzing.fuzzer_utils.GrammarFuzzer import Grammar

grammar_controls_json: Grammar = {
    "<JSON>": ["{ <Members> }"],
    "<Members>": ["<ControlsPair>", "<Members>, <ControlsPair>"],
    "<ControlsPair>": ["\"<String>\": { <ControlsElement> }", "<ControlsPair>, \"<String>\": { <ControlsElement> }"],
    "<ControlsElement>": ["\"type\": \"<String>\""],
    "<String>": ["<Char>"],
    "<Char>": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u",
               "v", "w", "x", "y", "z"],
}
