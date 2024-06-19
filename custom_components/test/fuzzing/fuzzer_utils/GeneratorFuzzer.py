import csv
import random
import inspect
import logging
from collections import defaultdict
from typing import Dict, List, Tuple, Type, Callable, Any, Union
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
        self.param_types = defaultdict(lambda: defaultdict(dict))
        self.param_types_file = "./custom_components/test/fuzzing/generators/param_types.csv"
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
        # Get the parameters of the method
        parameters = inspect.signature(method).parameters.items()

        # Filter out the "self" parameter
        filtered_parameters = [(param_name, param) for param_name, param in parameters if param_name != "self"]

        # Assign the param type for each parameter according to the mode we are using
        for i, (param_name, param) in enumerate(filtered_parameters):
            if param.annotation == param.empty or self.mode == 3:
                param_type = random.choice(['INT', 'UINT', 'FLOAT', 'STRING', 'BOOL', 'BYTE', 'LIST', 'DICT', 'DATE'])
                logging.warning(f"Randomly assigned type '{param_type}' for parameter {i+1} ({param_name}) in {class_name}.{method.__name__}")
            elif param.annotation.__name__ == 'str':
                param_type = 'STRING'
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
        methods = [method for method in dir(cls) if callable(getattr(cls, method)) and not method.startswith("__")]
        start_method = random.choice(start_methods)
        sequence = [start_method]
        for _ in range(random.randint(1, max_sequence_length - 1)):
            next_method = random.choice(methods)
            sequence.append(next_method)
        return sequence
    
    def _to_hashable_with_marker(self, data: Any) -> Union[Tuple[str, frozenset], Any]:
        """
        Convert a list or a dictionary to a hashable form (frozenset) with a type marker, or return other data types unchanged.

        :param data: The data to be converted to a frozenset form.
        :type data: Any
        :return: A tuple containing the type marker and the frozenset if 'data' is a list or a dictionary, otherwise 'data' itself.
        :rtype: Union[Tuple[str, frozenset], Any]
        """
        if isinstance(data, list):
            return ('list', frozenset(data))
        elif isinstance(data, dict):
            return ('dict', frozenset(data.items()))
        else:
            # If data is neither a list nor a dict, return it as is
            return data
        
    def _to_original_from_marker(self, data_with_marker: Union[Tuple[str, frozenset], Any]) -> Any:
        """
        Convert data back to its original form from a hashable form (frozenset) with a type marker, or return other data types unchanged.

        :param data_with_marker: The data to be converted back to its original form.
        :type data_with_marker: Union[Tuple[str, frozenset], Any]
        :return: The original data form if 'data_with_marker' had a type marker, otherwise 'data_with_marker' itself.
        :rtype: Any
        """
        # Check if data_with_marker is a tuple and has a type marker
        if isinstance(data_with_marker, tuple) and data_with_marker[0] in ('list', 'dict'):
            data_type, data = data_with_marker
            if data_type == 'list':
                return list(data)
            elif data_type == 'dict':
                return dict(data)
        else:
            # If there is no type marker, return the data as is
            return data_with_marker

    def fuzz(self, cls: Type, start_methods: List[str], max_sequence_length: int, num_sequences: int, max_param_combi: int = 2) -> List[List[Tuple[str, Tuple[Any]]]]:
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
        :param max_param_combi: Maximum number of parameter combinations. If a method takes less parameters the combinations will be decreased accordingly.
        :type param_combi: int
        :return: List of unique method sequences with parameters.
        :rtype: List[List[Tuple[str, Tuple[Any]]]]
        example return:
        [
            [('method1', (param1, param2)), ('method2', (param3, param4))],
            [('method3', (param5)), ('method4', (param6, param7))]
        ]  
        """
        existing_sequences = set()
        while len(existing_sequences) < num_sequences:
            sequence = self._generate_method_sequence(cls, start_methods, max_sequence_length)
            param_sequences = []
            for method_name in sequence:
                param_combi = max_param_combi
                method = getattr(cls, method_name)
                param_types = self._get_param_types(cls.__name__, method)
                if len(param_types) != 0:
                    # make sure we don't request more combinations than parameters available
                    if max_param_combi > len(param_types):
                        param_combi = len(param_types)
                    # Generate parameter sets using the value pool fuzzer 
                    param_set = self.value_pool_fuzzer.fuzz(param_nr=len(param_types), types=[param_types[i] for i in range(len(param_types))], param_combi=param_combi)
                    # Select a random parameter set from the generated combinations
                    random_param_set = random.choice(param_set)
                    param_sequences.append((method_name, random_param_set))
                else:
                    # don't generate any param_sets if we don't need any - would raise error when calling value_pool_fuzzer.fuzz
                    param_sequences.append((method_name, {}))
            # convert sequence list to tuple to make it hashable to be able to add it to existing_sequences set
            sequence_tuple = tuple(
                (
                    method_name, 
                    tuple(self._to_hashable_with_marker(param) for param in params)
                )
                for method_name, params in param_sequences
            )
            existing_sequences.add(sequence_tuple) # add the sequence_tuple to set to make sure we only have unique sequences
        # Return the sequences but revert the types back to their original
        return [
            [
                (method_name, tuple(self._to_original_from_marker(param) for param in params))
                for method_name, params in seq_tuple
            ]
            for seq_tuple in existing_sequences
        ]

