# Dummy class for testing
class DummyClass:
    def __init__(self, value: int):
        self.value = value

    def increment(self, amount: int) -> int:
        """Increment the value by a given amount."""
        self.value += amount
        return self.value

    def multiply(self, factor: float) -> float:
        """Multiply the value by a given factor."""
        self.value *= factor
        return self.value

    def reset(self) -> None:
        """Reset the value to zero."""
        self.value = 0

    def echo(self, message: str) -> str:
        """Return the given message."""
        return message

    def divide(self, divisor: float) -> float:
        """Divide the value by the given divisor."""
        if divisor == 0:
            raise ValueError("Cannot divide by zero")
        self.value /= divisor
        return self.value