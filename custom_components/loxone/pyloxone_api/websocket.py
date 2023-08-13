import asyncio
import urllib.parse
from base64 import b64encode
from typing import NoReturn

import websockets
from Crypto.Cipher import AES
from Crypto.Util import Padding

from loxone_types import MiniserverProtocol
from message import TextMessage

# class LoxoneWebSocket:
#     def __init__(self, url):
#         self.url = url
#         self.websocket = None
#         self._ping_timeout: int = 30


class WebsocketMixin(MiniserverProtocol):
    @property
    def websocket_is_open(self):
        if self._ws and self._ws.open:
            return True
        return False

    async def _open_web_socket_connection(self) -> None:
        try:
            # Start the WebSocket connection
            self._ws = await websockets.connect(self._url)
            # self.message_handler = MessageHandler(self.websocket)
            # Set up message handling and keep the connection alive
            # async for message in self.websocket:
            #    await self.on_message(message)

        except websockets.ConnectionClosedOK:
            # Connection closed gracefully
            await self.on_close()
        except websockets.ConnectionClosedError as e:
            await self.on_error(e)
        except Exception as e:
            await self.on_error(e)

    async def _send_text_command(
        self, command: str = "", encrypted: bool = False
    ) -> TextMessage:
        """Send a (text) command to the Miniserver, and return the response.

        If encrypted=True, the message will be encrypted, and will be sent using
        Loxone's 'jdev/sys/enc' command. We do not handle 'jdev/sys/fenc'
        full encryption, which encrypts the response as well.

        Miniserver gen 2 uses TLS, so most commands do not need encrypting. But
        some commands (to do with tokens) still seem to need it.

        """

        # expected_control = command
        if encrypted:
            if self._salt_has_expired:
                old_salt = self._salt
                self._generate_salt()
                # The miniserver needs the text terminated with a zero byte,
                # though this is not documented
                command_string = f"nextsalt/{old_salt}/{self._salt}/{command}\x00"
            else:
                command_string = f"salt/{self._salt}/{command}\x00"
            padded_bytes = Padding.pad(bytes(command_string, "utf-8"), 16)
            aes_cipher = AES.new(self._aes_key, AES.MODE_CBC, self._iv)
            cipher = b64encode(aes_cipher.encrypt(padded_bytes))
            enc_cipher = urllib.parse.quote(cipher.decode())
            command = f"jdev/sys/enc/{enc_cipher}"

        await self._ws.send(command)

        # # According to the API docs, "The Miniserver will answer every command
        # # it receives, it will return a TextMessage as confirmation." The
        # # returned message will have a control attribute which should be the
        # # same as the command.
        # message = await self._get_message([MessageType.TEXT], expected_control)
        # assert isinstance(message, TextMessage)
        # # Sometimes the miniserver responds with "/dev ..." in the control,
        # # even though the command was "/jdev ...". We need to check for both.
        # if message.control not in [expected_control, expected_control[1:]]:
        #     raise LoxoneException(
        #         f"Expected {expected_control}, but received {message.control}"
        #     )
        # if message.code != 200:
        #     raise LoxoneCommandError(code=message.code, message=message.value)
        # return message

    async def enable_state_updates(self) -> None:
        """Tell the Miniserver to start sending binary update messages."""
        command = "jdev/sps/enablebinstatusupdate"
        # Gen 1 miniserver may require encryption here
        _ = await self._send_text_command(command)

    async def send_ws(self, command: str = ""):
        if self._ws and self._ws:
            await self._ws.send(command)

    async def listen_for_messages(self) -> NoReturn:
        try:
            async for message in self._ws:
                await self.on_message(message)
            # while True:
            #   ws_msg = await self.websocket.recv()
            #   await self.on_message(ws_msg)
            # async for message in self.websocket:
            #    print("message", message)
            # Keep the loop alive
            # await self.on_message(message)
        except websockets.ConnectionClosedOK:
            # Connection closed gracefully
            await self.on_close()
        except websockets.ConnectionClosedError as e:
            await self.on_error(e)
        except Exception as e:
            await self.on_error(e)
        finally:
            import traceback

            traceback.print_exc()
            if self._ws:
                await self._ws.close()

    async def ping_server(self):
        while True:
            # Send a ping message to the server
            try:
                await asyncio.sleep(self._ping_timeout)  # Send a ping every x seconds
                await self._ws.send("keepalive")
            except websockets.ConnectionClosedOK:
                # Connection closed gracefully, stop pinging
                break
            except websockets.ConnectionClosedError as e:
                # Handle any errors during the ping
                await self.on_error(e)
                break

    async def on_message(self, message) -> None:
        # Pass the message to the message handler
        # await self.message_handler.handle_message(message)
        await self.handle_message(message)

        # callback_coroutine = self.callback_coroutine()  # Get the callback coroutine

    async def on_error(self, error) -> None:
        # Handle any errors that occur
        print("Error:", error)

    async def on_close(self) -> None:
        # Handle the WebSocket connection close event
        print("Connection closed.")
