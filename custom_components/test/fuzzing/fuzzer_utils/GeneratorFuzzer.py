import csv
import random
import inspect
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Type, Callable, Any
from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer
from custom_components.test.fuzzing.fuzzer_utils import ValuePoolFuzzer

class GeneratorFuzzer(Fuzzer):
    def __init__(self, value_pool_fuzzer: ValuePoolFuzzer):
        self.value_pool_fuzzer = value_pool_fuzzer  # Reuse the value pool fuzzer implementation
        self.param_types = defaultdict(dict)  # Dictionary for storing parameter types for each class and method
        self.param_types_file = "param_types.csv"  # File to store and restore parameter types for each class and method
        self.load_param_types()  # Load parameter_types dict from CSV

    def load_param_types(self) -> None:
        """Load parameter types from a CSV file."""
        try:
            with open(self.param_types_file, mode='r') as file:
                reader = csv.reader(file)
                for row in reader:
                    class_name, method_name, param_index, param_type = row
                    self.param_types[class_name][method_name][int(param_index)] = param_type
        except FileNotFoundError:
            pass

    def save_param_types(self) -> None:
        """
        Save parameter types to a CSV file.
        This method writes the whole parameter_types dict to the file for each call.
        """
        with open(self.param_types_file, mode='w') as file:
            writer = csv.writer(file)
            for class_name, methods in self.param_types.items():
                for method_name, params in methods.items():
                    for param_index, param_type in params.items():
                        writer.writerow([class_name, method_name, param_index, param_type])

    def prompt_for_param_types(self, class_name: str, method: Callable) -> Dict[int, str]:
        """Prompt the user for parameter types if not specified."""
        param_types = {}
        for i, (param_name, param) in enumerate(inspect.signature(method).parameters.items()):
            if param.annotation == param.empty:
                param_type = input(f"Enter type for parameter {i+1} ({param_name}): ")
            else:
                param_type = param.annotation.__name__.upper()
            param_types[i] = param_type
        self.param_types[class_name][method.__name__] = param_types
        self.save_param_types()
        return param_types

    def get_param_types(self, class_name: str, method: Callable) -> Dict[int, str]:
        """Get the parameter types for a method, prompting the user if necessary."""
        if class_name in self.param_types and method.__name__ in self.param_types[class_name]:
            use_saved = input(f"Use saved types for {class_name}.{method.__name__}? (y/n): ").strip().lower()
            if use_saved == 'y':
                return self.param_types[class_name][method.__name__]
        return self.prompt_for_param_types(class_name, method)

    def generate_unique_sequence(self, cls: Type, start_methods: List[str], sequence_length: int, existing_sequences: Set[Tuple[str, ...]]) -> List[str]:
        """Generate a unique method sequence starting with one of the start methods."""
        methods = [method for method in dir(cls) if callable(getattr(cls, method))]
        while True: #generate sequences with length sequence length until we find one that is not in the existing_sequences set
            start_method = random.choice(start_methods)
            sequence = [start_method]
            for _ in range(sequence_length - 1):
                next_method = random.choice(methods)
                sequence.append(next_method)
            sequence_tuple = tuple(sequence)
            if sequence_tuple not in existing_sequences:
                existing_sequences.add(sequence_tuple)
                return sequence

    def fuzz(self, cls: Type, start_methods: List[str], sequence_length: int, num_sequences: int, param_combi: int = 1) -> List[List[Tuple[str, List[List[Any]]]]]:
        """Generate unique method sequences with parameters."""
        sequences = []
        existing_sequences = set()
        for _ in range(num_sequences):
            sequence = self.generate_unique_sequence(cls, start_methods, sequence_length, existing_sequences)
            param_sequences = []
            for method_name in sequence:
                method = getattr(cls, method_name)
                param_types = self.get_param_types(cls.__name__, method)
                param_set = self.value_pool_fuzzer.fuzz(param_nr=len(param_types), types=[param_types[i] for i in range(len(param_types))], param_combi=param_combi)
                param_sequences.append((method_name, param_set))
            sequences.append(param_sequences)
        return sequences
