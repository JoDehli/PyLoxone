"""Bounded Loxone JSON-RPC signalling and token challenge authentication."""

import asyncio
import base64
from collections.abc import Callable
import json
import logging
import os

import aiohttp
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad
from homeassistant.components.camera import WebRTCCandidate
from webrtc_models import RTCIceCandidateInit

from .errors import (
    IntercomAuthenticationError,
    IntercomBusyError,
    IntercomConnectionError,
    IntercomError,
    IntercomIceError,
    IntercomProtocolError,
)

_LOGGER = logging.getLogger(__name__)
OPEN_TIMEOUT = 12
RPC_TIMEOUT = 12
CLOSE_TIMEOUT = 3
MAX_PENDING_CANDIDATES = 128
MAX_CANDIDATE_SIZE = 8192


class IntercomSession:
    """One signalling socket and exactly the calls established on that socket."""

    def __init__(self, hass, client, url, credentials: Callable[[], tuple[str, str]], send_message):
        self.hass = hass
        self.client = client
        self.url = url
        self.credentials = credentials
        self.send_message = send_message
        self.ws = None
        self.reader = None
        self.pending = {}
        self.counter = 10
        self.answer_ready = asyncio.Event()
        self.closed = False
        self.plan = None
        self.remote_candidates = []
        self.has_call = False
        self.failure = None
        self.on_disconnect = None
        self._close_task = None

    def _background_task(self, coroutine, name):
        if self.hass is None:
            return asyncio.create_task(coroutine, name=name)
        return self.hass.async_create_background_task(coroutine, name)

    async def open(self):
        """Release a partially opened socket on failure or cancellation."""
        try:
            await self._async_open()
        except BaseException:
            await asyncio.shield(self.close())
            raise

    async def _async_open(self):
        """Bound connection, challenge and ready-message waits by one deadline."""
        if self.closed:
            raise IntercomConnectionError("Intercom session was closed")
        username, token = self.credentials()
        async with asyncio.timeout(OPEN_TIMEOUT):
            self.ws = await self.client.ws_connect(self.url, protocols=["webrtc-signaling"], heartbeat=20)
            if self.closed:
                await self.ws.close()
                raise IntercomConnectionError("Intercom session was closed")
            challenge = await self.ws.receive_json()
            if not isinstance(challenge, dict) or challenge.get("method") != "authenticate":
                raise IntercomProtocolError("Expected an Intercom authentication challenge")
            params = challenge.get("params")
            if (
                not isinstance(params, list)
                or len(params) < 3
                or not isinstance(params[0], str)
                or len(params[0]) > 1024
            ):
                raise IntercomProtocolError("Invalid Intercom authentication challenge")
            try:
                if len(params) > 3 and isinstance(params[3], str):
                    if len(params[3]) > 16384:
                        raise ValueError("Oversized public key")
                    # The device's PEM has no line breaks.
                    pem = params[3].replace("-----BEGIN PUBLIC KEY-----", "-----BEGIN PUBLIC KEY-----\n")
                    pem = pem.replace("-----END PUBLIC KEY-----", "\n-----END PUBLIC KEY-----")
                    key = RSA.import_key(pem)
                else:
                    if (
                        not isinstance(params[1], str)
                        or len(params[1]) > 2048
                        or not isinstance(params[2], str)
                        or len(params[2]) > 16
                    ):
                        raise ValueError("Oversized public key")
                    key = RSA.construct((int(params[1], 16), int(params[2], 16)))
                if key.size_in_bits() > 8192 or key.has_private():
                    raise ValueError("Invalid public key")
                aes_key, iv = os.urandom(32), os.urandom(16)
                encrypted_token = AES.new(aes_key, AES.MODE_CBC, iv).encrypt(pad(token.encode(), AES.block_size))
                encrypted_key = PKCS1_v1_5.new(key).encrypt(f"{aes_key.hex()}:{iv.hex()}:{params[0]}".encode())
            except (ValueError, TypeError, IndexError) as error:
                raise IntercomProtocolError("Invalid Intercom authentication challenge") from error
            await self.ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": challenge.get("id"),
                    "result": {
                        "code": 200,
                        "message": "Ok",
                        "data": [
                            username,
                            base64.b64encode(encrypted_key).decode(),
                            base64.b64encode(encrypted_token).decode(),
                        ],
                    },
                }
            )
            while True:
                message = await self.ws.receive_json()
                if not isinstance(message, dict):
                    raise IntercomProtocolError("Invalid Intercom authentication response")
                if message.get("method") == "ready":
                    break
                if "error" in message or message.get("method") == "authenticate":
                    raise IntercomAuthenticationError("Intercom token authentication failed")
                result = message.get("result")
                if isinstance(result, dict) and str(result.get("code", 200)) != "200":
                    raise IntercomAuthenticationError("Intercom token authentication failed")
        if self.closed:
            raise IntercomConnectionError("Intercom session was closed")
        self.reader = self._background_task(self._receive(), "loxone_intercom_signaling")

    async def request(self, method, params=None):
        """Bound both writing the RPC and waiting for its response."""
        if self.failure is not None:
            raise self.failure
        if (self.closed and method != "hangup") or self.ws is None or self.ws.closed:
            raise IntercomConnectionError("Intercom signalling is unavailable")
        if self.reader is not None and self.reader.done():
            raise IntercomConnectionError("Intercom signalling closed")
        self.counter += 1
        rpc_id = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[rpc_id] = future
        try:
            async with asyncio.timeout(RPC_TIMEOUT):
                await self.ws.send_json({"jsonrpc": "2.0", "method": method, "id": rpc_id, "params": params or []})
                result = await future
            if method == "call":
                self.has_call = True
            elif method == "hangup":
                self.has_call = False
            return result
        finally:
            self.pending.pop(rpc_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                # Covers a send failure racing with the receive loop's close.
                future.exception()

    def _candidate(self, params):
        if not isinstance(params, list) or not params:
            raise IntercomProtocolError("Invalid Intercom ICE candidate")
        item = params[0]
        if isinstance(item, str):
            item = {
                "candidate": item,
                "sdpMLineIndex": params[1] if len(params) > 1 else None,
                "sdpMid": params[2] if len(params) > 2 else None,
            }
        if not isinstance(item, dict) or not isinstance(item.get("candidate"), str):
            raise IntercomProtocolError("Invalid Intercom ICE candidate")
        if len(item["candidate"]) > MAX_CANDIDATE_SIZE:
            raise IntercomProtocolError("Intercom ICE candidate is too large")
        index, candidate_mid = item.get("sdpMLineIndex"), item.get("sdpMid")
        if self.plan is not None:
            index, candidate_mid = self.plan.remote_candidate_target(index, candidate_mid)
        return WebRTCCandidate(
            RTCIceCandidateInit(
                candidate=item["candidate"],
                sdp_mid=candidate_mid,
                sdp_m_line_index=index,
            )
        )

    async def _receive(self):
        failure = IntercomConnectionError("Intercom signalling connection closed")
        try:
            async for message in self.ws:
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                try:
                    msg = json.loads(message.data)
                except (ValueError, TypeError) as error:
                    raise IntercomProtocolError("Invalid Intercom signalling message") from error
                if not isinstance(msg, dict):
                    raise IntercomProtocolError("Invalid Intercom signalling message")
                if "method" not in msg:
                    rpc_id = msg.get("id")
                    if not isinstance(rpc_id, int) or isinstance(rpc_id, bool):
                        raise IntercomProtocolError("Invalid Intercom RPC response")
                    future = self.pending.get(rpc_id)
                    if future is None or future.done():
                        continue  # A late response to a cancelled/timed-out RPC.
                    result = msg.get("result")
                    if "error" in msg or not isinstance(result, dict) or str(result.get("code")) != "200":
                        error = msg.get("error")
                        code = (
                            error.get("code")
                            if isinstance(error, dict)
                            else result.get("code")
                            if isinstance(result, dict)
                            else None
                        )
                        if code in (486, "486"):
                            failure = IntercomBusyError("Intercom audio is in use; close other calls first")
                        elif code in (509, "509"):
                            failure = IntercomError("Intercom video stream limit reached; close other streams first")
                        elif code in (415, "415"):
                            failure = IntercomError("The Intercom does not support the requested media codecs")
                        else:
                            failure = IntercomProtocolError("Intercom rejected the signalling request")
                        future.set_exception(failure)
                    else:
                        future.set_result(result.get("data"))
                    continue
                method = msg["method"]
                if not isinstance(method, str):
                    raise IntercomProtocolError("Invalid Intercom notification")
                if method == "addIceCandidate":
                    candidate = self._candidate(msg.get("params"))
                    if self.answer_ready.is_set():
                        self.send_message(candidate)
                    elif len(self.remote_candidates) < MAX_PENDING_CANDIDATES:
                        self.remote_candidates.append(candidate)
                    else:
                        raise IntercomProtocolError("Too many Intercom ICE candidates")
                    if "id" in msg:
                        async with asyncio.timeout(RPC_TIMEOUT):
                            await self.ws.send_json(
                                {"jsonrpc": "2.0", "id": msg["id"], "result": {"code": 200, "message": "Ok"}}
                            )
                elif method == "noIceMatchFound":
                    raise IntercomIceError("Intercom could not establish the media connection")
                elif method in {"kick", "closeDueToNoDemand"}:
                    raise IntercomConnectionError("Intercom ended this media session")
                elif method == "onlineChanged" and msg.get("params") == [False]:
                    raise IntercomConnectionError("Intercom went offline")
        except asyncio.CancelledError:
            raise
        except IntercomError as error:
            failure = error
        except Exception:
            failure = IntercomConnectionError("Intercom signalling connection failed")
        finally:
            if not self.closed:
                self.failure = failure
            for future in tuple(self.pending.values()):
                if not future.done():
                    future.set_exception(failure)
            if not self.closed and self.on_disconnect is not None:
                try:
                    self.on_disconnect()
                except Exception as error:
                    _LOGGER.debug("Intercom disconnect callback failed (%s)", type(error).__name__)

    async def send_candidate(self, candidate):
        async with asyncio.timeout(RPC_TIMEOUT):
            await self.answer_ready.wait()
        if self.closed:
            return
        if candidate.candidate:
            if not isinstance(candidate.candidate, str) or len(candidate.candidate) > MAX_CANDIDATE_SIZE:
                raise IntercomProtocolError("Invalid browser ICE candidate")
            index = candidate.sdp_m_line_index
            if self.plan is not None:
                index = self.plan.local_candidate_target(index, candidate.sdp_mid)
            await self.request("addIceCandidate", [candidate.candidate, index])
        else:
            async with asyncio.timeout(RPC_TIMEOUT):
                await self.ws.send_json({"jsonrpc": "2.0", "method": "iceGatheringFinished"})

    def release_candidates(self):
        self.answer_ready.set()
        for candidate in self.remote_candidates:
            self.send_message(candidate)
        self.remote_candidates.clear()

    async def close(self):
        """Concurrent/cancelled closers share one bounded cleanup operation."""
        if self._close_task is None:
            self.closed = True
            self.answer_ready.set()
            self._close_task = self._background_task(self._async_close(), "loxone_intercom_close")
        await asyncio.shield(self._close_task)

    async def _async_close(self):
        try:
            if self.ws is not None and not self.ws.closed:
                if self.has_call and self.reader is not None and not self.reader.done() and self.failure is None:
                    try:
                        async with asyncio.timeout(CLOSE_TIMEOUT):
                            await self.request("hangup")
                    except (TimeoutError, RuntimeError, aiohttp.ClientError):
                        pass
                try:
                    async with asyncio.timeout(CLOSE_TIMEOUT):
                        await self.ws.close()
                except Exception as error:
                    _LOGGER.debug("Intercom socket close failed (%s)", type(error).__name__)
        finally:
            if self.reader is not None and self.reader is not asyncio.current_task():
                self.reader.cancel()
                await asyncio.gather(self.reader, return_exceptions=True)
            self.remote_candidates.clear()
            for future in tuple(self.pending.values()):
                if not future.done():
                    future.set_exception(IntercomConnectionError("Intercom session was closed"))
