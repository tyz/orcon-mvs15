"""Home Assistant policy for the Orcon MVS-15 integration.

The session speaks RAMSES II; this controller decides which devices belong to
the installation, when to raise a repair issue, which requests to send and how
the packet log is written.
"""

from __future__ import annotations

import logging
import os
import threading

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TextIO

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import DOMAIN
from .device import update_gateway_version
from .discovery import DiscoveryManager
from .handlers import DataHandlers
from .issues import (
    async_create_fan_not_responding_issue,
    async_delete_fan_not_responding_issue,
)
from .ramses.protocol import (
    Code,
    Code10e0,
    Code1298,
    Code12a0,
    Code22f1,
    Code31d9,
    Code31e0,
    RamsesID,
    RamsesPacket,
)
from .ramses.session import RamsesSession
from .ramses.transport import ConnectionState, Envelope, TransportError

if TYPE_CHECKING:
    from .coordinator import OrconMVS15DataUpdateCoordinator
    from .models import OrconMVS15Config

_LOGGER = logging.getLogger(__name__)

HUMIDITY_POLL_INTERVAL = timedelta(minutes=5)

# The fan broadcasts 31D9 every 5 minutes and answers the 31D9 request sent at
# setup, so half an hour of silence means the RF link or the fan itself is
# broken. Keep the window wide enough to survive a missed broadcast.
FAN_RESPONSE_TIMEOUT = timedelta(minutes=30)

PACKET_LOG_MAX_SIZE = 10_000_000


class OrconMVS15Controller:
    """Apply the Orcon policy on top of a generic RAMSES session."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: OrconMVS15Config,
        session: RamsesSession,
        discovery: DiscoveryManager,
        fan_coordinator: OrconMVS15DataUpdateCoordinator,
        co2_coordinator: OrconMVS15DataUpdateCoordinator,
        *,
        entry_id: str,
        packet_log: bool = False,
        packet_log_path: str | None = None,
    ) -> None:
        self.hass = hass
        self.config = config
        self.session = session
        self.discovery = discovery
        self.fan_coordinator = fan_coordinator
        self.co2_coordinator = co2_coordinator
        self.entry_id = entry_id
        self.packet_log_enabled = packet_log
        self.packet_log_path = packet_log_path or hass.config.path("packet.log")
        self.handlers = DataHandlers(
            hass, fan_coordinator, co2_coordinator, entry_id=entry_id
        )
        self._unsubs: list[Callable[[], None]] = []
        self._humidity_poll_unsub: Callable[[], None] | None = None
        self._fan_watchdog_unsub: Callable[[], None] | None = None
        self._log_f: TextIO | None = None
        self._log_lock = threading.Lock()
        self._closed = False

    @property
    def fan_id(self) -> RamsesID:
        """Return the known fan id, if any."""
        return self.discovery.get("fan")

    @property
    def co2_id(self) -> RamsesID:
        """Return the known CO2 sensor id, if any."""
        return self.discovery.get("co2")

    async def start(self) -> None:
        """Subscribe to the session and fetch the state of known devices."""
        if self._closed:
            return
        self._register_subscriptions()
        await self.session.start()
        if self.fan_id:
            await self.init_fan()
        if self.co2_id:
            await self.init_co2()

    async def stop(self) -> None:
        """Stop polling, timers, the session and the packet log."""
        if self._closed:
            return
        self._closed = True
        while self._unsubs:
            self._unsubs.pop()()
        self._stop_humidity_polling()
        self.cancel_fan_watchdog()
        self.handlers.cleanup()
        if self.fan_id:
            async_delete_fan_not_responding_issue(self.hass, self.fan_id)
        await self.session.stop()
        await self.hass.async_add_executor_job(self._close_packet_log)

    def _register_subscriptions(self) -> None:
        """Register every packet the integration understands."""
        handlers = dict(self.handlers.pointers)
        handlers["042F"] = self._powerup
        for code, handler in handlers.items():
            self._unsubs.append(self.session.subscribe(code, self._policy(handler)))
        self._unsubs.append(self.session.subscribe_raw(self._log_packet))
        self._unsubs.append(self.session.subscribe_connection(self._connection_changed))
        self._unsubs.append(self.session.subscribe_version(self._version_received))

    def _policy(self, handler: Callable[[Code], None]) -> Callable[[Code], None]:
        """Wrap a data handler with the device and echo filters."""

        def _handle(payload: Code) -> None:
            if self._pre_handle(payload):
                handler(payload)

        return _handle

    def _pre_handle(self, payload: Code) -> bool:
        """Return whether this payload belongs to a device we handle."""
        packet = payload.packet
        if not self._is_ours(packet):
            return False
        if self.fan_id and self._fan_sent(packet):
            self._fan_responded()
        return not self._is_own_echo(packet)

    def _is_ours(self, packet: RamsesPacket) -> bool:
        """Filter out neighbouring installations, except for 042F discovery."""
        known = {
            self.fan_id,
            self.co2_id,
            self.config.gateway_id,
            self.config.remote_id,
        }
        if packet.src_id in known or packet.code == "042F":
            return True
        if (
            not self.co2_id
            and self.fan_id
            and packet.type == "I"
            and packet.code == "31E0"
            and packet.length == 8
            and packet.dst_id == self.fan_id
        ):
            if self.discovery.discover("co2", packet.src_id):
                _LOGGER.debug("Discovered CO2 sensor (%s)", packet.src_id)
                self.hass.async_create_task(self.init_co2())
            return True
        return False

    def _fan_sent(self, packet: RamsesPacket) -> bool:
        """Return whether this packet came from our fan."""
        return (
            packet.ann_id == self.fan_id
            if packet.code == "042F"
            else packet.src_id == self.fan_id
        )

    @staticmethod
    def _is_own_echo(packet: RamsesPacket) -> bool:
        """Return whether a frame is the gateway echo of a local request."""
        return packet.signal_strength == 0 and packet.code not in {
            "042F",
            "22F1",
            "22F3",
        }

    def _powerup(self, payload: Code) -> None:
        """Use the fan's power-up broadcast for discovery.

        Not every unit fills in ``ann_id``. When it is empty, fall back to the
        sender so a broadcast that only names a source still discovers the fan.
        """
        fan_id = payload.packet.ann_id or payload.packet.src_id
        _LOGGER.info(
            "Fan startup payload received, signal strength: %s dBm",
            payload.values["signal_strength"],
        )
        if self.discovery.discover("fan", fan_id):
            _LOGGER.debug("Fetching device info for discovered fan (%s)", fan_id)
            self.hass.async_create_task(self.init_fan())
        self.fan_coordinator.async_set_updated_data(
            {
                **self.fan_coordinator.data,
                "discovered_fan_id": fan_id,
                "fan_signal_strength": payload.values["signal_strength"],
            }
        )

    async def init_fan(self) -> None:
        """Fetch the current fan state and start polling."""
        if self._closed or not self.fan_id:
            return
        gateway_id = self.config.gateway_id
        await self.session.request(Code10e0.get(gateway_id, self.fan_id))
        await self.session.request(Code12a0.get(gateway_id, self.fan_id))
        await self.session.request(Code31d9.get(gateway_id, self.fan_id))
        self.start_humidity_polling()
        self.start_fan_watchdog()

    async def init_co2(self) -> None:
        """Fetch the current CO2 sensor state and device info."""
        if self._closed or not self.co2_id:
            return
        gateway_id = self.config.gateway_id
        await self.session.request(Code10e0.get(gateway_id, self.co2_id))
        await self.session.request(Code1298.get(gateway_id, self.co2_id))
        await self.session.request(Code31e0.get(gateway_id, self.co2_id))

    async def req_humidity(self, _now: datetime | None = None) -> None:
        """Ask the fan for the humidity the gateway does not broadcast."""
        if self._closed or not self.fan_id:
            return
        await self.session.request(Code12a0.get(self.config.gateway_id, self.fan_id))

    def start_humidity_polling(self) -> None:
        """12A0 is not broadcast, so poll it even if a response was lost."""
        if self._closed or self._humidity_poll_unsub is not None:
            return
        self._humidity_poll_unsub = async_track_time_interval(
            self.hass, self.req_humidity, HUMIDITY_POLL_INTERVAL
        )
        _LOGGER.info("Polling humidity every %s", HUMIDITY_POLL_INTERVAL)

    def _stop_humidity_polling(self) -> None:
        """Stop the humidity interval when the entry unloads."""
        if self._humidity_poll_unsub is not None:
            self._humidity_poll_unsub()
            self._humidity_poll_unsub = None
            _LOGGER.debug("Removed the humidity poll interval")

    def start_fan_watchdog(self) -> None:
        """Wait for the fan's first packet and raise an issue on silence.

        Restarting is intentional: every init_fan() asks the fan for its state,
        so a fresh request deserves a fresh response window.
        """
        self.cancel_fan_watchdog()
        if not self.fan_id or self._closed:
            return
        self._fan_watchdog_unsub = async_call_later(
            self.hass, FAN_RESPONSE_TIMEOUT, self._fan_response_timeout
        )

    def cancel_fan_watchdog(self) -> None:
        """Stop waiting for the fan."""
        if self._fan_watchdog_unsub is not None:
            self._fan_watchdog_unsub()
            self._fan_watchdog_unsub = None

    @callback
    def _fan_response_timeout(self, _now: datetime) -> None:
        """Raise the issue when the fan stayed silent for the whole window."""
        self._fan_watchdog_unsub = None
        async_create_fan_not_responding_issue(self.hass, self.fan_id)

    @callback
    def _fan_responded(self) -> None:
        """The fan is alive: stop the timer and clear any stale issue."""
        self.cancel_fan_watchdog()
        async_delete_fan_not_responding_issue(self.hass, self.fan_id)

    @callback
    def async_set_connected(self, connected: bool) -> None:
        """Pause the watchdog and mark the entities unavailable on an outage."""
        for coordinator in (self.fan_coordinator, self.co2_coordinator):
            coordinator.async_set_available(connected)
        if connected:
            self.start_fan_watchdog()
        else:
            self.cancel_fan_watchdog()

    def _connection_changed(self, state: ConnectionState) -> None:
        """Translate the transport state into integration availability."""
        self.async_set_connected(state is ConnectionState.CONNECTED)

    def _version_received(self, version: str) -> None:
        """Store the gateway firmware version on its device."""
        update_gateway_version(
            self.hass, self.entry_id, self.config.gateway_id, version
        )

    async def set_preset_mode(self, mode: str) -> None:
        """Set the fan preset mode."""
        try:
            packet = Code22f1.set(
                value=mode,
                src_id=self.config.remote_id,
                dst_id=self.fan_id,
            )
        except KeyError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="unknown_preset_mode",
                translation_placeholders={"mode": mode},
            ) from err
        _LOGGER.info("Setting fan preset mode to %s", mode)
        try:
            await self.session.request(packet)
        except TransportError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="set_preset_failed",
                translation_placeholders={"mode": mode, "error": str(err)},
            ) from err

    async def _log_packet(self, envelope: Envelope) -> None:
        """Write one debug line when the packet log is enabled."""
        if not self.packet_log_enabled:
            return
        await self.packet_log(envelope)

    async def packet_log(
        self,
        envelope: Envelope,
        path: str | None = None,
        max_size: int = PACKET_LOG_MAX_SIZE,
    ) -> None:
        """Log raw packets to disk, rolling over, offloaded to an executor."""
        target = path or self.packet_log_path

        def _sync_log() -> None:
            with self._log_lock:
                if self._closed:
                    return
                if not self._open_log(target):
                    return
                try:
                    self._append_log_line(envelope)
                    size = os.path.getsize(target)
                except FileNotFoundError:
                    # The file was removed while the handle stayed open.
                    self._close_log_handle()
                    if not self._open_log(target):
                        return
                    self._append_log_line(envelope)
                    size = os.path.getsize(target)

                if size <= max_size:
                    return
                self._close_log_handle()
                for i in range(10, 0, -1):  # keep up to 10 old log files
                    src = f"{target}{'' if i == 1 else f'.{i - 1}'}"
                    dst = f"{target}.{i}"
                    try:
                        os.replace(src, dst)
                    except FileNotFoundError:
                        continue
                try:
                    self._log_f = open(target, "a")
                except Exception as err:
                    _LOGGER.error("Error reopening %s: %s", target, err)
                    self._log_f = None

        await self.hass.async_add_executor_job(_sync_log)

    def _open_log(self, target: str) -> bool:
        """Open the log if there is no handle; return whether it is ready."""
        if self._log_f is not None:
            return True
        try:
            self._log_f = open(target, "a")
        except Exception as err:
            _LOGGER.error("Error opening %s: %s", target, err)
            return False
        return True

    def _append_log_line(self, envelope: Envelope) -> None:
        """Append one line to the open log and flush it."""
        log = self._log_f
        if log is None:
            return
        print(f"{envelope['ts']} {envelope['msg']}", file=log)
        log.flush()

    def _close_log_handle(self) -> None:
        """Close the handle, if any, so the next write reopens the file."""
        if self._log_f is None:
            return
        try:
            self._log_f.close()
        except OSError:
            _LOGGER.debug("Failed to close the packet log", exc_info=True)
        self._log_f = None

    def _close_packet_log(self) -> None:
        """Close the debug log without racing a write in another thread."""
        with self._log_lock:
            self._close_log_handle()
