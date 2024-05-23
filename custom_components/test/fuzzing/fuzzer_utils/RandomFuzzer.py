from custom_components.test.fuzzing.fuzzer_utils.Fuzzer import Fuzzer


class Random(Fuzzer):
    """Random fuzzer class, inherits from the abstract fuzzer class."""

    def __int__(self):
        """constructor"""
        pass

    def fuzz(self) -> list:
        """Not implemented!"""
        raise Exception("The random fuzzer is not implemented!")
