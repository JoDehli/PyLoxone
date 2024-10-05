from abc import ABC, abstractmethod


class Runner(ABC):
    """Abstract class"""

    @abstractmethod
    def __init__(self):
        """Abstract method, must be overloaded by the corresponding fuzzer."""
        pass

    @abstractmethod
    def run(self):
        """Abstract method, must be overloaded by the corresponding fuzzer."""
        pass
