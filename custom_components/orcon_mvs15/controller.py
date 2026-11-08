"""Home Assistant policy for the Orcon MVS-15 integration.

The session speaks RAMSES II; this controller decides which devices belong to
the installation, when to raise a repair issue, which requests to send and how
the packet log is written.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TextIO

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .const import DOMAIN, TRANSPORT_MQTT
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

# The gateway downloads and flashes the image itself, so the wait covers the
# download, the reboot and the retained version message on reconnect.
FIRMWARE_UPDATE_TIMEOUT = 300.0
# The firmware stores the tag in a 32-byte buffer and uses it in a URL path.
FIRMWARE_VERSION_RE = re.compile(r"^[A-Za-z0-9._-]{1,31}$")


def packet_fan_id(packet: RamsesPacket) -> RamsesID:
    """Return the fan a packet came from.

    Not every unit fills in ``ann_id`` on a ``042F`` broadcast, so fall back to
    the sender when it is empty. Every decision about ownership uses this one
    rule, so discovery and the watchdog cannot disagree.
    """
    if packet.code == "042F":
        return packet.ann_id or packet.src_id
    return packet.src_id


def _versions_match(reported: str, target: str) -> bool:
    """Treat a release tag and the firmware's version string as the same version."""
    return reported.removeprefix("v") == target.removeprefix("v")


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
        gateway_coordinator: OrconMVS15DataUpdateCoordinator,
        *,
        entry_id: str,
        packet_log: bool = False,
        packet_log_path: str | None = None,
        firmware_update_timeout: float = FIRMWARE_UPDATE_TIMEOUT,
    ) -> None:
        self.hass = hass
        self.config = config
        self.session = session
        self.discovery = discovery
        self.fan_coordinator = fan_coordinator
        self.co2_coordinator = co2_coordinator
        self.gateway_coordinator = gateway_coordinator
        self.entry_id = entry_id
        self.firmware_update_timeout = firmware_update_timeout
        self._firmware_update_future: asyncio.Future[str] | None = None
        self._firmware_update_target: str | None = None
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
        if (
            self._firmware_update_future is not None
            and not self._firmware_update_future.done()
        ):
            self._firmware_update_future.cancel()
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
        self._unsubs.append(self.session.subscribe_latest(self._latest_received))

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
            ramses_id
            for ramses_id in (
                self.fan_id,
                self.co2_id,
                self.config.gateway_id,
                self.config.remote_id,
            )
            if ramses_id
        }
        if packet.src_id in known:
            return True
        if packet.code == "042F":
            # Before the fan is known a power-up is the only way to learn its
            # id; afterwards a different ann_id is another installation.
            return not self.fan_id or packet_fan_id(packet) == self.fan_id
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
                self._start_init(self.init_co2)
            return True
        return False

    def _fan_sent(self, packet: RamsesPacket) -> bool:
        """Return whether this packet came from our fan."""
        return packet_fan_id(packet) == self.fan_id

    @staticmethod
    def _is_own_echo(packet: RamsesPacket) -> bool:
        """Return whether a frame is the gateway echo of a local request."""
        return packet.signal_strength == 0 and packet.code not in {
            "042F",
            "22F1",
            "22F3",
        }

    def _powerup(self, payload: Code) -> None:
        """Use the fan's power-up broadcast for discovery."""
        fan_id = packet_fan_id(payload.packet)
        _LOGGER.info(
            "Fan startup payload received, signal strength: %s dBm",
            payload.values["signal_strength"],
        )
        if self.discovery.discover("fan", fan_id):
            _LOGGER.debug("Fetching device info for discovered fan (%s)", fan_id)
            self._start_init(self.init_fan)
        self.fan_coordinator.async_set_updated_data(
            {
                **self.fan_coordinator.data,
                "discovered_fan_id": fan_id,
                "fan_signal_strength": payload.values["signal_strength"],
            }
        )

    def _start_init(self, init: Callable[[], Awaitable[None]]) -> None:
        """Run a discovered-device init without losing a failed publish."""

        async def _run() -> None:
            try:
                await init()
            except TransportError as err:
                _LOGGER.warning("Could not fetch the device state: %s", err)

        self.hass.async_create_task(_run())

    async def init_fan(self) -> None:
        """Fetch the current fan state and start polling."""
        if self._closed or not self.fan_id:
            return
        gateway_id = self.config.gateway_id
        try:
            await self.session.request(Code10e0.get(gateway_id, self.fan_id))
            await self.session.request(Code12a0.get(gateway_id, self.fan_id))
            await self.session.request(Code31d9.get(gateway_id, self.fan_id))
        finally:
            # A failed publish must not leave the fan unwatched or unpolled.
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
        """Raise an issue if the fan stays silent for the whole window.

        Restarting is intentional: every fan packet and every init_fan()
        deserves a fresh response window.
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
        """The fan is alive: clear the issue and restart the silence window."""
        self.start_fan_watchdog()
        async_delete_fan_not_responding_issue(self.hass, self.fan_id)

    @callback
    def async_set_connected(self, connected: bool) -> None:
        """Pause the watchdog and mark the entities unavailable on an outage."""
        for coordinator in (
            self.fan_coordinator,
            self.co2_coordinator,
            self.gateway_coordinator,
        ):
            coordinator.async_set_available(connected)
        if connected:
            self.start_fan_watchdog()
        else:
            self.cancel_fan_watchdog()

    def _connection_changed(self, state: ConnectionState) -> None:
        """Translate the transport state into availability and a refresh."""
        connected = state is ConnectionState.CONNECTED
        self.async_set_connected(connected)
        if connected:
            self._start_init(self._refresh_devices)

    async def _refresh_devices(self) -> None:
        """Re-fetch the known devices after the gateway comes back.

        The next broadcast can be five minutes away, so a reconnect would
        otherwise leave the entities unavailable long after the stick is up.
        """
        if self.fan_id:
            await self.init_fan()
        if self.co2_id:
            await self.init_co2()

    def _version_received(self, version: str) -> None:
        """Store the gateway firmware version and release a waiting update."""
        previous = self.gateway_coordinator.data.get("firmware_version")
        self.gateway_coordinator.async_set_updated_data(
            {**self.gateway_coordinator.data, "firmware_version": version}
        )
        update_gateway_version(
            self.hass, self.entry_id, self.config.gateway_id, version
        )
        future = self._firmware_update_future
        target = self._firmware_update_target
        if (
            future is not None
            and not future.done()
            and (
                version != previous
                or target is None
                or _versions_match(version, target)
            )
        ):
            future.set_result(version)

    def _latest_received(self, version: str) -> None:
        """Store the newest firmware version the gateway found."""
        self.gateway_coordinator.async_set_updated_data(
            {**self.gateway_coordinator.data, "latest_firmware_version": version}
        )

    async def async_install_firmware(self, version: str | None = None) -> None:
        """Ask the gateway to install firmware and wait for its new version.

        The gateway downloads the image itself; this only sends the console
        command and waits for the rebooted firmware to report its version.
        """
        if self.config.transport != TRANSPORT_MQTT:
            raise self._gateway_error("firmware_update_unsupported")
        if self._firmware_update_future is not None:
            raise self._gateway_error("firmware_update_in_progress")
        target = version.strip() if version is not None else None
        if target is not None and not FIRMWARE_VERSION_RE.match(target):
            raise self._gateway_error("firmware_version_invalid", version=version or "")
        if target is None:
            latest = self.gateway_coordinator.data.get("latest_firmware_version")
            if not isinstance(latest, str) or not latest:
                raise self._gateway_error("firmware_latest_unknown")
            target = latest
        previous = self.gateway_coordinator.data.get("firmware_version")
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._firmware_update_future = future
        self._firmware_update_target = target
        try:
            try:
                if version is not None:
                    await self.session.send_command(f"ota version {target}")
                await self.session.send_command("ota start")
            except TransportError as err:
                raise self._gateway_error(
                    "firmware_update_failed", error=str(err)
                ) from err
            try:
                async with asyncio.timeout(self.firmware_update_timeout):
                    reported = await future
            except TimeoutError as err:
                raise self._gateway_error(
                    "firmware_update_timeout", version=target
                ) from err
        finally:
            self._firmware_update_future = None
            self._firmware_update_target = None
        _LOGGER.info(
            "Gateway firmware reported %s (installed was %s)", reported, previous
        )

    @staticmethod
    def _gateway_error(key: str, **placeholders: str) -> HomeAssistantError:
        """Build a translated gateway-command error."""
        return HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=key,
            translation_placeholders=placeholders,
        )

    async def async_reboot_gateway(self) -> None:
        """Reboot the gateway with the firmware's own `reset` command."""
        if self._firmware_update_future is not None:
            raise self._gateway_error("reboot_during_update")
        _LOGGER.info("Rebooting the Ramses ESP gateway")
        try:
            await self.session.send_command("reset")
        except TransportError as err:
            raise self._gateway_error("reboot_failed", error=str(err)) from err

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
