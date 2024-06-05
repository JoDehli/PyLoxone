
import logging
import inspect

class GeneratorRunner(Runner):
    """Generator runner class, inherits from the abstract runner class."""

    def __init__(self):
        """Constructor"""
        pass

    def run(self, cls: Type, sequences: List[List[Tuple[str, List[List[Any]]]]]) -> List[Tuple[str, List[Any], str, str]]:
        """Run the generated sequences on the given class."""
        logger = logging.getLogger(__name__)
        results = []

        for sequence in sequences:
            instance = cls()  # Create an instance of the class
            for method_name, param_set in sequence:
                method = getattr(instance, method_name)
                sig = inspect.signature(method)
                num_params = len(sig.parameters)
                logger.info(f"Running {method_name} with {num_params} parameters")

                for params in param_set:
                    try:
                        method(*params)  # Run the method with the given parameters
                        logger.debug(f"Test passed with parameters: {params}")
                        results.append((method_name, params, "Passed", ""))
                    except Exception as e:
                        logger.error(f"Test failed with parameters: {params}. Exception: {e}")
                        results.append((method_name, params, "Failed", str(e)))

        return results