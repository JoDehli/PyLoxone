"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""


import logging

from .miniserver import Miniserver  # noqa

__all__ = [
    "Miniserver",
]

_LOGGER = logging.getLogger(__name__)
