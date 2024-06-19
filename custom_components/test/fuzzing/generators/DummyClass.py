class DummyClass:
    def __init__(self, value: int):
        """
        Initialize the class with an integer value.
        :param value: The initial integer value of the class instance.
        """
        self.value = value

    def increment(self, amount: int) -> int:
        """
        Increment the value by a given integer amount.
        :param amount: The integer amount to increment the value by.
        :return: The new integer value after incrementing.
        """
        self.value += amount
        return self.value

    def multiply(self, factor: float) -> float:
        """
        Multiply the value by a given float factor.
        :param factor: The float factor to multiply the value by.
        :return: The new float value after multiplication.
        """
        self.value *= factor
        return self.value

    def reset(self) -> None:
        """
        Reset the value to zero.
        """
        self.value = 0

    def echo(self, message: str) -> str:
        """
        Return the given string message.
        :param message: The string message to be returned.
        :return: The string message provided as input.
        """
        return message

    def divide(self, divisor: float) -> float:
        """
        Divide the value by the given float divisor.
        :param divisor: The float divisor to divide the value by.
        :return: The new float value after division.
        :raises ValueError: If the divisor is zero.
        """
        if divisor == 0:
            raise ValueError("Cannot divide by zero")
        self.value /= divisor
        return self.value

    def add_and_multiply(self, addend: int, multiplier: float) -> float:
        """
        Add an integer to the value and then multiply it by a float.
        :param addend: The integer number to add to the value.
        :param multiplier: The float number to multiply the value by after adding.
        :return: The new float value after addition and multiplication.
        """
        self.value += addend
        self.value *= multiplier
        return self.value

    def process_list(self, data_list: list) -> int:
        """
        Process a list of integers and return their sum.
        :param data_list: A list of integers to be processed.
        :return: The sum of the integers in the list.
        """
        return sum(data_list)
