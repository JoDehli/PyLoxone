import pytest
import logging

from custom_components.test.fuzzing.fuzzer_utils.ValuePoolFuzzer import ValuePoolFuzzer
from custom_components.test.fuzzing.fuzzer_utils.GeneratorFuzzer import GeneratorFuzzer
from custom_components.test.fuzzing.fuzzer_utils.GeneratorRunner import GeneratorRunner
from custom_components.loxone.climate import LoxoneRoomControllerV2
from custom_components.loxone.api import LxToken

# Logger setup
logger = logging.getLogger(__name__)

# Fuzzing and Runner setup
value_pool_fuzzer = ValuePoolFuzzer()
generator_fuzzer = GeneratorFuzzer(value_pool_fuzzer, 2)
generator_runner = GeneratorRunner()

@pytest.mark.timeout(300)
def test_api_LxToken() -> None:
    logger.info("Start test of LxToken from api.py.")
    
    # Define the start methods and parameters for fuzzing
    start_methods = ['__init__']
    max_sequence_length = 8
    num_sequences = 50
    
    # Generate fuzzed sequences
    generated_sequences = generator_fuzzer.fuzz(LxToken, start_methods, max_sequence_length, num_sequences)
    
    # Run the sequences on LoxoneRoomControllerV2
    results = generator_runner.run(LxToken, generated_sequences)
    
    # Extract passed and failed test counts
    passed_tests, failed_tests = results
    
    # Log the results
    logger.info(f"Passed tests: {passed_tests}, Failed tests: {failed_tests}")
    
    logger.info("LxToken test finished.")
