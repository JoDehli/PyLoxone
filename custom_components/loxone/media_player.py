"""Support for Loxone Audio zone media player."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import replace
from hashlib import sha256
import logging
from uuid import uuid4

from aiohttp import ClientError
from pyloxone_audio import selection as audio_selection
from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player import (
    BrowseError,
    BrowseMedia,
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
    RepeatMode,
    SearchError,
    SearchMedia,
    SearchMediaQuery,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from . import LoxoneEntity, audio_announcement, audio_sources
from .audio import AudioMetadataCoordinator
from .audio_artwork import decoded_cover, music_placeholder
from .audio_models import to_ha_browse, to_ha_search
from .audio_radio import RADIO_MEDIA_TYPE
from .audio_catalogue import BROWSE_ARTWORK, AudioCatalogue, CatalogueTarget

from .const import (
    CONF_AUDIOSERVER_HOST,
    CONF_AUDIOSERVER_PLAYBACK,
    DEFAULT_AUDIO_ZONE_V2_PLAY_STATE,
    DOMAIN,
    SENDDOMAIN,
)
from .helpers import add_room_and_cat_to_value_values, get_all, get_or_create_device
from .miniserver import get_miniserver_from_hass
from .pyloxone_api.audioserver import (
    AudioCommandError, AudioRepeatMode, AudioServerCommands, audio_mode_supported, audio_player_id,
)
from .spotify_continuity import (
    async_restore_dispatch_fences, spotify_room_uncertain,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from datetime import datetime
    from .audio_radio import RadioTarget
    from .pyloxone_api.audioserver import AudioZoneMetadata

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
DEFAULT_FORCE_UPDATE = False
ARTWORK_RETRY_SECONDS = 30

# This is the "optimistic" view of supported features and will be returned until the
# actual set of supported feature have been determined (will always be all or a subset
# of these).
SUPPORT_LOXONE_AUDIO_ZONE = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.STOP
)


def _state_uuid(states: dict, name: str) -> str | None:
    """Un-guarded ``states[name]`` indexing crashes the media player platform when a
    structure file omits an attribute; return ``None`` instead."""
    return states.get(name)


def play_state_to_media_player_state(play_state: int) -> MediaPlayerState:
    """Map a Loxone AudioZoneV2 ``playState`` value to the matching HA state.

    Unknown values fall back to ``IDLE`` (a non-playing state): the entity
    must never be left without a state just because the server sent a new
    value we do not know about.
    """
    match play_state:
        case 0:
            return MediaPlayerState.IDLE
        case 1:
            return MediaPlayerState.PAUSED
        case 2:
            return MediaPlayerState.PLAYING
        case -1:
            return MediaPlayerState.OFF
        case _:
            _LOGGER.debug("Unknown playState %r; defaulting to %s", play_state, MediaPlayerState.IDLE)
            return MediaPlayerState.IDLE


def audio_zone_stop_value() -> str:
    """Command value behind the ``STOP`` feature.

    AudioZoneV2 has no ``stop`` sub-command; pausing makes the zone silent,
    which is the closest stop semantic the device offers.
    """
    return "pause"


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Audio zones."""


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load Loxone Audio zones based on a config entry."""
    await async_restore_dispatch_fences(hass)
    miniserver = get_miniserver_from_hass(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    entities = []

    audio_metadata = None
    if host := config_entry.options.get(CONF_AUDIOSERVER_HOST):
        try:
            audio_metadata = AudioMetadataCoordinator(host)
        except ValueError:
            _LOGGER.warning("Invalid optional Audioserver host; keeping Miniserver-only media controls")
        else:
            hass.data[DOMAIN][config_entry.entry_id].audio_metadata = audio_metadata

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    diagnostics = getattr(coordinator, "audio_diagnostics", None)
    if audio_metadata is not None:
        audio_metadata.diagnostics = diagnostics
    playback_enabled = config_entry.options.get(CONF_AUDIOSERVER_PLAYBACK, False) is True
    audio_commands = None
    if playback_enabled:
        try:
            audio_commands = AudioServerCommands(
                config_entry.options.get(CONF_AUDIOSERVER_HOST, ""),
                lambda: (config_entry.options.get("username", ""), coordinator.api.get_token_dict().get("token", "")),
            )
        except ValueError:
            _LOGGER.warning("Optional Audio Server playback unavailable; play/pause will not fall back to room start")
        else:
            coordinator.audio_commands = audio_commands
            audio_commands.diagnostics = diagnostics


    for audioZone in get_all(loxconfig, "AudioZoneV2"):
        audioZone = add_room_and_cat_to_value_values(loxconfig, audioZone)
        audioZone.update(
            {
                "hass": hass,
            }
        )
        entities.append(
            LoxoneAudioZoneV2(
                audio_metadata=audio_metadata,
                audio_commands=audio_commands,
                audio_commands_enabled=playback_enabled,

                **audioZone,
            )
        )

    async_add_entities(entities)
    if audio_metadata is not None:
        audio_metadata.async_start(hass, config_entry)


class LoxoneAudioZoneV2(LoxoneEntity, MediaPlayerEntity):
    """Representation of a AudioZoneV2 Loxone device."""

    def __init__(
        self,
        audio_metadata: AudioMetadataCoordinator | None = None,
        *,
        audio_commands: AudioServerCommands | None = None,
        audio_commands_enabled: bool = False,

        **kwargs: Any,
    ) -> None:
        """Retain native controls and optionally bind an exact metadata player ID."""
        super().__init__(**kwargs)
        self.hass = kwargs["hass"]

        self._attr_device_class = MediaPlayerDeviceClass.SPEAKER
        self._state = play_state_to_media_player_state(DEFAULT_AUDIO_ZONE_V2_PLAY_STATE)
        self._volume = 0
        self._audio_metadata = audio_metadata
        self._audio_commands = audio_commands
        self._audio_commands_enabled = audio_commands_enabled
        self._announcement_task = None
        self._source_task = None
        self._source_generation = 0
        self._source_target = None
        self._source_feedback = None
        self._source_return_rejection = None
        self._transport_tasks: set[asyncio.Task] = set()
        self._discovery_tasks: set[asyncio.Task] = set()
        self._source_favourites = ()
        self._attr_source_list = None
        self._audio_sources_ready = False
        self._audio_removed = False
        self._audio_timing_sample = None
        self._audio_timing_identity = None
        self._audio_track_revision = 0
        self._cover_lock = asyncio.Lock()
        self._cover_cache = None
        self._cover_metadata_hash = None
        self._cover_retry_cancel: Callable[[], None] | None = None
        self._audio_timing_mode = None
        details = kwargs.get("details")
        self._audio_player_id = audio_player_id(details.get("playerid")) if isinstance(details, dict) else None
        self._radio_catalogue = (
            AudioCatalogue(audio_commands, self._audio_player_id)
            if audio_commands_enabled and audio_commands is not None and self._audio_player_id is not None else None
        )


        self.type = "AudioZoneV2"
        self._attr_device_info = get_or_create_device(self.unique_id, self.name, self.type, self.room)

    async def async_added_to_hass(self) -> None:
        """Keep the existing Miniserver listener and add exact-player metadata."""
        # Registry entity-ID changes remove and re-add this same instance.
        await async_restore_dispatch_fences(self.hass)
        self._audio_removed = False

        await super().async_added_to_hass()
        if self._audio_metadata is not None and self._audio_player_id is not None:
            self.async_on_remove(
                self._audio_metadata.async_add_listener(self._audio_player_id, self._update_audio_metadata)
            )
            self._update_audio_metadata()
        if self._can_announce():
            await self._async_refresh_audio_sources()

    @asynccontextmanager
    async def _async_discovery(self) -> AsyncIterator[None]:
        """Own read-only requests as well as playback during entity removal."""
        if self._audio_removed:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        task = asyncio.current_task()
        self._discovery_tasks.add(task)
        try:
            yield
            if self._audio_removed:
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        finally:
            self._discovery_tasks.discard(task)

    async def _async_refresh_audio_sources(self) -> None:
        """Keep optional startup discovery cancellable and entry-owned."""
        async with self._async_discovery():
            try:
                self._source_favourites = audio_sources.parse_room_favourites(
                    await self._audio_commands.async_room_favourites(self._audio_player_id), self._audio_player_id
                )
            except (AudioCommandError, ValueError, TimeoutError):  # fmt: skip
                _LOGGER.warning("Optional configured Audio Server favourites unavailable; keeping other controls")
            if self._radio_catalogue is not None:
                await self._async_refresh_native_sources()

    async def _async_refresh_native_sources(self) -> None:
        """Allow a later browse to recover optional startup discovery, without polling."""
        self._audio_sources_ready = False
        try:
            await self._radio_catalogue.async_refresh_sources()
            self._attr_source_list = list(self._radio_catalogue.previous_source_labels) or None
            self._audio_sources_ready = self._radio_catalogue.source_inventory_complete
        except (AudioCommandError, ValueError, TimeoutError):
            _LOGGER.warning("Optional native source history unavailable; keeping browse and other controls")
        finally:
            # Presence can be known even when optional content history fails.
            self._attr_source_list = list(self._radio_catalogue.previous_source_labels) or None

    async def async_will_remove_from_hass(self) -> None:
        """Cancel preparation/event waiting before removing this entity."""
        self._audio_removed = True
        self._cancel_cover_retry()
        self._cover_metadata_hash = None
        self._cover_cache = None
        self._source_generation += 1

        cancelled = False
        for task in {*self._discovery_tasks, *self._transport_tasks, self._announcement_task, self._source_task}:
            if task is not None and task is not asyncio.current_task():
                try:
                    await self._async_cancel_audio_task(task)
                except asyncio.CancelledError:
                    cancelled = True
        removal = asyncio.create_task(super().async_will_remove_from_hass())
        try:
            await self._async_cancel_audio_task(removal, cancel=False)
        except asyncio.CancelledError:
            cancelled = True
        removal.result()
        if cancelled:
            raise asyncio.CancelledError

    def _update_audio_metadata(self) -> None:
        """Clear attributes on stream loss without changing state or controls."""
        if self._audio_removed or self._audio_metadata is None or self._audio_player_id is None:
            return
        metadata = self._audio_metadata.get(self._audio_player_id)

        self._attr_shuffle = metadata.shuffle if metadata else None
        self._attr_repeat = (
            {AudioRepeatMode.OFF: RepeatMode.OFF, AudioRepeatMode.ALL: RepeatMode.ALL,
             AudioRepeatMode.ONE: RepeatMode.ONE}.get(metadata.repeat) if metadata else None
        )
        self._attr_media_title = metadata.title if metadata else None
        self._attr_media_artist = metadata.artist if metadata else None
        self._attr_media_album_name = metadata.album if metadata else None
        identity = audio_selection.native_track_identity(metadata)
        timing = (
            (identity, metadata.position, metadata.duration, metadata.received_at, metadata.playback_mode)
            if metadata else None
        )
        if identity != self._audio_timing_identity:
            self._audio_track_revision += 1
        if timing != self._audio_timing_sample:
            # Event-end callbacks retain the original wire sample. Reapplying
            # it would undo a newer native pause/resume clock adjustment.
            previous_timing = self._audio_timing_sample
            self._audio_timing_sample = timing
            if (
                metadata
                and (metadata.position == 0 or (
                    metadata.playback_mode in ("pause", "stop") and metadata.position is None
                ) or (
                    previous_timing is not None
                    and metadata.position is not None
                    and metadata.position == previous_timing[1]
                ))
                and identity is not None
                and identity == self._audio_timing_identity and self.media_position is not None
            ):
                # Zero placeholders and unchanged offsets aren't fresh clock
                # anchors. Pause can resend the old positive offset before its
                # corrected position; preserve elapsed time through that gap.
                # A changed positive offset (including a rewind) is accepted.
                self._freeze_audio_position(dt_util.utcnow())
            else:
                self._attr_media_position = metadata.position if metadata else None
                self._attr_media_duration = metadata.duration if metadata else None
                self._attr_media_position_updated_at = metadata.position_updated_at if metadata else None
            self._audio_timing_identity = identity
            self._audio_timing_mode = metadata.playback_mode if metadata else None
        # Match the tested pilot: HA's native music subtitle needs this hint.
        # Clear it on events, unsupported/unknown metadata and stream loss.
        self._attr_media_content_type = (
            MediaType.MUSIC
            if metadata
            and metadata.event_active is False
            and (
                metadata.artist
                or metadata.album
                or metadata.source in {"Spotify", "AirPlay", "TuneIn", "Loxone Radio"}
            )
            else None
        )
        self._attr_media_image_url = self._audio_metadata.artwork_url(metadata.cover_url if metadata else None)
        # A player-specific image endpoint can keep its URL when the track changes.
        # Event-only timer transitions must not invalidate unchanged artwork.
        artwork_metadata = (
            replace(metadata, event=None, event_active=None, position=None, duration=None,
                    position_updated_at=None, playback_mode=None, received_at=None, playback_restrictions=None,
                    native_mode=None, shuffle=None, repeat=None, shuffle_switch_supported=None)
            if metadata
            else None
        )
        metadata_hash = sha256(repr(artwork_metadata).encode()).hexdigest()
        if metadata_hash != self._cover_metadata_hash:
            self._cancel_cover_retry()
            self._cover_metadata_hash = metadata_hash
            self._cover_cache = None
            # A fresh generation also avoids a browser's old failed-cover cache
            # when the same track returns after reload or another source.
            self._attr_media_image_hash = f"{metadata_hash}-{uuid4().hex}"
        # Once an HA action settles, genuine other-app playback can become
        # last-good too. Unexpected identity changes need a second playing
        # sample: one delayed old reply must not replace a confirmed visit.
        previous = self._source_feedback
        settled = self._source_task is None
        eligible = audio_sources.passive_history_eligible(
            metadata, previous, settled=settled, initial_generation=self._source_generation == 0,
        )
        accept_return = True
        if settled and self._source_return_rejection is not None and metadata is not None:
            saved, rejected = self._source_return_rejection
            if metadata.source == saved.source and metadata.source_name == saved.source_name:
                identity = metadata.audio_path
                if metadata.audio_path == saved.audio_path and eligible:
                    self._source_return_rejection = None
                elif metadata.audio_path:
                    if rejected is None or identity == rejected:
                        # Continuing a rejected return is truthful now-playing,
                        # not permission to replace the preceding bookmark.
                        self._source_return_rejection = (saved, identity)
                        accept_return = False
                    elif eligible:
                        # A different later selection can qualify by the normal
                        # passive two-sample rule. This is not an issuer claim.
                        self._source_return_rejection = None
                    else:
                        accept_return = False
        source_label = self._radio_catalogue.remember_source(
            metadata, intent=None if settled else self._source_target,
            accept=accept_return and eligible,
        ) if self._radio_catalogue is not None else None
        self._source_feedback = metadata
        if self._radio_catalogue is not None:
            self._attr_source_list = list(self._radio_catalogue.previous_source_labels) or None
        self._attr_source = source_label or (metadata.source if metadata else None)
        # Preserve common Loxone attributes and native playback state. None is
        # unknown (including disconnect), not an observed event completion.
        self._attr_extra_state_attributes.update(
            audio_event=metadata.event if metadata else None,
            audio_event_active=metadata.event_active if metadata else None,
        )
        self.async_schedule_update_ha_state()

    async def async_get_media_image(self) -> tuple[bytes | None, str | None]:
        """Supply a valid native HA cover without global URL-only caching."""
        async with self._cover_lock:
            key = (self.media_image_url, self.media_image_hash)
            if self._cover_cache is not None and self._cover_cache[0] == key:
                return self._cover_cache[1]
            image = None
            if key[0] and not self._audio_removed:
                try:
                    content, _ = await self._async_fetch_image(key[0])
                    image = await self.hass.async_add_executor_job(decoded_cover, content)
                except (ClientError, TimeoutError):
                    pass
            if key != (self.media_image_url, self.media_image_hash) or self._audio_removed:
                # An older in-flight fetch must not paint over a new track.
                image = None
            elif image is not None:
                if self._cover_retry_cancel is not None:
                    # Another client can recover before the retry fires. Publish
                    # a new URL for browsers which already cached the fallback.
                    self._cancel_cover_retry()
                    self._attr_media_image_hash = f"{self._cover_metadata_hash}-{uuid4().hex}"
                    key = (self.media_image_url, self.media_image_hash)
                    self.async_schedule_update_ha_state()
                self._cover_cache = (key, image)
                return image
            elif key[0]:
                self._schedule_cover_retry(key)
            # Core caches successful image responses for an hour. A failed
            # endpoint gets one demand-triggered URL refresh, not network polling.
            return await self.hass.async_add_executor_job(music_placeholder)

    @callback
    def _cancel_cover_retry(self) -> None:
        """Cancel the single entity-owned image retry, if any."""
        if self._cover_retry_cancel is not None:
            self._cover_retry_cancel()
            self._cover_retry_cancel = None

    @callback
    def _schedule_cover_retry(self, key: tuple[str, str]) -> None:
        """Let native clients retry a failed cover through a fresh cache key."""
        if self._cover_retry_cancel is not None:
            return

        @callback
        def retry(_now: datetime) -> None:
            if self._audio_removed or key != (self.media_image_url, self.media_image_hash):
                return
            self._cover_retry_cancel = None
            self._attr_media_image_hash = f"{self._cover_metadata_hash}-{uuid4().hex}"
            self.async_schedule_update_ha_state()

        self._cover_retry_cancel = async_call_later(self.hass, ARTWORK_RETRY_SECONDS, retry)

    def _freeze_audio_position(self, now: datetime) -> None:
        """Freeze once whichever feedback transport reports a stop first."""
        if self.media_position is not None and self.media_position_updated_at is not None:
            if self._state == MediaPlayerState.PLAYING and self._audio_timing_mode == "play":
                elapsed = max(0, (now - self.media_position_updated_at).total_seconds())
                self._attr_media_position = min(self.media_duration, self.media_position + elapsed)
            self._attr_media_position_updated_at = now

    async def event_handler(self, event):
        should_update = False

        if (u := _state_uuid(self.states, "volume")) and u in event.data:
            self._volume = float(event.data[u]) / 100
            should_update = True

        if (u := _state_uuid(self.states, "playState")) and u in event.data:
            state = play_state_to_media_player_state(event.data[u])
            if state != self._state:
                self._freeze_audio_position(dt_util.utcnow())
                # Only a transition is resume; repeated playing feedback must
                # not undo an earlier Audio Server stop during transport lag.
                self._audio_timing_mode = "play" if state == MediaPlayerState.PLAYING else "stop"
            self._state = state
            should_update = True

        if should_update:
            self.async_schedule_update_ha_state()

    # properties
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the clock freeze without overriding native playback state."""
        attrs = super().extra_state_attributes or {}

        if self._audio_metadata is None:
            return attrs
        return {
            **attrs,
            "audio_track_id": (
                sha256(repr((self._audio_timing_identity, self._audio_track_revision)).encode()).hexdigest()
                if self._audio_timing_identity is not None else None
            ),
            "audio_position_frozen": (
                self._audio_timing_mode != "play" if self.media_position is not None else None
            ),
        }

    @property
    def state(self) -> MediaPlayerState:
        """Return the playback state."""
        return self._state

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        return self._volume

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Report native controls, excluding skips for an evidenced radio stream."""
        features = SUPPORT_LOXONE_AUDIO_ZONE
        metadata = self._audio_metadata.get(self._audio_player_id) if self._audio_metadata is not None else None
        if metadata and metadata.source in {"Loxone Radio", "TuneIn"}:
            features &= ~(MediaPlayerEntityFeature.NEXT_TRACK | MediaPlayerEntityFeature.PREVIOUS_TRACK)
        if self._can_announce() and self._radio_catalogue is not None and self._radio_catalogue.source_descriptors:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
        if self._can_announce():
            features |= MediaPlayerEntityFeature.PLAY_MEDIA | MediaPlayerEntityFeature.MEDIA_ANNOUNCE
            features |= MediaPlayerEntityFeature.BROWSE_MEDIA | MediaPlayerEntityFeature.SEARCH_MEDIA
        if self._can_seek():
            features |= MediaPlayerEntityFeature.SEEK
        if self._can_set_audio_mode("shuffle"):
            features |= MediaPlayerEntityFeature.SHUFFLE_SET
        if self._can_set_audio_mode("repeat"):
            features |= MediaPlayerEntityFeature.REPEAT_SET
        return features


    def _can_set_audio_mode(self, operation: str) -> bool:
        """Only current native state/capabilities can enable a mode control."""
        metadata = self._audio_metadata.get(self._audio_player_id) if self._audio_metadata is not None else None
        return self._can_announce() and audio_mode_supported(metadata, operation)

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Set a literal mode; feedback, not this request, owns the HA indicator."""
        if type(shuffle) is not bool:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        await self._async_set_audio_mode("shuffle", shuffle)

    async def async_set_repeat(self, repeat: RepeatMode) -> None:
        """Map HA's standard Off/All/One to native 0/1/3 explicitly."""
        modes = {RepeatMode.OFF: AudioRepeatMode.OFF, RepeatMode.ALL: AudioRepeatMode.ALL,
                 RepeatMode.ONE: AudioRepeatMode.ONE}
        if not isinstance(repeat, str) or repeat not in modes:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        await self._async_set_audio_mode("repeat", modes[repeat])

    async def _async_set_audio_mode(self, operation: str, value: bool | AudioRepeatMode) -> None:
        """Share existing newest-action transport ownership, without playback."""
        if not self._can_set_audio_mode(operation) or self._announcement_task is not None or self._audio_source_uncertain():
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        commands, metadata, player = self._audio_commands, self._audio_metadata, self._audio_player_id
        original = metadata.get(player)
        generation, owner = None, False
        valid = True

        def current() -> bool:
            nonlocal valid
            snapshot = metadata.get(player)
            valid = bool(
                valid and (generation is None or generation == self._source_generation)
                and self._can_set_audio_mode(operation) and self._announcement_task is None
                and not self._audio_source_uncertain() and snapshot is not None
                and all(getattr(original, field) == getattr(snapshot, field)
                        for field in ("audio_path", "source_name", "parent_id", "native_mode"))
            )
            return valid

        # Observe original native validity even while the previous owner's socket
        # drains. Ownership is checked once acquired; stable takeover is valid.
        # A matching later frame must never revive a native-invalidated request.
        remove = metadata.async_add_listener(player, current)
        try:
            generation, owner = await self._async_begin_source_action()
            if operation == "shuffle":
                await commands.async_set_shuffle(player, value, is_current=current)
            else:
                await commands.async_set_repeat(player, value, is_current=current)
        except (AudioCommandError, ValueError, TimeoutError):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_failed") from None
        finally:
            remove()
            self._finish_source_action(owner)

    def _can_announce(self) -> bool:
        """Require opt-in control and exact-player event completion ownership."""
        return bool(
            self._audio_commands_enabled
            and self._audio_commands is not None
            and self._audio_metadata is not None
            and self._audio_player_id is not None
            and not self._audio_removed
        )

    async def _async_cancel_audio_task(self, task: asyncio.Task, *, cancel: bool = True) -> None:
        """Cancellation requests never detach an owned transport's cleanup."""
        if cancel and not task.cancelling():
            task.cancel()
        waiter = asyncio.gather(task, return_exceptions=True)
        cancelled = False
        while not waiter.done():
            try:
                await asyncio.shield(waiter)
            except asyncio.CancelledError:
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    async def _async_begin_source_action(self) -> tuple[int, bool]:
        """One owner for Source/Browse/Seek; newest explicit intent supersedes it."""
        task = asyncio.current_task()
        if self._source_task is task:
            return self._source_generation, False
        previous = self._source_task
        # Transfer an unresolved exact-return obligation before invalidating its
        # owner or awaiting socket cleanup. The departed caller must not write
        # this state later, nor may its wrong feedback become a native no-op.
        self._retain_unconfirmed_source_return(self._source_target)
        self._source_generation += 1
        generation = self._source_generation
        self._source_task = task
        self._source_target = None
        try:
            if previous is not None:
                await self._async_cancel_audio_task(previous)
            # Ordinary play/skip controls also own native transports, even
            # when they did not start a Source action. Drain those sockets
            # before this newer intent dispatches; the same shielded cleanup
            # survives an intervening third selection.
            for pending in tuple(self._transport_tasks):
                if pending is not task and pending is not previous:
                    await self._async_cancel_audio_task(pending)
            if self._source_task is not task or generation != self._source_generation or self._audio_removed:
                raise asyncio.CancelledError
            # Supersede only this player's old source observer, AFTER its
            # transport cleanup. Announcement and durable provider ownership
            # remain separate; this is a new explicit action, never replay A.
            release = (
                self._audio_commands.source_fences.get(self._audio_player_id)
                if self._audio_commands is not None else None
            )
            if release is not None:
                release()
        except BaseException:
            self._finish_source_action(True)
            raise
        return generation, True

    def _retain_unconfirmed_source_return(self, target: RadioTarget | None) -> None:
        """Carry an unresolved exact target, never authority to replay its write."""
        if (
            isinstance(target, CatalogueTarget) and target.return_session is not None
            and self._audio_commands is not None and self._audio_metadata is not None
            and self._audio_player_id is not None
            and self._audio_player_id in self._audio_commands.source_fences
        ):
            saved = target.return_session
            snapshot = self._audio_metadata.get(self._audio_player_id)
            rejected = (
                snapshot.audio_path
                if snapshot is not None and snapshot.source == saved.source
                and snapshot.source_name == saved.source_name and snapshot.audio_path else None
            )
            self._source_return_rejection = (saved, rejected)

    def _finish_source_action(self, owner: bool) -> None:
        """Obsolete and nested actions cannot clear a newer intent's ownership."""
        if owner and self._source_task is asyncio.current_task():
            self._source_task = None
            self._source_target = None
            if self._radio_catalogue is not None:
                self._attr_source_list = list(self._radio_catalogue.previous_source_labels) or None

    async def async_select_source(self, source: str) -> None:
        """Return to the exact room's last native provider selection or input."""
        if (
            not self._can_announce()
            or self._radio_catalogue is None
            or (
                source not in self._radio_catalogue.source_choices
                and source not in self._radio_catalogue.source_descriptors
            )
            or self._announcement_task is not None
        ):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        generation, owns_action = await self._async_begin_source_action()

        def selected(target: RadioTarget) -> None:
            self._source_target = target

        def native_available() -> bool:
            return (
                self._source_generation == generation
                and self._can_announce() and self._announcement_task is None
                and self._audio_player_id not in self._audio_commands.announcement_fences
            )

        try:
            route = await audio_selection.async_source_route(
                self._audio_commands, self._audio_metadata, self._radio_catalogue, self._audio_player_id, source,
                is_current=lambda: generation == self._source_generation,
                ensure_snapshot=lambda: self._async_ensure_source_snapshot(generation),
                native_is_available=native_available,
                on_target=selected, environment=audio_sources.environment,
                allow_native_noop=self._source_return_rejection is None,
            )
            if route.media_id is not None:
                await self._async_play_radio(route.media_id, expected_native=route.original, source_return=True)
        except audio_selection.SourceContentRequiredError:
            descriptor = self._radio_catalogue.source_descriptors.get(source)
            folder = {
                "tunein": "Radio", "loxoneradio": "Loxone Radio",
                "library": "Local Library", "spotify": "Spotify",
            }.get(getattr(descriptor, "service", None), "Radio")
            raise HomeAssistantError(
                f"Choose and play content in Browse media > {folder}. "
                "Then use Source to return to this room's selection."
            ) from None
        except (AudioCommandError, ValueError, TimeoutError, ClientError):  # fmt: skip
            _LOGGER.warning("Audio source selection failed; no automatic retry was sent")
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_failed") from None
        finally:
            self._finish_source_action(owns_action)

    async def _async_ensure_source_snapshot(self, generation: int) -> None:
        """Bootstrap only absent metadata, never replace a newer household state."""
        if self._audio_metadata.get(self._audio_player_id) is not None:
            return

        def current() -> bool:
            return (
                self._can_announce() and self._source_generation == generation
                and self._announcement_task is None
                and self._audio_player_id not in self._audio_commands.source_fences
                and self._audio_player_id not in self._audio_commands.announcement_fences
            )

        await self._audio_metadata.async_ensure_snapshot(
            self._audio_commands, self._audio_player_id, is_current=current,
        )



    async def async_browse_media(
        self, media_content_type: str | None = None, media_content_id: str | None = None,
    ) -> BrowseMedia:
        """Expose native source discovery through HA's standard media browser."""
        if not self._can_announce() or self._radio_catalogue is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        if media_content_type not in (None, RADIO_MEDIA_TYPE):
            message = "Only the native Audio Server catalogue can be browsed"
            raise BrowseError(message)
        try:
            async with self._async_discovery():
                result = to_ha_browse(await self._radio_catalogue.async_browse(media_content_id))
                if not self._audio_sources_ready:
                    await self._async_refresh_native_sources()
                if self._audio_removed:
                    raise HomeAssistantError(
                        translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable"
                    )
                if self._radio_catalogue.favourites is not None:
                    self._source_favourites = self._radio_catalogue.favourites
                self._attr_source_list = list(self._radio_catalogue.previous_source_labels) or None
                self.async_write_ha_state()
                self._proxy_browse_artwork([result])
        except (AudioCommandError, ValueError, TimeoutError):
            message = "Audio sources could not be loaded; browse again"
            raise BrowseError(message) from None
        return result

    async def async_search_media(self, query: SearchMediaQuery) -> SearchMedia:
        """Search native indexed providers, restricted by the requested folder."""
        if not self._can_announce() or self._radio_catalogue is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        if query.media_content_type not in (None, RADIO_MEDIA_TYPE):
            message = "Only the native Audio Server catalogue can be searched"
            raise SearchError(message)
        try:
            async with self._async_discovery():
                native_result = await self._radio_catalogue.async_search(
                    query.search_query, query.media_content_id,
                    media_filter_classes=query.media_filter_classes,
                )
                result = to_ha_search(native_result)
                self._proxy_browse_artwork(result.result)
                return result
        except (AudioCommandError, ValueError, TimeoutError):
            message = "Audio search failed; refine the query and try again"
            raise SearchError(message) from None

    def _proxy_browse_artwork(self, items: list[BrowseMedia]) -> None:
        """Reuse HA's token-protected image route, including HTTP native covers."""
        for item in items:
            if item.thumbnail:
                item.thumbnail = self.get_browse_image_url(RADIO_MEDIA_TYPE, item.media_content_id)
            if item.children:
                self._proxy_browse_artwork(item.children)

    async def async_get_browse_image(
        self, media_content_type: str, media_content_id: str, media_image_id: str | None = None,  # noqa: ARG002
    ) -> tuple[bytes | None, str | None]:
        """Return artwork only for this entity's currently discovered catalogue."""
        if self._audio_removed or self._radio_catalogue is None or media_content_type != RADIO_MEDIA_TYPE:
            return None, None
        try:
            image = self._radio_catalogue.artwork(media_content_id)
        except ValueError:
            return None, None
        if image in BROWSE_ARTWORK:
            return BROWSE_ARTWORK[image], "image/svg+xml"
        if not image or not image.startswith(("http://", "https://")):
            return None, None
        return await self._async_fetch_image(image)

    async def _async_play_radio(  # noqa: PLR0912, PLR0915 - one dispatch boundary
        self, media_id: str, *, expected_native: AudioZoneMetadata | None = None, source_return: bool = False,
    ) -> None:
        """Select only this entity's discovered station, under its source fence."""
        commands, metadata, player = self._audio_commands, self._audio_metadata, self._audio_player_id
        if (
            not self._can_announce() or self._radio_catalogue is None
            or commands is None or metadata is None or player is None
            or self._announcement_task is not None
        ):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        try:
            target = self._radio_catalogue.resolve(media_id)
            if not self._radio_catalogue._item(target).can_play:
                raise ValueError("The discovered item is not playable")
        except ValueError:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_failed") from None
        generation, owns_action = await self._async_begin_source_action()


        try:

            self._source_target = target

            def available() -> bool:
                return (
                    self._can_announce() and self._announcement_task is None
                    and self._source_generation == generation
                )

            def confirmed(snapshot: AudioZoneMetadata) -> None:
                # The observer qualifies post-dispatch playback. A matching
                # frame during preparation is not this visit's success.
                if available():
                    self._radio_catalogue.remember_source(snapshot, intent=None if source_return else target)
                    if self._source_return_rejection is not None:
                        saved, _ = self._source_return_rejection
                        if snapshot.source == saved.source and snapshot.source_name == saved.source_name:
                            self._source_return_rejection = None

            await self._async_ensure_source_snapshot(generation)
            current = expected_native if expected_native is not None else metadata.get(player)
            if current is None:
                msg = "Initial native source identity is missing; no command was sent"
                raise AudioCommandError(msg)  # noqa: TRY301 - translated source-action boundary


            if target.kind == "favourite" and target.favourite is not None:
                await audio_sources.async_select_favourite(
                    commands, metadata, target.favourite, is_available=available,
                    expected_native=current, on_confirmed=confirmed, source_return=source_return,
                )
            elif target.kind == "station":
                await audio_sources.async_select_radio_station(
                    commands, metadata, player,
                    target.service, target.audio_path, is_available=available,
                    expected_native=current, on_confirmed=confirmed, source_return=source_return,
                )
            elif isinstance(target, CatalogueTarget):
                await audio_sources.async_select_catalogue(
                    commands, metadata, player, target, is_available=available, expected_native=current,
                    on_confirmed=confirmed, source_return=source_return,
                )
            else:
                raise ValueError  # noqa: TRY301 - share the translated unsupported-selection error


        except (AudioCommandError, ValueError, TimeoutError, ClientError):
            _LOGGER.warning("Audio content selection failed; no automatic retry was sent")
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_failed") from None
        finally:
            if source_return and available():
                self._retain_unconfirmed_source_return(target)
            self._finish_source_action(owns_action)

    async def async_play_media(self, media_type: str, media_id: str, **kwargs: Any) -> None:
        """Deliver announcements or explicitly select a discovered radio station."""
        if media_type == RADIO_MEDIA_TYPE:
            if kwargs.get("announce") is True or kwargs.get("enqueue") not in (None, "play"):
                raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
            await self._async_play_radio(media_id)
            return
        extra = kwargs.get("extra") or {}
        volume = extra.get("volume", self.volume_level) if isinstance(extra, dict) else None
        if (
            not self._can_announce()
            or kwargs.get("announce") is not True
            or self._announcement_task is not None
            or self._source_task is not None
            or spotify_room_uncertain(self.hass, self.unique_id, self._audio_player_id)
            or self._audio_player_id in getattr(self._audio_commands, "source_fences", {})
            or self._audio_player_id in getattr(self._audio_commands, "announcement_fences", {})
            or not isinstance(media_id, str)
            or not media_id.strip()
            or isinstance(volume, bool)
            or not isinstance(volume, (int, float))
            or not 0 <= volume <= 1
        ):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_announcement_unavailable")
        self._announcement_task = asyncio.current_task()
        try:
            data, duration = await audio_announcement.async_prepare_announcement(self.hass, media_id, self.entity_id)
            await audio_announcement.async_send_announcement(
                self.hass,
                self._audio_commands,
                self._audio_metadata,
                self._audio_player_id,
                data,
                duration,
                round(volume * 100),
            )
        except (AudioCommandError, HomeAssistantError, ValueError, TimeoutError, OSError, ClientError):  # fmt: skip
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="audioserver_announcement_failed"
            ) from None
        finally:
            self._announcement_task = None

    def _can_seek(self) -> bool:
        """Require an explicit track-seek bit on a current supported snapshot."""
        metadata = (
            self._audio_metadata.get(self._audio_player_id)
            if (self._audio_metadata is not None and self._audio_player_id is not None)
            else None
        )
        return bool(
            self._audio_commands_enabled
            and self._audio_commands is not None
            and audio_selection.manual_seek_supported(metadata)
        )

    async def async_media_seek(self, position: float) -> None:
        """Seek within the track and require observed progress, never just an echo."""
        commands, metadata = self._audio_commands, self._audio_metadata
        duration = self.media_duration
        if (
            commands is None or metadata is None or duration is None or not self._can_seek()
            or self._audio_removed or self._announcement_task is not None
            or self._audio_source_uncertain()
        ):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_seek_unavailable")
        # Contributor measurements show that even duration itself can advance
        # the queue. Invalid negatives/non-finite inputs are rejected, not sent.
        try:
            position = audio_selection.manual_seek_position(position, duration)
        except ValueError:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="audioserver_seek_unavailable",
            ) from None
        identity, revision = self._audio_timing_identity, self._audio_track_revision
        original = metadata.get(self._audio_player_id)
        qualification = audio_selection.ManualSeekQualification(original, identity, revision, duration)
        generation, owner = await self._async_begin_source_action()

        def is_current() -> bool:
            return bool(
                not self._audio_removed
                and generation == self._source_generation
                and qualification.is_current(
                    metadata.get(self._audio_player_id), identity=self._audio_timing_identity,
                    revision=self._audio_track_revision, duration=self.media_duration,
                    enabled=self._audio_commands_enabled and self._audio_commands is not None,
                )
            )

        try:
            observed = await audio_sources.async_seek_track(
                commands, metadata, self._audio_player_id, position, is_available=is_current,
            )
        except (AudioCommandError, ValueError, TimeoutError):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_seek_failed") from None
        finally:
            self._finish_source_action(owner)
        if not is_current():
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_seek_failed")
        # Use qualified seek evidence and its newer positive progress, never
        # the last raw zero placeholder. A confirmed zero can override the
        # passive filter; native seek may itself resume pause.
        self._attr_media_position = observed.position
        self._attr_media_position_updated_at = observed.position_updated_at
        if self._radio_catalogue is not None:
            self._radio_catalogue.remember_source(observed, position_confirmed=True)
        self.async_schedule_update_ha_state()

    # commands
    def _audio_source_uncertain(self) -> bool:
        """Keep native fences; old Spotify writes cannot disable proven Library."""
        snapshot = self._audio_metadata.get(self._audio_player_id) if self._audio_metadata is not None else None
        saved = self._radio_catalogue.source_session("Local Library") if self._radio_catalogue is not None else None
        confirmed_library = audio_selection.confirmed_library_session(snapshot, saved)
        return bool(
            (not confirmed_library and (
                spotify_room_uncertain(self.hass, self.unique_id, self._audio_player_id)

            ))
            or (self._audio_commands is not None and (
                self._audio_player_id in self._audio_commands.source_fences
                or self._audio_player_id in self._audio_commands.announcement_fences
            ))
        )

    async def _async_audio_command(self, action: str) -> bool:
        """Use explicitly enabled player commands without a source-changing fallback."""
        if (
            self._audio_removed or self._source_task not in (None, asyncio.current_task()) or self._announcement_task is not None
            or (action == "play" and (self._audio_source_uncertain() or self._transport_tasks))
        ):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        if not self._audio_commands_enabled:
            return False
        if self._audio_commands is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        generation = self._source_generation
        original = self._audio_metadata.get(self._audio_player_id) if self._audio_metadata is not None else None

        def is_current() -> bool:
            current = self._audio_metadata.get(self._audio_player_id) if self._audio_metadata is not None else None
            return bool(
                not self._audio_removed and generation == self._source_generation
                and self._source_task in (None, task) and self._announcement_task is None
                and (action != "play" or not self._audio_source_uncertain())
                and (original is None) == (current is None)
                and (original is None or all(
                    getattr(original, field) == getattr(current, field)
                    for field in ("source", "source_name", "audio_path", "parent_id", "native_mode")
                ))
            )

        task = asyncio.current_task()
        self._transport_tasks.add(task)
        try:
            await self._audio_commands.async_execute(self._audio_player_id, action, is_current=is_current)
        except (AudioCommandError, ValueError):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_failed") from None
        finally:
            self._transport_tasks.discard(task)
        return True

    async def async_media_play(self) -> None:
        """Send play command to device."""
        if not await self._async_audio_command("play"):
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="play"))
        self.async_schedule_update_ha_state()

    async def async_media_pause(self) -> None:
        """Cancel a pending source return, then pause without clearing uncertainty."""
        _generation, owner = await self._async_begin_source_action()
        try:
            if not await self._async_audio_command("pause"):
                self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="pause"))
        finally:
            self._finish_source_action(owner)
        self.async_schedule_update_ha_state()

    async def async_media_stop(self) -> None:
        """Send stop command to device and invalidate a pending provider return."""
        if self._audio_removed:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        _generation, owner = await self._async_begin_source_action()
        try:
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=audio_zone_stop_value()))
        finally:
            self._finish_source_action(owner)
        self.async_schedule_update_ha_state()

    async def async_media_next_track(self) -> None:
        """Send next track command to device."""
        if (
            self._audio_removed or self._source_task is not None or self._announcement_task is not None
            or self._transport_tasks or self._audio_source_uncertain()
        ):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="next"))
        self.async_schedule_update_ha_state()

    async def async_media_previous_track(self) -> None:
        """Send previous track command to device."""
        if (
            self._audio_removed or self._source_task is not None or self._announcement_task is not None
            or self._transport_tasks or self._audio_source_uncertain()
        ):
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="prev"))
        self.async_schedule_update_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Send new volume_level to device."""
        if self._audio_removed:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        volume_int = int(volume * 100)
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=f"volume/{volume_int}"))
        self.async_schedule_update_ha_state()

    async def async_volume_up(self) -> None:
        """Send volume UP to device."""
        if self._audio_removed:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="volUp"))
        self.async_schedule_update_ha_state()

    async def async_volume_down(self) -> None:
        """Send volume DOWN to device."""
        if self._audio_removed:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="audioserver_playback_unavailable")
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="volDown"))
        self.async_schedule_update_ha_state()
