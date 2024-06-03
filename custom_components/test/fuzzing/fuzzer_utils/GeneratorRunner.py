import logging

from custom_components.test.fuzzing.fuzzer_utils.Runner import Runner


class GeneratorRunner(Runner):
    """Generator runner class, inherits from the abstract runner class."""

    def __init__(self):
        """constructor"""
        pass

    def run(self, function: function) -> list:
        """__summary__

        TODO: @JKortmann implement function
        TODO: @JKortmann add comments and update UML if necessary

        :param function: The passed function which is to be fuzzed. @JKortmann Man müsste hier doch eine ganze Klasse übergeben?
        :type function: function

        :return: Returns a list with two integers, the first number retruns the number of passed tests and the second of failed
        :rtype: list
        """
        # INFO
        logger = logging.getLogger(__name__)
        logger.debug("This is a DEBUG message.")
        logger.info("This is a INFO message.")
        logger.warning("This is a WARNING message.")
        logger.error("This is a ERROR message.")

        dummy_result = [6, 3]
        return dummy_result
