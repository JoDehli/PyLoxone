"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

from __future__ import annotations

import logging
from typing import AsyncIterable, Iterable, Union

from websockets import ClientConnection

_LOGGER = logging.getLogger(__name__)

Data = Union[str, bytes]
"""Types supported in a WebSocket message:
:class:`str` for a Text_ frame, :class:`bytes` for a Binary_.

.. _Text: https://www.rfc-editor.org/rfc/rfc6455.html#section-5.6
.. _Binary : https://www.rfc-editor.org/rfc/rfc6455.html#section-5.6

"""


class LoxoneClientConnection(ClientConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def recv(self, decode: bool | None = False) -> str | bytes:
        result = await super().recv(decode)
        # Lazy %-args on purpose: this runs for **every** frame, so the
        # slice/repr must not be built unless DEBUG is enabled. G004
        # already bans the f-string variant — do not "simplify" it back.
        _LOGGER.debug("Received: %r", result[:80])
        return result

    async def send(
        self,
        message: Data | Iterable[Data] | AsyncIterable[Data],
        text: bool | None = None,
    ) -> None:
        # Lazy %-args (see ``recv``): the whole payload must not be
        # stringified per outgoing message; G004 bans the f-string form.
        _LOGGER.debug("Sent:%s", message)
        result = await super().send(message, text=text)
        return result
