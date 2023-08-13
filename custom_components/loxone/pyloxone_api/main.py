import asyncio


from miniserver import Miniserver


async def connect_to_websocket(host, port, user, password, use_websockets=True):
    pass
    m = Miniserver(host, port, user, password, use_websockets=use_websockets)
    await m.connect()

    # websocket_proxy = WebSocketProxy(url, use_websockets)
    # await websocket_proxy.connect()

    # message_handler = MessageHandler(websocket_proxy)
    # async for message in websocket_proxy.receive():
    #    await message_handler.handle_message(message)


import logging

logging.basicConfig(format="%(name)s.%(levelname)s: %(message)s", level=logging.DEBUG)

# Usage example:
# url = "wss://your_server_url"
host = "192.168.1.225"
# host = "0.0.0.0"
port = 8080
user = "admin"
password = "ZennAlles6789"
use_websockets = True  # Set this to False to use aiohttp instead
asyncio.get_event_loop().run_until_complete(
    connect_to_websocket(host, port, user, password, use_websockets)
)
