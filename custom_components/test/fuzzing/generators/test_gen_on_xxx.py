import pytest
import logging

from custom_components.test.fuzzing.fuzzer_utils import ValuePoolFuzzer
from custom_components.test.fuzzing.fuzzer_utils import GeneratorFuzzer
from custom_components.test.fuzzing.fuzzer_utils import GeneratorRunner
import DummyClass


logger = logging.getLogger(__name__)

value_pool_fuzzer = ValuePoolFuzzer()
generator_fuzzer = GeneratorFuzzer(value_pool_fuzzer)
generator_runner = GeneratorRunner()

@pytest.mark.timeout(300)
def test_DummyClass() -> None:
    logger.info("Start of DummyClass test.")
    # Define the start methods and parameters for fuzzing
    start_methods = ['increment', 'multiply', 'reset', 'echo', 'divide']
    sequence_length = 3
    num_sequences = 5
    
    # Generate fuzzed sequences
    fuzzed_sequences = generator_fuzzer.fuzz(DummyClass, start_methods, sequence_length, num_sequences)
    
    # run the sequences on ExampleClass
    results = generator_runner.run(DummyClass, fuzzed_sequences)
    
    # Print the results
    for result in results:
        print(result)
        
    logger.info("DummyClass test finished.")
