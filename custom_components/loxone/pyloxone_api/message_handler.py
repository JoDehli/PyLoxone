import asyncio
import json
import logging
import traceback
import uuid

from .const import CMD_ENABLE_UPDATES, PERMISSION, CMD_GET_JWT
from .loxone_types import MiniserverProtocol
from .message import (
    MessageType,
    parse_header,
    parse_message,
    TextMessage,
    ValueStatesTable,
    TextStatesTable,
    Keepalive,
)

_LOGGER = logging.getLogger(__name__)


class LoxoneMessageHandlerMixin(MiniserverProtocol):
    async def handle_message(self, message) -> None:
        try:
            if isinstance(message, bytes) and len(message) == 8 and message[0] == 3:
                self.message_header = parse_header(message)
            else:
                if isinstance(message, str) and message.startswith("{"):
                    mess_obj = parse_message(message, self.message_header.message_type)
                elif isinstance(message, bytes):
                    mess_obj = parse_message(message, self.message_header.message_type)
                else:
                    raise NotImplementedError("Decryption not implemented yet")

                if hasattr(mess_obj, "control") and mess_obj.control.find("/enc/") > -1:
                    raise NotImplementedError("!!!!! decrypt not implented yet !!!!")
                    # mess_obj.control = self._decrypt(mess_obj.control)

                # if self.message_header == 1 and mess_obj == 1:
                _LOGGER.debug(f"Message Header {self.message_header.message_type.name}")
                # print("MESSAGE OBj", mess_obj)

                if isinstance(mess_obj, TextMessage) and "getkey2" in mess_obj.message:
                    self._key = mess_obj.value_as_dict["key"]
                    self._user_salt = mess_obj.value_as_dict["salt"]
                    self._hash_alg = mess_obj.value_as_dict.get("hashAlg", None)
                    new_hash = self._hash_credentials()
                    command = f"{CMD_GET_JWT}/{new_hash}/{self._user}/{PERMISSION}/{uuid.UUID(int=uuid.getnode())}/pyloxone_api"
                    await self._send_text_command(command, encrypted=True)

                elif isinstance(mess_obj, TextMessage) and (
                    "gettoken" in mess_obj.message or "getjwt" in mess_obj.message
                ):
                    self._token.token = mess_obj.value_as_dict["token"]
                    self._token.valid_until = mess_obj.value_as_dict["validUntil"]
                    self._token.key = mess_obj.value_as_dict["key"]
                    self._token.hash_alg = self._hash_alg
                    if "unsecurePass" in mess_obj.value_as_dict:
                        self._token.unsecure_password = mess_obj.value_as_dict[
                            "unsecurePass"
                        ]

                    self._safe_to_path(self._token_path)

                    await self._send_text_command(
                        f"{CMD_ENABLE_UPDATES}", encrypted=True
                    )

                elif isinstance(mess_obj, TextMessage) and "keyexchange" in mess_obj.message:
                    # TODO: HIER WEITER MIT keyexchange!!!!
                    print(mess_obj.as_dict())

                elif isinstance(mess_obj, ValueStatesTable):
                    print(mess_obj.as_dict())
                    # if self.message_call_back:
                    #    await self.message_call_back(mess_obj.as_dict())

                elif isinstance(mess_obj, TextStatesTable):
                    print(mess_obj.as_dict())
                    # if self.message_call_back:
                    #   await self.message_call_back(mess_obj.as_dict())
                elif isinstance(mess_obj, Keepalive):
                    _LOGGER.debug("Got Keepalive")

                else:
                    _LOGGER.debug("Process <UNKNOWN> response")
                    _LOGGER.debug(mess_obj)
                    _LOGGER.debug(mess_obj.message)

        except:
            import traceback

            traceback.print_exc()
            print("d")
            # if message.startswith("{"):
            #    mess_obj = parse_message(message, self.message_header.message_type)
            # print("mess_obj", mess_obj.value)

            # if hasattr(mess_obj, "control") and mess_obj.control.find("/enc/") > -1:
            #    mess_obj.control = self._decrypt(mess_obj.control)

            # if isinstance(mess_obj, TextMessage) and "keyexchange" in mess_obj.message:


# class MessageHandler:
#
#     def __init__(self, websocket):
#         self.websocket = websocket
#         self._current_header = None
#
#     async def handle_message(self, message):
#         # Implement your logic here to handle different message types
#         # For simplicity, let's assume the message is a JSON object
#
#         if isinstance(message, bytes) and len(message) == 8:
#             self._current_header = parse_header(message)
#
#         elif isinstance(message, str):
#             _LOGGER.debug(
#                 f"Parsing message {message[:80]!r} ({self._current_header.message_type})"
#             )
#             if self._current_header.message_type == MessageType.TEXT:
#                 self.handle_text_message(message)
#
#     # try:
#     #     data = json.loads(message)
#     #     message_type = data.get("type")
#     #     if message_type == "text":
#     #         self.handle_text_message(data)
#     #     elif message_type == "image":
#     #         self.handle_image_message(data)
#     #     else:
#     #         self.handle_unknown_message(data)
#     # except json.JSONDecodeError:
#     #     self.handle_invalid_message(message)
#
#     def handle_text_message(self, data):
#         print("Received text message:", data)
#         message = parse_message(data, self._current_header.message_type)
#         print("Received text message:", data)
#
#         # Example of sending a response message back to the WebSocket connection
#         # response = {"type": "response", "content": "Received your text message"}
#         # asyncio.create_task(self.websocket.send(json.dumps(response)))
#
#     def handle_image_message(self, data):
#         print("Received image message:", data)
#         # Example of sending a response message back to the WebSocket connection
#         response = {"type": "response", "content": "Received your image message"}
#         asyncio.create_task(self.websocket.send(json.dumps(response)))
#
#     def handle_unknown_message(self, data):
#         print("Received unknown message type:", data)
#
#     def handle_invalid_message(self, message):
#         print("Received invalid JSON message:", message)
