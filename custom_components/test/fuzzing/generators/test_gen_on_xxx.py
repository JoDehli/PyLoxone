import pytest
import logging

from custom_components.test.fuzzing.fuzzer_utils.ValuePoolFuzzer import ValuePoolFuzzer
from custom_components.test.fuzzing.fuzzer_utils.GeneratorFuzzer import GeneratorFuzzer
from custom_components.test.fuzzing.fuzzer_utils.GeneratorRunner import GeneratorRunner
import DummyClass


# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fuzzing and Runner setup
value_pool_fuzzer = ValuePoolFuzzer()
generator_fuzzer = GeneratorFuzzer(value_pool_fuzzer)
generator_runner = GeneratorRunner()

@pytest.mark.timeout(300)
def test_DummyClass() -> None:
    logger.info("Start of DummyClass test.")
    
    # Define the start methods and parameters for fuzzing
    start_methods = ['__init__']
    max_sequence_length = 4
    num_sequences = 10
    
    # Generate fuzzed sequences
    fuzzed_sequences = generator_fuzzer.fuzz(DummyClass, start_methods, max_sequence_length, num_sequences)
    
    # Run the sequences on DummyClass
    results = generator_runner.run(DummyClass, fuzzed_sequences)
    
    # Extract passed and failed test counts
    passed_tests, failed_tests = results
    
    # Log the results
    logger.info(f"Passed tests: {passed_tests}, Failed tests: {failed_tests}")
    
    # Assert that at least some tests passed
    assert passed_tests > 0, "No tests passed."
    
    logger.info("DummyClass test finished.")

# Running the test if the script is executed directly (optional)
if __name__ == "__main__":
    pytest.main()
