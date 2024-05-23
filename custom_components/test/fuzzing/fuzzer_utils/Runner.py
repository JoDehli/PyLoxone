from abc import ABC, abstractmethod


class Runner(ABC):
    """Abstract class"""

    @abstractmethod
    def __int__(self):
        """Abstract method, must be overloaded by the corresponding fuzzer."""
        pass

    @abstractmethod
    def run(self):
        """Abstract method, must be overloaded by the corresponding fuzzer."""
        pass
