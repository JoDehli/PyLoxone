from abc import ABC, abstractmethod


class Fuzzer(ABC):
    """Abstract class"""

    @abstractmethod
    def __init__(self):
        """Abstract method, must be overloaded by the corresponding fuzzer."""
        pass

    @abstractmethod
    def fuzz(self) -> list:
        """Abstract method, must be overloaded by the corresponding fuzzer."""
        pass
