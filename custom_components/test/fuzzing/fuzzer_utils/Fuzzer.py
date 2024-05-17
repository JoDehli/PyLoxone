from abc import ABC, abstractmethod


class Fuzzer(ABC):

    @abstractmethod
    def __int__(self):
        pass

    @abstractmethod
    def fuzz(self):
        pass
