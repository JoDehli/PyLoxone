from custom_components.test.fuzzing.fuzzer_utils.GrammarFuzzer import Grammar

grammar_ipv4: Grammar = {
    "<IPv4>": ["<Num>.<Num>.<Num>.<Num>"],
    "<Num>": ["<3Digits>", "<2Digits>", "<Digit>"],
    "<3Digits>": ["2<2DigitsR>", "1<Digit><Digit>"],
    "<2Digits>": ["<DigitP><Digit>"],
    "<2DigitsR>": ["55", "5<DigitR>", "<DigitR><Digit>"],
    "<Digit>": ["0", "<DigitP>"],
    "<DigitP>": ["1", "2", "3", "4", "5", "6", "7", "8", "9"],
    "<DigitR>": ["0", "1", "2", "3", "4"]
}

grammar_controls_json: Grammar = {
    "<JSON>": ["{ \"controls\" : { <Members> } }"],
    "<Members>": ["<ControlsPair>", "<Members>, <ControlsPair>"],
    "<ControlsPair>": ["\"<String>\": { <ControlsElement> }", "<ControlsPair>, \"<String>\": { <ControlsElement> }"],
    "<ControlsElement>": ["\"type\": \"<String>\""],
    "<String>": ["<Char>"],
    "<Char>": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u",
               "v", "w", "x", "y", "z"],
}

grammar_loxconfig_rooms_cats_json: Grammar = {
    "<JSON>": ["{ \"rooms\": { <Members> }, \"cats\": { <Members> } }"],
    "<Members>": ["<Pair>", "<Members>, <Pair>"],
    "<Pair>": ["\"<Char>\": { <Element> }", "<Pair>, \"<Char>\": { <Element> }"],
    "<Element>": ["\"name\": \"<Char>\""],
    "<Char>": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u",
               "v", "w", "x", "y", "z"],
}
