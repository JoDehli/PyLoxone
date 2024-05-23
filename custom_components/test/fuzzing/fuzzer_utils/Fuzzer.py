from abc import ABC, abstractmethod


class Fuzzer(ABC):
    """Abstract class"""

    @abstractmethod
    def __int__(self):
        """Abstract method, must be overloaded by the corresponding fuzzer."""
        pass

    @abstractmethod
    def fuzz(self):
        """Abstract method, must be overloaded by the corresponding fuzzer."""
        pass
