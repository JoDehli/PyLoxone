import csv
import random
import inspect
import logging
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Type, Callable, Any
from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer
from custom_components.test.fuzzing.fuzzer_utils import ValuePoolFuzzer

class GeneratorFuzzer(Fuzzer):
    def __init__(self, value_pool_fuzzer: ValuePoolFuzzer, mode: int = 1):
        """
        Initialize the GeneratorFuzzer.

        :param value_pool_fuzzer: Instance of ValuePoolFuzzer to generate parameter values.
        :type value_pool_fuzzer: ValuePoolFuzzer
        :param mode: Operating mode (1: use CSV, 2: no CSV but use specified types, 3: use only random types).
        :type mode: int
        """
        self.value_pool_fuzzer = value_pool_fuzzer
        self.param_types = defaultdict(dict)
        self.param_types_file = "param_types.csv"
        self.mode = mode
        if self.mode == 1:
            self._load_param_types()

    def _load_param_types(self) -> None:
        """
        Load parameter types from a CSV file into the param_types dictionary.
        """
        try:
            with open(self.param_types_file, mode='r') as file:
                reader = csv.reader(file)
                for row in reader:
                    class_name, method_name, param_index, param_type = row
                    self.param_types[class_name][method_name][int(param_index)] = param_type
        except FileNotFoundError:
            pass

    def _save_param_types(self) -> None:
        """
        Save the param_types dictionary to a CSV file.
        """
        with open(self.param_types_file, mode='w') as file:
            writer = csv.writer(file)
            for class_name, methods in self.param_types.items():
                for method_name, params in methods.items():
                    for param_index, param_type in params.items():
                        writer.writerow([class_name, method_name, param_index, param_type])

    def _assign_param_types(self, class_name: str, method: Callable) -> Dict[int, str]:
        """
        Assign types to parameters from the method signature. If not specified, the parameter type will be randomly assigned.

        :param class_name: Name of the class containing the method.
        :type class_name: str
        :param method: The method for which parameter types are being assigned.
        :type method: Callable
        :return: Dictionary of parameter indices and their assigned types.
        :rtype: Dict[int, str]
        """
        param_types = {}
        for i, (param_name, param) in enumerate(inspect.signature(method).parameters.items()):
            if param.annotation == param.empty or self.mode == 3:
                param_type = random.choice(['INT', 'UINT', 'FLOAT', 'STRING', 'BOOL', 'BYTE', 'LIST', 'DICT', 'DATE', 'ALL'])
                logging.warning(f"Randomly assigned type '{param_type}' for parameter {i+1} ({param_name}) in {class_name}.{method.__name__}")
            else:
                param_type = param.annotation.__name__.upper()
            param_types[i] = param_type
        if self.mode == 1:
            self.param_types[class_name][method.__name__] = param_types
            self._save_param_types()
        return param_types

    def _get_param_types(self, class_name: str, method: Callable) -> Dict[int, str]:
        """
        Get the parameter types for a method based on the operating mode.

        :param class_name: Name of the class containing the method.
        :type class_name: str
        :param method: The method for which parameter types are being retrieved.
        :type method: Callable
        :return: Dictionary of parameter indices and their types.
        :rtype: Dict[int, str]
        """
        if self.mode == 1 and class_name in self.param_types and method.__name__ in self.param_types[class_name]:
            return self.param_types[class_name][method.__name__]
        return self._assign_param_types(class_name, method)

    def _generate_method_sequence(self, cls: Type, start_methods: List[str], max_sequence_length: int) -> List[str]:
        """
        Generate a random method sequence with a length of up to max_sequence_length, starting with one of the start methods.

        :param cls: The class for which the method sequence is being generated.
        :type cls: Type
        :param start_methods: List of method names that can start the sequence.
        :type start_methods: List[str]
        :param max_sequence_length: The maximum length of the method sequence.
        :type max_sequence_length: int
        :return: List of method names forming the sequence.
        :rtype: List[str]
        """
        methods = [method for method in dir(cls) if callable(getattr(cls, method))]
        start_method = random.choice(start_methods)
        sequence = [start_method]
        for _ in range(random.randint(1, max_sequence_length - 1)):
            next_method = random.choice(methods)
            sequence.append(next_method)
        return sequence

    def fuzz(self, cls: Type, start_methods: List[str], max_sequence_length: int, num_sequences: int, param_combi: int = 1) -> List[List[Tuple[str, List[Any]]]]:
        """
        Generate unique method sequences with parameters. A sequence is unique if either the methods are chained differently or any value of any parameter differs from an otherwise identical sequence.

        :param cls: The class for which the method sequences are being generated.
        :type cls: Type
        :param start_methods: List of method names that can start the sequence.
        :type start_methods: List[str]
        :param max_sequence_length: The maximum length of the method sequences.
        :type max_sequence_length: int
        :param num_sequences: The number of unique sequences to generate.
        :type num_sequences: int
        :param param_combi: Maximum number of parameter combinations.
        :type param_combi: int
        :return: List of unique method sequences with parameters.
        :rtype: List[List[Tuple[str, List[Any]]]]
        example return:
        [
            [('method1', [param1, param2]), ('method2', [param3, param4])],
            [('method3', [param5]), ('method4', [param6, param7])]
        ]  
        """
        existing_sequences = set()
        while len(existing_sequences) < num_sequences:
            sequence = self._generate_method_sequence(cls, start_methods, max_sequence_length)
            param_sequences = []
            for method_name in sequence:
                method = getattr(cls, method_name)
                param_types = self._get_param_types(cls.__name__, method)
                param_set = self.value_pool_fuzzer.fuzz(param_nr=len(param_types), types=[param_types[i] for i in range(len(param_types))], param_combi=param_combi)
                # Select a random parameter set from the generated combinations
                random_param_set = random.choice(param_set)
                param_sequences.append((method_name, random_param_set))
            sequence_tuple = tuple((method_name, tuple(params)) for method_name, params in param_sequences)
            existing_sequences.add(sequence_tuple) # add the tuple of tuples if it is unique (set only contains unique entries)
        return [list(seq) for seq in existing_sequences]
