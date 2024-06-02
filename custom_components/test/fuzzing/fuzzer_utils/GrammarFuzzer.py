import functools
from pprint import pprint
from typing import Dict, List, Tuple
import re

# derivations to be supported
# - minimal cost derivation
# - maximal cost derivation
# - three-phase derivation ?
# - probabilistic derivation ?
# - grammar coverage ?

Element = str
Grammar = Dict[Element, List[Element]]

Annotated_Element = Tuple[Element, int]
Annotated_Non_Terminals = Dict[Element, int]
Annotated_Grammar = Dict[Element, List[Annotated_Element]]

NON_TERMINAL_REGEX = re.compile(r"<.*?>")


class GrammarFuzzer():

    def __init__(self) -> None:
        pass

    def convert_to_min_cost_grammar(self, grammar: Grammar) -> Tuple[Annotated_Grammar, Annotated_Non_Terminals]:
        cost_grammar: Annotated_Grammar = {}
        annotated_non_terminals: Annotated_Non_Terminals = {}

        def convert_rule(head: Element, body: List[Element]) -> None:
            if head in annotated_non_terminals:
                return

            annotated_elements: List[Annotated_Element] = []

            for element in body:
                cost = 0
                non_terminals = re.findall(NON_TERMINAL_REGEX, element)

                for non_terminal in non_terminals:
                    if non_terminal not in annotated_non_terminals:
                        convert_rule(non_terminal, grammar[non_terminal])
                    cost += annotated_non_terminals[non_terminal]

                annotated_elements.append((element, cost))

            cost_grammar[head] = annotated_elements
            annotated_non_terminals[head] = min(annotated_elements, key=lambda x: x[1])[1] + 1

        for key, value in grammar.items():
            convert_rule(key, value)

        return cost_grammar, annotated_non_terminals

    def fuzz_min_cost(self, grammar: Grammar, start_symbol: Element) -> List[str]:
        pass

    def fuzz_max_cost(self, grammar: Grammar, start_symbol: Element) -> str:
        pass


expr_grammar: Grammar = {
    "<IPv4>": ["<Num>.<Num>.<Num>.<Num>"],
    "<Num>": ["<3Digits>", "<2Digits>", "<Digit>"],
    "<3Digits>": ["2<2DigitsR>", "1<Digit><Digit>"],
    "<2Digits>": ["<DigitP><Digit>"],
    "<2DigitsR>": ["55", "5<DigitR>", "<DigitR><Digit>"],
    "<Digit>": ["0", "<DigitP>"],
    "<DigitP>": ["1", "2", "3", "4", "5", "6", "7", "8", "9"],
    "<DigitR>": ["0", "1", "2", "3", "4"]
}

test_fuzzer = GrammarFuzzer()
test_fuzzer.convert_to_min_cost_grammar(expr_grammar)
