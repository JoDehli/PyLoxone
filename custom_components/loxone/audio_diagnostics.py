"""Entry-owned opt-in local audio evidence, separate from playback and logging."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime
import json
import math
import logging
import os
from pathlib import Path
import re
import stat
import time
import secrets
from uuid import uuid4

from pyloxone_audio.diagnostic_events import (
    BOOLEANS,
    ENUMS,
    IDENTITIES,
    NUMBERS,
    STAGES,
)
from pyloxone_audio.diagnostic_events import DiagnosticEmitter
from homeassistant.helpers.storage import Store
from homeassistant.core import CoreState, callback
from homeassistant.const import EVENT_CALL_SERVICE

_LOGGER = logging.getLogger(__name__)

RETENTION_SECONDS = 86400
# Payload cap; one atomic segment and <=8KiB metadata are additionally reserved.
DISK_BYTES = 4 * 1024 * 1024
SEGMENT_BYTES = 256 * 1024
EXPORT_BYTES = 1024 * 1024
QUEUE_EVENTS = 256
EVENT_BYTES = 2048
_STATS = (
    "expired_records",
    "rotated_records",
    "invalid_records",
    "dropped_queue",
    "dropped_storage",
    "storage_failures",
    "observer_failures",
)


def _encode(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _safe_event(row):
    """Validate persisted input too: never trust a partial/foreign JSONL record."""
    try:
        if (
            not isinstance(row, dict)
            or row.get("schema") != 1
            or not isinstance(row.get("stage"), str)
            or row["stage"] not in STAGES
        ):
            return False
        stamp = datetime.fromisoformat(row["utc"])
        if stamp.tzinfo is None or not math.isfinite(stamp.timestamp()):
            return False
        if type(row["sequence"]) is not int or row["sequence"] < 0:
            return False
        if type(row["monotonic"]) not in (int, float) or not math.isfinite(
            row["monotonic"]
        ):
            return False
        for name, value in row.items():
            if name in {"schema", "stage", "utc", "sequence", "monotonic"}:
                continue
            if name in IDENTITIES:
                if (
                    not isinstance(value, str)
                    or re.fullmatch(re.escape(name) + r"-[0-9a-f]{20}", value) is None
                ):
                    return False
            elif name in NUMBERS:
                if (
                    type(value) not in (int, float)
                    or not math.isfinite(value)
                    or value < 0
                ):
                    return False
            elif name in BOOLEANS:
                if type(value) is not bool:
                    return False
            elif name in ENUMS:
                if not isinstance(value, str) or value not in ENUMS[name]:
                    return False
            elif name == "route":
                if not isinstance(value, str) or not re.fullmatch(
                    r"(?:io/room-[a-f0-9]{20}/(?:volume/[0-9]{1,3}(?:\.[0-9]+)?|play|pause|stop|volUp|volDown|next|prev)|"
                    r"audio/player-[a-f0-9]{20}/(?:position/[0-9]+(?:\.[0-9]+)?|play|pause|stop|status|shuffle/(?:enable|disable)|repeat/(?:0|1|3)|"
                    r"serviceplay/spotify/account-[0-9a-f]{20}/content-[0-9a-f]{20}(?:/parentpath/parent-[0-9a-f]{20}/[0-9]{1,10})?/noshuffle|"
                    r"(?:serviceplay/(?:spotify|library|tunein|loxoneradio|linein|airplay)/account-[0-9a-f]{20}/content-[0-9a-f]{20}|"
                    r"library/play/content-[0-9a-f]{20})(?:/parentpath/parent-[0-9a-f]{20}/[0-9]{1,10})?|"
                    r"roomfav/play/content-[0-9a-f]{20}))",
                    value,
                ):
                    return False
            else:
                return False
        return len(_encode(row)) + 1 <= EVENT_BYTES
    except (KeyError, ValueError, TypeError, OverflowError):
        return False


class RollingJournal:
    """Bounded JSONL segments; invoke only in the host's executor, serially.

    Each operation is bounded by payload+one queue batch. Atomic replacement
    preserves complete segments after failed writes. Coverage never implies
    continuous reception; gaps/drop/failure counters accompany every download.
    """

    def __init__(
        self,
        path: Path,
        *,
        clock=time.time,
        disk_bytes=DISK_BYTES,
        segment_bytes=SEGMENT_BYTES,
        export_bytes=EXPORT_BYTES,
    ):
        self.path = path
        self.clock = clock
        self.disk_bytes = disk_bytes
        self.segment_bytes = min(segment_bytes, disk_bytes)
        self.export_bytes = export_bytes
        self.stats = dict.fromkeys(_STATS, 0)
        self._stats_loaded = False
        self._cache = None
        self._record_groups = {}
        self._canonical = False

    def _read(self, path, limit):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise OSError("Invalid diagnostics file")
            return source.read(limit + 1)

    def _check_directory(self):
        if self.path.is_symlink():
            raise OSError("Invalid diagnostics directory")
        if self.path.exists() and not self.path.is_dir():
            raise OSError("Invalid diagnostics directory")

    def _discard_temporary(self):
        """Only the serial disk owner may retire abandoned atomic writes.

        Never open temporary payloads or follow links. Bound both directory
        inspection and recognised work; unexpected types/limits are failures,
        not evidence of successful recovery.
        """
        if not self.path.exists():
            return
        recognised = 0
        with os.scandir(self.path) as entries:
            for scanned, entry in enumerate(entries):
                if scanned >= 256:
                    raise OSError("Too many diagnostics directory entries")
                if entry.name != "state.json.tmp" and re.fullmatch(
                    r"events-[0-9]{16,}\.jsonl\.tmp", entry.name
                ) is None:
                    continue
                if recognised >= 64:
                    raise OSError("Too many diagnostics temporary files")
                recognised += 1
                if not entry.is_file(follow_symlinks=False):
                    raise OSError("Invalid diagnostics temporary file")
                os.unlink(entry.path)

    def _records(self):
        self._check_directory()
        self._discard_temporary()
        if self._cache is not None:
            return self._cache
        if not self.path.exists():
            self._record_groups = {}
            return [], {}
        if not self._stats_loaded:
            try:
                stored = json.loads(self._read(self.path / "state.json", 8192))
                if not isinstance(stored, dict):
                    stored = {}
                self.stats = {
                    k: stored[k]
                    if type(stored.get(k)) is int and 0 <= stored[k] < 10**18
                    else 0
                    for k in _STATS
                }
            except (FileNotFoundError, ValueError, TypeError):
                pass
            self._stats_loaded = True
        rows, files = [], {}
        size = 0
        for p in sorted(self.path.glob("events-*.jsonl")):
            if len(files) >= 64:
                raise OSError("Too many diagnostics files")
            data = self._read(p, self.segment_bytes)
            size += len(data)
            if size > self.disk_bytes:
                raise OSError("Diagnostics payload exceeds bound")
            files[p.name] = data
            self._record_groups[p.name] = []
            for line in data.splitlines(keepends=True):
                try:
                    row = json.loads(line) if line.endswith(b"\n") else None
                except (ValueError, TypeError):
                    row = None
                if _safe_event(row):
                    rows.append(row)
                    self._record_groups[p.name].append(row)
                else:
                    self.stats["invalid_records"] += 1
        self._cache = (rows, files)
        return self._cache

    def _atomic(self, name, data):
        target = self.path / name
        if target.is_symlink():
            raise OSError("Invalid diagnostics file")
        temporary = self.path / (name + ".tmp")
        fd = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        try:
            with os.fdopen(fd, "wb") as output:
                os.fchmod(output.fileno(), 0o600)
                written = output.write(data)
                if written != len(data):
                    raise OSError("Partial diagnostics write")
                output.flush()
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def maintain(self, incoming):
        _rows, old_files = self._records()
        now = self.clock()
        cutoff = now - RETENTION_SECONDS
        groups = {}
        wanted = {}
        # Preserve stable segment names. Expiry repairs only affected segments;
        # normal appends never rename/rewrite every file at the payload cap.
        for name, records in self._record_groups.items():
            kept = []
            for row in records:
                timestamp = datetime.fromisoformat(row["utc"]).timestamp()
                if timestamp <= cutoff:
                    self.stats["expired_records"] += 1
                elif timestamp > now + 300:
                    self.stats["invalid_records"] += 1
                else:
                    kept.append(row)
            if kept:
                groups[name] = kept
                wanted[name] = (
                    old_files[name]
                    if self._canonical and len(kept) == len(records)
                    else b"".join(_encode(row) + b"\n" for row in kept)
                )
        next_index = max((int(n[7:-6]) for n in old_files), default=-1) + 1
        for row in incoming:
            if not _safe_event(row):
                self.stats["invalid_records"] += 1
                continue
            stamp = datetime.fromisoformat(row["utc"]).timestamp()
            if stamp <= cutoff:
                self.stats["expired_records"] += 1
                continue
            data = _encode(row) + b"\n"
            if stamp > now + 300 or len(data) > self.segment_bytes:
                self.stats["invalid_records"] += 1
                continue
            name = next(reversed(wanted), None)
            if name is None or len(wanted[name]) + len(data) > self.segment_bytes:
                name = f"events-{next_index:016d}.jsonl"
                next_index += 1
                wanted[name] = b""
                groups[name] = []
            wanted[name] += data
            groups[name].append(row)
        total = sum(map(len, wanted.values()))
        while total > self.disk_bytes:
            oldest = next(iter(wanted))
            total -= len(wanted.pop(oldest))
            self.stats["rotated_records"] += len(groups.pop(oldest))
        if not wanted and not self.path.exists():
            return
        try:
            self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.path.chmod(0o700)
            # Delete expired/rotated data first. Atomic replacement reserves at
            # most one extra segment, never an additional whole timeline.
            for name in old_files.keys() - wanted.keys():
                (self.path / name).unlink()
            for name, data in wanted.items():
                if old_files.get(name) != data:
                    self._atomic(name, data)
            state = _encode(self.stats)
            if (
                not (self.path / "state.json").exists()
                or self._read(self.path / "state.json", 8192) != state
            ):
                self._atomic("state.json", state)
        except Exception:
            # A failed atomic write must recover actual disk contents, not
            # promote the uncommitted in-memory candidate into later exports.
            self._cache = None
            self._record_groups = {}
            self._canonical = False
            raise
        self._record_groups = groups
        self._canonical = True
        self._cache = ([row for records in groups.values() for row in records], wanted)

    def export(self):
        self.maintain([])
        rows, _ = self._records()
        report = {
            "retention_seconds": RETENTION_SECONDS,
            "payload_limit_bytes": self.disk_bytes,
            "export_limit_bytes": self.export_bytes,
            "complete_24h": False,
            "coverage_oldest_utc": rows[0]["utc"] if rows else None,
            "coverage_newest_utc": rows[-1]["utc"] if rows else None,
            **self.stats,
            "export_omitted_records": 0,
            "events": [],
        }
        # One encoding per row plus fixed metadata: O(n), not repeated full
        # serialisation of a shrinking list. Reserve counter-digit growth.
        budget = (
            self.export_bytes - len(json.dumps(report, allow_nan=False).encode()) - 24
        )
        retained = []
        for row in reversed(rows):
            size = len(json.dumps(row, allow_nan=False).encode()) + (
                2 if retained else 0
            )
            if size > budget:
                break
            retained.append(row)
            budget -= size
        report["export_omitted_records"] = len(rows) - len(retained)
        report["events"] = list(reversed(retained))
        return report


class EntryAudioDiagnostics:
    """One entry's preference, nonblocking queue, executor writer and export."""

    def __init__(self, hass, entry, structure):
        self.hass, self.entry = hass, entry
        self.store = Store(hass, 1, "loxone_audio_diagnostics." + entry.entry_id)
        self.journal = RollingJournal(
            Path(
                hass.config.path(
                    ".storage", "loxone_audio_diagnostics_" + entry.entry_id
                )
            )
        )
        self._key = secrets.token_hex(32)
        self.emitter = DiagnosticEmitter(bytes.fromhex(self._key), self._enqueue)
        self.queue = asyncio.Queue(maxsize=QUEUE_EVENTS)
        self.wake = asyncio.Event()
        self.lock = asyncio.Lock()
        self._preference_lock = asyncio.Lock()
        self.requested_preference = False
        self.confirmed_preference = None
        self.pending_preference = None
        self._preference_revision = 0
        self._preference_retry_at = 0.0
        self._task = None
        self.closed = False
        self.dropped_queue = 0
        self.dropped_storage = 0
        self.storage_failures = 0
        self.status = "off"
        self._warned = False
        self.on_change = None
        self.players = {}
        self.controls = {}
        self.states = {}
        self._unsubscribe = None
        for uuid, control in (structure.get("controls") or {}).items():
            if not isinstance(control, dict) or control.get("type") != "AudioZoneV2":
                continue
            details = control.get("details") or {}
            from pyloxone_audio.native import audio_player_id

            player = audio_player_id(details.get("playerid"))
            if player is not None:
                action = control.get("uuidAction") or uuid
                self.players[player] = action
                self.controls[action] = player
                for name in ("volume", "playState"):
                    if isinstance(
                        (state_id := (control.get("states") or {}).get(name)), str
                    ):
                        self.states[state_id] = (player, name)

    @property
    def enabled(self):
        return self.emitter.enabled and not self.closed

    @property
    def preference_restart_risk(self):
        return self.pending_preference is not None

    async def async_start(self):
        try:
            saved = await self.store.async_load()
            if isinstance(saved, dict) and re.fullmatch(
                r"[0-9a-f]{64}", saved.get("key", "") or ""
            ):
                self._key = saved["key"]
                self.emitter = DiagnosticEmitter(
                    bytes.fromhex(self._key), self._enqueue
                )
                self.emitter.enabled = saved.get("enabled") is True
            else:
                self._key = secrets.token_hex(32)
                self.emitter = DiagnosticEmitter(
                    bytes.fromhex(self._key), self._enqueue
                )
            self.status = "collecting" if self.enabled else "off"
            self.requested_preference = self.enabled
            self.confirmed_preference = self.enabled
        except Exception:
            self._failure()
        try:
            await self._run_disk(self.journal.maintain, [])
            self.dropped_queue = self.journal.stats["dropped_queue"]
            self.dropped_storage = self.journal.stats["dropped_storage"]
            self.storage_failures += self.journal.stats["storage_failures"]
            self.emitter.sink_failures = self.journal.stats["observer_failures"]
        except Exception:
            self._failure()
        self._task = self.entry.async_create_background_task(
            self.hass, self._writer(), name="Loxone opt-in audio diagnostics"
        )
        self._unsubscribe = self.hass.bus.async_listen(
            EVENT_CALL_SERVICE, self._service_event
        )
        if self.enabled:
            self.emit("collection_started")

    def emit(self, stage, **fields):
        if not self.enabled:
            return
        player = fields.get("player")
        route = fields.get("route")
        if player is None and isinstance(route, str):
            pieces = route.split("/")
            if len(pieces) > 2 and pieces[0] == "audio" and pieces[1].isdigit():
                player = int(pieces[1])
                fields["player"] = player
        if player in self.players:
            fields["room"] = self.players[player]
        fields["entry"] = self.entry.entry_id
        self.emitter.emit(stage, **fields)

    def _enqueue(self, row):
        if not self.enabled or not _safe_event(row):
            return
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped_queue += 1
        self.queue.put_nowait(row)
        self.wake.set()

    @callback
    def _service_event(self, event):
        if not self.enabled:
            return
        try:
            from homeassistant.helpers import entity_registry as er

            data = event.data
            operation = data.get("service")
            if (
                data.get("domain") != "media_player"
                or operation not in ENUMS["operation"]
            ):
                return
            service_data = data.get("service_data") or {}
            targets = service_data.get("entity_id", [])
            if isinstance(targets, str):
                targets = [targets]
            registry = er.async_get(self.hass)
            for target in targets:
                entity = registry.async_get(target)
                if (
                    entity is None
                    or entity.config_entry_id != self.entry.entry_id
                    or entity.unique_id not in self.controls
                ):
                    continue
                fields = {
                    "player": self.controls[entity.unique_id],
                    "operation": operation,
                    "transport": "ha_service",
                    "request_id": event.context.id,
                }
                if operation == "media_seek":
                    fields["position"] = service_data.get("seek_position")
                volume = service_data.get("volume_level")
                if operation == "volume_set" and type(volume) in (int, float):
                    fields["volume"] = volume * 100
                self.emit("ha_service_request", **fields)
        except Exception:
            self.emitter.sink_failures += 1

    def miniserver_feedback(self, message):
        if not self.enabled or not isinstance(message, dict):
            return
        for state_id, value in message.items():
            if state_id not in self.states or type(value) not in (int, float):
                continue
            player, name = self.states[state_id]
            self.emit(
                "feedback",
                player=player,
                transport="miniserver",
                operation="state",
                **{"volume" if name == "volume" else "play_state": value},
            )

    def prepare_miniserver(self, command):
        """Only discovered audio controls and fixed, non-secret commands qualify."""
        if not self.enabled or not isinstance(command, str) or len(command) > 512:
            return None
        pieces = command.split("/")
        if (
            len(pieces) < 5
            or pieces[:3] != ["jdev", "sps", "io"]
            or pieces[3] not in self.controls
        ):
            return None
        if self.emitter.route(command) is None:
            return None
        fields = {
            "player": self.controls[pieces[3]],
            "transport": "miniserver",
            "route": command,
            "request_id": uuid4().hex,
        }
        if pieces[4] == "volume":
            fields["volume"] = float(pieces[5])
        return fields

    def _failure(self):
        self.storage_failures += 1
        self.status = "storage_unavailable"
        self._notify()
        if not self._warned:
            _LOGGER.warning(
                "Audio diagnostics storage unavailable; playback is unaffected. Check free disk space and permissions"
            )
            self._warned = True

    def _notify(self):
        if self.on_change is not None:
            self.on_change()

    def _healthy(self):
        self.status = (
            "storage_unavailable" if self.pending_preference is not None
            else "collecting" if self.enabled else "off"
        )
        self._notify()

    async def _run_disk(self, function, *args):
        """Keep serial ownership until an executor operation actually finishes.

        Cancelling an asyncio waiter cannot stop a filesystem thread. Defer
        propagation until completion so a download/unload cannot race that write.
        """
        future = self.hass.async_add_executor_job(function, *args)
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(future)
                break
            except asyncio.CancelledError:
                if future.cancelled():
                    raise
                cancelled = True
            except Exception:
                if cancelled:
                    raise asyncio.CancelledError from None
                raise
        if cancelled:
            raise asyncio.CancelledError
        return result

    async def _flush_locked(self):
        rows = []
        while not self.queue.empty():
            rows.append(self.queue.get_nowait())
        try:
            counters = {
                "dropped_queue": self.dropped_queue,
                "dropped_storage": self.dropped_storage,
                "storage_failures": self.storage_failures,
                "observer_failures": self.emitter.sink_failures,
            }

            def maintain():
                self.journal._records()
                self.journal.stats.update(counters)
                self.journal.maintain(rows)

            await self._run_disk(maintain)
            self._healthy()
        except Exception:
            self.dropped_storage += len(rows)
            self._failure()

    async def async_flush(self):
        async with self.lock:
            await self._flush_locked()

    async def _writer(self):
        while not self.closed:
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=60)
            except TimeoutError:
                pass
            self.wake.clear()
            # Never take the preference lock while holding the journal lock.
            await self._retry_preference()
            await self.async_flush()
            if not self.closed:
                await asyncio.sleep(0.25)

    async def _save_preference_locked(self):
        """One Store operation, retained until completion even if cancelled.

        Ordinary Store saves invalidate its load cache before disk I/O, but HA
        swallows WriteError. Public readback is therefore required. Stopping
        saves can return pending in-memory data and are never confirmation.
        """
        desired = self.requested_preference
        revision = self._preference_revision

        async def save_and_verify():
            deferred = self.hass.state in (
                CoreState.stopping, CoreState.final_write, CoreState.stopped
            )
            await self.store.async_save({"enabled": desired, "key": self._key})
            if deferred or self.hass.state in (
                CoreState.stopping, CoreState.final_write, CoreState.stopped
            ):
                return False
            saved = await self.store.async_load()
            return (
                self.hass.state not in (
                    CoreState.stopping, CoreState.final_write, CoreState.stopped
                )
                and isinstance(saved, dict)
                and saved.get("enabled") is desired
                and saved.get("key") == self._key
            )

        # At most one owned task: creation is inside the preference lock.
        operation = asyncio.create_task(save_and_verify())
        cancelled = False
        verified = False
        while True:
            try:
                verified = await asyncio.shield(operation)
                break
            except asyncio.CancelledError:
                cancelled = True
                if operation.cancelled():
                    break
            except Exception:
                break
        self._preference_retry_at = self.hass.loop.time() + 60
        if verified and not cancelled and not self.closed:
            self.confirmed_preference = desired
            if revision == self._preference_revision:
                self.pending_preference = None
            self._healthy()
        else:
            self._failure()
        if cancelled:
            raise asyncio.CancelledError

    async def _retry_preference(self):
        if (
            self.closed or self.pending_preference is None
            or self.hass.loop.time() < self._preference_retry_at
        ):
            return
        async with self._preference_lock:
            if (
                self.closed or self.pending_preference is None
                or self.hass.loop.time() < self._preference_retry_at
            ):
                return
            await self._save_preference_locked()

    async def async_set_enabled(self, enabled):
        if self.closed:
            return
        # Apply intent BEFORE waiting for an older write. A newer OFF must never
        # be undone by a stale ON completion, cancellation or storage failure.
        desired = enabled is True
        if not desired:
            self.emit("collection_stopped")
        self.requested_preference = desired
        self.pending_preference = desired
        self._preference_revision += 1
        revision = self._preference_revision
        self.emitter.enabled = desired
        self._healthy()
        if self.enabled:
            self.emit("collection_started")
        async with self._preference_lock:
            if self.closed or revision != self._preference_revision:
                return
            await self._save_preference_locked()
            await self.async_flush()

    async def async_export(self):
        async with self.lock:
            await self._flush_locked()
            try:
                report = await self._run_disk(self.journal.export)
            except Exception:
                self._failure()
                report = {
                    "events": [],
                    "retention_seconds": RETENTION_SECONDS,
                    "complete_24h": False,
                }
        report.update(
            enabled=self.enabled,
            status=self.status,
            pending_preference=self.pending_preference,
            preference_restart_risk=self.preference_restart_risk,
            dropped_queue=self.dropped_queue,
            dropped_storage=self.dropped_storage,
            storage_failures=self.storage_failures,
            entry_alias=self.emitter.alias("entry", self.entry.entry_id),
            mapped_rooms=len(self.players),
            room_aliases_omitted=max(0, len(self.players) - 128),
            rooms=[
                {
                    "room": self.emitter.alias("room", uuid),
                    "player": self.emitter.alias("player", player),
                }
                for player, uuid in sorted(self.players.items())[:128]
            ],
        )
        return await self.hass.async_add_executor_job(self._bound_export, report)

    @staticmethod
    def _bound_export(report):
        # HA owns the outer system/integration envelope and pretty-prints JSON.
        # Bound our actual nested pretty representation, reserving64KiB for
        # that separate platform metadata instead of budgeting compact JSON.
        rows = report["events"]
        omitted = report.get("export_omitted_records", 0)
        low, high = 0, len(rows)
        while low < high:
            cut = (low + high) // 2
            report["events"] = rows[cut:]
            report["export_omitted_records"] = omitted + cut
            report["export_oldest_utc"] = rows[cut]["utc"] if cut < len(rows) else None
            if (
                len(
                    json.dumps(
                        {"data": {"audio": report}}, indent=2, allow_nan=False
                    ).encode()
                )
                > EXPORT_BYTES - 65536
            ):
                low = cut + 1
            else:
                high = cut
        report["events"] = rows[low:]
        report["export_omitted_records"] = omitted + low
        report["export_oldest_utc"] = rows[low]["utc"] if low < len(rows) else None
        return report

    async def async_close(self):
        self.emitter.enabled = False
        self.closed = True
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        self.wake.set()
        if self._task is not None:
            with suppress(asyncio.CancelledError):
                await self._task
        # Retire any caller-owned in-flight preference operation, without
        # holding a lock needed by the writer we just awaited.
        async with self._preference_lock:
            pass
        await self.async_flush()
        self.on_change = None
