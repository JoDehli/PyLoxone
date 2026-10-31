"""Bounded HA-generated audio preparation and native temporary announcements."""

from __future__ import annotations

import asyncio
import io
from http import HTTPStatus
import sys
from typing import TYPE_CHECKING
import wave
from urllib.parse import urlsplit


from homeassistant.components import media_player, media_source
from homeassistant.helpers import aiohttp_client
from pyloxone_audio.announcement import async_send_prepared_announcement

from .pyloxone_api.audioserver import AudioCommandError as AudioCommandError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from .audio import AudioMetadataCoordinator
    from .pyloxone_api.audioserver import AudioServerCommands

MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 120


async def async_send_announcement(  # noqa: PLR0913 - existing host signature
    hass: HomeAssistant,
    commands: AudioServerCommands,
    metadata: AudioMetadataCoordinator,
    player_id: int,
    data: bytes,
    duration: float,
    volume: int,
) -> None:
    """Delegate native ownership; lazily supply HA's existing HTTP session."""
    await async_send_prepared_announcement(
        lambda: aiohttp_client.async_get_clientsession(hass),
        commands, metadata, player_id, data, duration, volume,
    )


async def async_prepare_announcement(
    hass: HomeAssistant,
    media_id: str,
    entity_id: str,
) -> tuple[bytes, float]:
    """Resolve HA-selected media without replacing its provider, voice or options."""
    async with asyncio.timeout(45):
        url = media_id
        if media_source.is_media_source_id(media_id):
            resolved = await media_source.async_resolve_media(hass, media_id, entity_id)
            url = resolved.url
        url = media_player.async_process_play_media_url(hass, url)
        if urlsplit(url).scheme not in ("http", "https"):
            message = "Announcements require resolved HTTP audio"
            raise ValueError(message)
        session = aiohttp_client.async_get_clientsession(hass)
        data = bytearray()
        async with session.get(
            url,
            allow_redirects=True,
            max_redirects=3,
            auto_decompress=False,
            headers={"Accept-Encoding": "identity"},
        ) as response:
            if (
                response.status != HTTPStatus.OK
                or response.headers.get("Content-Encoding", "identity").lower() != "identity"
            ):
                message = "Announcement audio is unavailable"
                raise ValueError(message)
            async for chunk in response.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data) > MAX_AUDIO_BYTES:
                    message = "Announcement audio is too large"
                    raise ValueError(message)
        return await async_announcement_wav(hass, bytes(data))


async def async_announcement_wav(hass: HomeAssistant, data: bytes) -> tuple[bytes, float]:
    """Decode bounded audio to a valid mono PCM WAV without files or network IO."""
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_AUDIO_BYTES:
        message = "Announcement audio is empty or too large"
        raise ValueError(message)
    binary = getattr(hass.data.get("ffmpeg"), "binary", "ffmpeg")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import os,resource,sys; "
        "resource.setrlimit(resource.RLIMIT_AS,(805306368,805306368)); "
        "resource.setrlimit(resource.RLIMIT_CPU,(15,16)); "
        "os.execvp(sys.argv[1],sys.argv[1:])",
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-max_alloc",
        "33554432",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-probesize",
        "1048576",
        "-analyzeduration",
        "5000000",
        "-protocol_whitelist",
        "pipe",
        "-i",
        "pipe:0",
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "24000",
        "-c:a",
        "pcm_s16le",
        "-t",
        str(MAX_AUDIO_SECONDS + 1),
        "-f",
        "s16le",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(20):
            pcm, _ = await process.communicate(data)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0 or not pcm or len(pcm) % 2 or len(pcm) > MAX_AUDIO_SECONDS * 48000:
        message = "Announcement audio cannot be decoded or exceeds two minutes"
        raise ValueError(message)
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(pcm)
    return output.getvalue(), len(pcm) / 48000
