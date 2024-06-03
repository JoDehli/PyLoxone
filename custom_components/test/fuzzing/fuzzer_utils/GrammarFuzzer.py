import math
from typing import Dict, List, Tuple
import re
from enum import Enum

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


class CostGrammarType(Enum):
    MIN = 1
    MAX = 2


class GrammarFuzzer():

    def __init__(self) -> None:
        pass

    def __convert_to_cost_grammar(self, grammar: Grammar, conversion_type: CostGrammarType) -> Tuple[
        Annotated_Grammar, Annotated_Non_Terminals]:
        cost_grammar: Annotated_Grammar = {}
        annotated_non_terminals: Annotated_Non_Terminals = {}

        def convert_rule(head: Element, body: List[Element]) -> None:
            if head in annotated_non_terminals:
                return

            annotated_elements: List[Annotated_Element] = []

            is_inf = False

            for element in body:
                cost = 0
                non_terminals = re.findall(NON_TERMINAL_REGEX, element)

                if head in non_terminals:
                    is_inf = True
                    annotated_non_terminals[head] = math.inf

                for non_terminal in non_terminals:
                    if non_terminal not in annotated_non_terminals:
                        convert_rule(non_terminal, grammar[non_terminal])
                    cost += annotated_non_terminals[non_terminal]

                annotated_elements.append((element, cost))

            cost_grammar[head] = annotated_elements

            if not is_inf:
                annotated_non_terminals[head] = min(annotated_elements, key=lambda x: x[1])[
                                                    1] + 1 if conversion_type == CostGrammarType.MIN else \
                    max(annotated_elements, key=lambda x: x[1])[1] + 1

        for key, value in grammar.items():
            convert_rule(key, value)

        return cost_grammar, annotated_non_terminals

    def __convert_to_trackable_grammar(self, grammar: Grammar) -> Tuple[Annotated_Grammar, Annotated_Non_Terminals]:
        trackable_grammar: Annotated_Grammar = {}
        trackable_non_terminals: Annotated_Non_Terminals = {}

        def convert_rule(head: Element, body: List[Element]) -> None:
            if head in trackable_non_terminals:
                return

            trackable_elements: List[Annotated_Element] = []

            for element in body:
                non_terminals = re.findall(NON_TERMINAL_REGEX, element)

                for non_terminal in non_terminals:
                    if non_terminal not in trackable_non_terminals:
                        convert_rule(non_terminal, grammar[non_terminal])

                trackable_elements.append((element, 0))

            trackable_non_terminals[head] = 0
            trackable_grammar[head] = trackable_elements

        for key, value in grammar.items():
            convert_rule(key, value)

        return trackable_grammar, trackable_non_terminals

    def __compose_min_cost(self, head: Element, given_cost_grammar: Annotated_Grammar) -> str:
        min_tuple: Annotated_Element = min(given_cost_grammar[head], key=lambda x: x[1])
        is_non_terminal = True if re.findall(NON_TERMINAL_REGEX, min_tuple[0]) else False

        if not is_non_terminal:
            return min_tuple[0]
        else:
            non_terminals = re.findall(NON_TERMINAL_REGEX, min_tuple[0])
            replacements = iter(
                list(map(lambda element: self.__compose_min_cost(element, given_cost_grammar), non_terminals)))
            result = re.sub(NON_TERMINAL_REGEX, lambda element: next(replacements), min_tuple[0])
            return result

    def fuzz_min_cost(self, grammar: Grammar, start_symbol: Element) -> str:
        cost_grammar: Annotated_Grammar
        cost_grammar, _ = self.__convert_to_cost_grammar(
            grammar, CostGrammarType.MIN)

        return self.__compose_min_cost(start_symbol, cost_grammar)

    def __compose_max_cost(self, head: Element, given_cost_grammar: Annotated_Grammar, applications: int,
                           max_applications: int) -> str:

        if applications == max_applications:
            min_tuple: Annotated_Element = min(given_cost_grammar[head], key=lambda x: x[1])
            is_non_terminal = True if re.findall(NON_TERMINAL_REGEX, min_tuple[0]) else False

            if not is_non_terminal:
                return min_tuple[0]
            else:
                non_terminals = re.findall(NON_TERMINAL_REGEX, min_tuple[0])
                replacements = iter(
                    list(map(lambda element: self.__compose_max_cost(element, given_cost_grammar, applications,
                                                                     max_applications), non_terminals)))
                result = re.sub(NON_TERMINAL_REGEX, lambda element: next(replacements), min_tuple[0])
                return result
        else:
            max_tuple: Annotated_Element = max(given_cost_grammar[head], key=lambda x: x[1])
            is_non_terminal = True if re.findall(NON_TERMINAL_REGEX, max_tuple[0]) else False

            if not is_non_terminal:
                return max_tuple[0]
            else:
                non_terminals = re.findall(NON_TERMINAL_REGEX, max_tuple[0])
                replacements = iter(
                    list(map(lambda element: self.__compose_max_cost(element, given_cost_grammar, applications + 1,
                                                                     max_applications), non_terminals)))
                result = re.sub(NON_TERMINAL_REGEX, lambda element: next(replacements), max_tuple[0])
                return result

    def fuzz_max_cost(self, grammar: Grammar, start_symbol: Element, max_rule_applications: int) -> str:
        cost_grammar: Annotated_Grammar
        cost_grammar, _ = self.__convert_to_cost_grammar(
            grammar, CostGrammarType.MAX)

        return self.__compose_max_cost(start_symbol, cost_grammar, 0, max_rule_applications)


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

inf_grammar: Grammar = {
    "<Start>": ["0", "<End>"],
    "<End>": ["1", "1<End>"],
}

test_fuzzer = GrammarFuzzer()
# test_fuzzer.convert_to_cost_grammar(expr_grammar, CostGrammarType.MAX)
# test_fuzzer.convert_to_cost_grammar(inf_grammar, CostGrammarType.MIN)
# test_fuzzer.convert_to_trackable_grammar(expr_grammar)
print(test_fuzzer.fuzz_min_cost(expr_grammar, "<IPv4>"))
print(test_fuzzer.fuzz_max_cost(expr_grammar, "<IPv4>", 2))
print(test_fuzzer.fuzz_max_cost(inf_grammar, "<Start>", 10))
