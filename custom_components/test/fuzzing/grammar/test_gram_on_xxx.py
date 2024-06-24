import logging
import pytest

from custom_components.test.fuzzing.fuzzer_utils.GrammarFuzzer import GrammarFuzzer
from custom_components.test.fuzzing.fuzzer_utils.grammars.grammar_ipv4 import (
    grammar_ipv4,
)

logger = logging.getLogger(__name__)
test_fuzzer = GrammarFuzzer()


@pytest.mark.skipif(True, reason="Only dummy test case.")
def test_dummy() -> None:
    logger.info("Start of dummy() test.")
    result = test_fuzzer.fuzz_min_cost(grammar_ipv4, "<IPv4>")
    assert result == "0.0.0.0"
    logger.info("dummy() test finished.")
