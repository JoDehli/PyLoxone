import math
from typing import Dict, List, Tuple
import re
from enum import Enum
from random import sample

Element = str
Grammar = Dict[Element, List[Element]]

Annotated_Element = Tuple[Element, int]
Annotated_Non_Terminals = Dict[Element, int]
Annotated_Grammar = Dict[Element, List[Annotated_Element]]


class CostGrammarType(Enum):
    MIN = 1
    MAX = 2


class GrammarFuzzer:
    _NON_TERMINAL_REGEX = re.compile(r"<.*?>")

    def __init__(self) -> None:
        """constructor"""
        pass

    def __convert_to_cost_grammar(
            self, grammar: Grammar, conversion_type: CostGrammarType
    ) -> Tuple[Annotated_Grammar, Annotated_Non_Terminals]:
        """Converts a common grammar to an annotated cost grammar"""
        cost_grammar: Annotated_Grammar = {}
        annotated_non_terminals: Annotated_Non_Terminals = {}

        def convert_rule(head: Element, body: List[Element]) -> None:
            """Recursively converts a rule to an annotated cost rule"""
            if head in annotated_non_terminals:
                return

            annotated_elements: List[Annotated_Element] = []

            is_inf = False

            for element in body:
                cost = 0
                non_terminals = re.findall(self._NON_TERMINAL_REGEX, element)

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
                annotated_non_terminals[head] = (
                    min(annotated_elements, key=lambda x: x[1])[1] + 1
                    if conversion_type == CostGrammarType.MIN
                    else max(annotated_elements, key=lambda x: x[1])[1] + 1
                )

        for key, value in grammar.items():
            convert_rule(key, value)

        return cost_grammar, annotated_non_terminals

    def __convert_to_trackable_grammar(
            self, grammar: Grammar
    ) -> Tuple[Annotated_Grammar, Annotated_Non_Terminals]:
        """Converts a common grammar to an annotated trackable grammar"""
        trackable_grammar: Annotated_Grammar = {}
        trackable_non_terminals: Annotated_Non_Terminals = {}

        def convert_rule(head: Element, body: List[Element]) -> None:
            """Recursively converts a rule to an annotated trackable rule"""
            if head in trackable_non_terminals:
                return

            trackable_elements: List[Annotated_Element] = []

            for element in body:
                non_terminals = re.findall(self._NON_TERMINAL_REGEX, element)

                for non_terminal in non_terminals:
                    if non_terminal not in trackable_non_terminals:
                        trackable_non_terminals[head] = 0

                trackable_elements.append((element, 0))

            trackable_grammar[head] = trackable_elements

        for key, value in grammar.items():
            convert_rule(key, value)

        return trackable_grammar, trackable_non_terminals

    def __compose_min_cost(
            self, head: Element, given_cost_grammar: Annotated_Grammar
    ) -> str:
        """Derives the first minimum cost value of a given annotated grammar."""
        min_tuple: Annotated_Element = min(given_cost_grammar[head], key=lambda x: x[1])
        is_non_terminal = (
            True if re.findall(self._NON_TERMINAL_REGEX, min_tuple[0]) else False
        )

        if not is_non_terminal:
            return min_tuple[0]
        else:
            non_terminals = re.findall(self._NON_TERMINAL_REGEX, min_tuple[0])
            replacements = iter(
                list(
                    map(
                        lambda element: self.__compose_min_cost(
                            element, given_cost_grammar
                        ),
                        non_terminals,
                    )
                )
            )
            result = re.sub(
                self._NON_TERMINAL_REGEX,
                lambda element: next(replacements),
                min_tuple[0],
            )
            return result

    def fuzz_min_cost(self, grammar: Grammar, start_symbol: Element) -> str:
        """Derives the first minimum cost value of a given grammar."""
        cost_grammar: Annotated_Grammar
        cost_grammar, _ = self.__convert_to_cost_grammar(grammar, CostGrammarType.MIN)

        return self.__compose_min_cost(start_symbol, cost_grammar)

    def __compose_max_cost(
            self,
            head: Element,
            given_cost_grammar: Annotated_Grammar,
            applications: int,
            max_applications: int,
    ) -> str:
        """Derives a maximum cost value of a given grammar."""

        if applications == max_applications:
            min_tuple: Annotated_Element = min(
                sample(given_cost_grammar[head], len(given_cost_grammar[head])), key=lambda x: x[1]
            )
            is_non_terminal = (
                True if re.findall(self._NON_TERMINAL_REGEX, min_tuple[0]) else False
            )

            if not is_non_terminal:
                return min_tuple[0]
            else:
                non_terminals = re.findall(self._NON_TERMINAL_REGEX, min_tuple[0])
                replacements = iter(
                    list(
                        map(
                            lambda element: self.__compose_max_cost(
                                element,
                                given_cost_grammar,
                                applications,
                                max_applications,
                            ),
                            non_terminals,
                        )
                    )
                )
                result = re.sub(
                    self._NON_TERMINAL_REGEX,
                    lambda element: next(replacements),
                    min_tuple[0],
                )
                return result
        else:
            max_tuple: Annotated_Element = max(
                given_cost_grammar[head], key=lambda x: x[1]
            )
            is_non_terminal = (
                True if re.findall(self._NON_TERMINAL_REGEX, max_tuple[0]) else False
            )

            if not is_non_terminal:
                return max_tuple[0]
            else:
                non_terminals = re.findall(self._NON_TERMINAL_REGEX, max_tuple[0])
                replacements = iter(
                    list(
                        map(
                            lambda element: self.__compose_max_cost(
                                element,
                                given_cost_grammar,
                                applications + 1,
                                max_applications,
                            ),
                            non_terminals,
                        )
                    )
                )
                result = re.sub(
                    self._NON_TERMINAL_REGEX,
                    lambda element: next(replacements),
                    max_tuple[0],
                )
                return result

    def fuzz_max_cost(
            self, grammar: Grammar, start_symbol: Element, max_rule_applications: int
    ) -> str:
        """Derives the first maximum cost value of a given grammar."""
        cost_grammar: Annotated_Grammar
        cost_grammar, _ = self.__convert_to_cost_grammar(grammar, CostGrammarType.MAX)

        return self.__compose_max_cost(
            start_symbol, cost_grammar, 0, max_rule_applications
        )

    def __is_grammar_covered(
            self,
            trackable_grammar: Annotated_Grammar,
            trackable_non_terminals: Annotated_Non_Terminals,
    ) -> bool:
        """Checks whether a given grammar is completely covered."""
        for non_terminal in trackable_non_terminals:
            if non_terminal[1] == 0:
                return False

        for rule in trackable_grammar:
            for element in trackable_grammar[rule]:
                if element[1] == 0:
                    return False

        return True

    def fuzz_grammar_coverage(
            self, grammar: Grammar, start_symbol: Element
    ) -> List[str]:
        """Derives values until each production rule is fully covered."""
        trackable_grammar: Annotated_Grammar
        trackable_non_terminals: Annotated_Non_Terminals
        trackable_grammar, trackable_non_terminals = (
            self.__convert_to_trackable_grammar(grammar)
        )

        fuzzed_values: List[str] = []

        def generate_value(head: Element):
            """Recursively generates values until each production rule is fully covered."""
            min_tuple: Annotated_Element = min(
                trackable_grammar[head], key=lambda x: x[1]
            )
            is_non_terminal = (
                True if re.findall(self._NON_TERMINAL_REGEX, min_tuple[0]) else False
            )
            trackable_grammar[head] = list(
                map(
                    lambda element: (
                        element
                        if element[0] != min_tuple[0]
                        else (element[0], element[1] + 1)
                    ),
                    trackable_grammar[head],
                )
            )

            if not is_non_terminal:
                return min_tuple[0]
            else:
                trackable_non_terminals[head] = min_tuple[1] + 1
                non_terminals = re.findall(self._NON_TERMINAL_REGEX, min_tuple[0])
                replacements = iter(
                    list(map(lambda element: generate_value(element), non_terminals))
                )
                result = re.sub(
                    self._NON_TERMINAL_REGEX,
                    lambda element: next(replacements),
                    min_tuple[0],
                )
                return result

        while not self.__is_grammar_covered(trackable_grammar, trackable_non_terminals):
            fuzzed_values.append(generate_value(start_symbol))

        return fuzzed_values
