"""Synthetic SDP and asynchronous signalling peers shared by Intercom tests."""

import asyncio
import json
from types import SimpleNamespace

import aiohttp

OFFER = "\r\n".join(
    [
        "v=0",
        "o=- 123 2 IN IP4 127.0.0.1",
        "s=-",
        "t=0 0",
        "a=group:BUNDLE audio video",
        "m=audio 9 UDP/TLS/RTP/SAVPF 0",
        "a=mid:audio",
        "a=recvonly",
        "a=ice-ufrag:audioU",
        "a=ice-pwd:audioPassword",
        "m=video 9 UDP/TLS/RTP/SAVPF 99",
        "a=mid:video",
        "a=recvonly",
        "a=ice-ufrag:videoU",
        "a=ice-pwd:videoPassword",
        "",
    ]
)

VIDEO_ANSWER = "\r\n".join(
    [
        "v=0",
        "o=- 456 2 IN IP4 127.0.0.1",
        "s=-",
        "t=0 0",
        "a=ice-ufrag:remoteU",
        "m=video 9 UDP/TLS/RTP/SAVPF 99",
        "a=mid:0",
        "a=sendonly",
        "",
    ]
)

COMBINED_ANSWER = VIDEO_ANSWER + "\r\n".join(["m=audio 9 UDP/TLS/RTP/SAVPF 0", "a=mid:1", "a=sendrecv", ""])


class Socket:
    """A framed, asynchronous peer whose responses arrive independently of writes."""

    def __init__(self):
        self.closed = False
        self.incoming = asyncio.Queue()
        self.sent = []
        self.close_count = 0

    async def send_json(self, message):
        self.sent.append(message)

    def feed(self, message):
        self.incoming.put_nowait(SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=json.dumps(message)))

    async def receive_json(self):
        message = await self.incoming.get()
        return json.loads(message.data)

    async def close(self):
        self.close_count += 1
        self.closed = True
        self.incoming.put_nowait(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.incoming.get()
        if value is None:
            raise StopAsyncIteration
        return value


class NegotiatingSocket(Socket):
    """Authenticate and answer the device protocol without replacing integration code."""

    def __init__(self, challenge, *, reject_auth=False):
        super().__init__()
        self.reject_auth = reject_auth
        self.feed({"jsonrpc": "2.0", "id": 0, "method": "authenticate", "params": challenge})

    async def send_json(self, message):
        await super().send_json(message)
        method = message.get("method")
        if method is None:
            self.feed({"error": {"code": 401}} if self.reject_auth else {"method": "ready"})
            return
        data = None
        if method == "info":
            data = {"callState": 0}
        elif method == "call":
            if message["params"][1] == "new":
                data = {"type": "answer", "sdp": VIDEO_ANSWER}
            else:
                # Arrives before the answer, exercising the real candidate buffer.
                self.feed({"method": "addIceCandidate", "params": ["candidate:door-audio", 1, "1"]})
                data = {"type": "answer", "sdp": COMBINED_ANSWER}
        self.feed({"id": message["id"], "result": {"code": 200, "data": data}})
