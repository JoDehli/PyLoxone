from custom_components.test.fuzzing.fuzzer_utils import ValuePoolFuzzer
from custom_components.test.fuzzing.fuzzer_utils import GeneratorFuzzer
from custom_components.test.fuzzing.fuzzer_utils import GeneratorRunner
import DummyClass

# Instantiate the ValuePoolFuzzer
value_pool_fuzzer = ValuePoolFuzzer()

# Create the GeneratorFuzzer with the ValuePoolFuzzer
generator_fuzzer = GeneratorFuzzer(value_pool_fuzzer)

# Define the start methods and parameters for fuzzing
start_methods = ['increment', 'multiply', 'reset', 'echo', 'divide']
sequence_length = 3
num_sequences = 5

# Generate fuzzed sequences
fuzzed_sequences = generator_fuzzer.fuzz(DummyClass, start_methods, sequence_length, num_sequences)

# Instantiate the GeneratorRunner and run the sequences on ExampleClass
generator_runner = GeneratorRunner()
results = generator_runner.run(DummyClass, fuzzed_sequences)

# Print the results
for result in results:
    print(result)
