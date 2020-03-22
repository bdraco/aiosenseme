"""SenseME Discovery.

This class periodically broadcasts discovery packets and listens for response messages
from SenseME fan by Big Ass Fans. Discovered fans are announced via callbacks.

Based on work from Bruce at http://bruce.pennypacker.org/tag/senseme-plugin/
and https://github.com/bpennypacker/SenseME-Indigo-Plugin

Based on work from TomFaulkner at https://github.com/TomFaulkner/SenseMe

Source can be found at https://github.com/mikelawrence/aiosenseme
"""
import asyncio
import inspect
import logging
import random
import socket
import threading
import time
import traceback

import ifaddr
from .fan import SensemeFan

_LOGGER = logging.getLogger(__name__)

PORT = 31415


class SensemeDiscoveryProtocol(asyncio.DatagramProtocol):
    """Datagram protocol for SenseME Discovery."""

    def __init__(self, endpoint):
        self._endpoint = endpoint

    # Protocol methods
    def connection_made(self, transport):
        self._endpoint._transport = transport
        self._endpoint._opened = True
        # _LOGGER.debug("Listening on %s" % self._endpoint._ip)
        self._endpoint.send_broadcast()

    def connection_lost(self, exe):
        # _LOGGER.debug("Listener closed on %s" % self._endpoint._ip)
        self._endpoint.close()  # half-closed connections are not permitted

    # Datagram protocol methods
    def datagram_received(self, data, addr):
        if data:
            msg = data.decode("utf-8")
            try:
                self._endpoint.receive_queue.put_nowait((msg, addr[0]))
            except asyncio.QueueFull:
                _LOGGER.error("Receive queue full")

    def error_received(self, exe):
        _LOGGER.error(
            "Endpoint error on %s\n%s" % (traceback.format_exc(), self._endpoint._ip)
        )


class SensemeDiscoveryEndpoint:
    """High-level endpoint for SenseME Discovery protocol."""

    receive_queue = asyncio.Queue()

    def __init__(self, ip=None):
        self._opened = False
        self._transport = None
        self._ip = ip

    def abort(self):
        """Close the transport immediately.
        Buffered write data will be lost.
        """
        self._opened = False
        if self._transport is None:
            return
        self._transport.abort()
        self.close()

    def close(self):
        """Close the transport gracefully.
        Buffered write data will be sent.
        """
        self._opened = False
        if self._transport is None:
            return
        self.receive_queue.put_nowait(None)  # tell receive() socket is closed
        if self._transport:
            self._transport.close()

    def is_closing(self):
        """Return True if the endpoint is closed or closing."""
        if not self._opened:
            return False  # unopened connection is not closed
        if self._transport is None:
            return True  # opened connection but no transport is closed
        return self._transport.is_closing()

    async def receive(self):
        """Wait for discovered device and return it.
        Return None when the socket is closed.
        This method is a coroutine.
        """
        while True:
            if self.receive_queue.empty() and self._transport.is_closing():
                return None
            rsp = await self.receive_queue.get()
            if rsp is None:
                return None
            try:
                msg = rsp[0]
                addr = rsp[1]
                if len(msg) > 200 or len(msg) < 31:
                    continue
                if msg[0] != "(" or msg[-1] != ")":
                    continue
                msg = msg[1:-1]
                msg_data = msg.split(";")
                if len(msg_data) != 5:
                    continue
                # _LOGGER.debug("Received '%s' from %s on %s" % (msg, addr, self._ip))
                device = SensemeFan(msg_data[0], msg_data[3], addr, msg_data[4])
                return device
            except Exception as e:
                _LOGGER.error(
                    "Failed to parse discovery response %s from %s, error: %s"
                    % (msg, addr, str(e))
                )

    def send_broadcast(self):
        """Sends the SenseME Discovery broadcast packet."""
        data = "<ALL;DEVICE;ID;GET>".encode("utf-8")
        self._transport.sendto(data, ("<broadcast>", PORT))
        # _LOGGER.debug("Discovery broadcast on %s" % (self._ip))


class SensemeDiscovery:
    """SenseME Discovery Class.

    This class periodically broadcasts discovery packets and listens
    for response messages from SenseME fans by Big Ass Fans.
    """

    _devices = []  # all SensemeDiscovery objects use the same device list

    def __init__(self, startFirst=True, refreshMinutes=5):
        threading.Thread.__init__(self)
        # will start and update device before announcing discovery
        self.startFirst = startFirst
        self.refreshMinutes = refreshMinutes
        self._is_running = False
        self._callbacks = []

    @property
    def devices(self):
        """Gets the current list of discovered fans."""
        return self._devices

    def add_callback(self, callback):
        """Add callback function/coroutine.
        Called when parameters are updated.
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            if inspect.iscoroutinefunction(callback):
                asyncio.get_event_loop().create_task(callback(self._devices.copy()))
                _LOGGER.debug("Added coroutine callback")
            else:
                callback(self._devices.copy())
                _LOGGER.debug("Added function callback")

    def remove_callback(self, callback):
        """Remove existing callback function/coroutine."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            _LOGGER.debug("Removed callback")

    async def _broadcaster(self):
        """Periodically broadcast discovery packet.
        If the underlying socket has an error this task will exit.
        This method is a coroutine.
        """
        self._is_running = True
        loop = asyncio.get_event_loop()
        error_count = 0
        device = None
        while True:
            if error_count > 10:
                _LOGGER.debug("Too many errors, broadcaster task aborted")
                break
            try:
                found_new = 0
                found_total = 0
                endpoints = []
                found_devices = []
                for adapter in ifaddr.get_adapters():
                    for ip in adapter.ips:
                        if isinstance(ip.ip, str) and "127.0.0.1" not in ip.ip:
                            endpoint = SensemeDiscoveryEndpoint(ip.ip)
                            try:
                                await loop.create_datagram_endpoint(
                                    lambda: SensemeDiscoveryProtocol(endpoint),
                                    local_addr=(ip.ip, PORT),
                                    family=socket.AF_INET,
                                    allow_broadcast=True,
                                )
                                endpoints.append(endpoint)
                            except Exception:
                                _LOGGER.error(
                                    "Error opening broadcast listener socket on %s\n%s"
                                    % (ip.ip, traceback.format_exc())
                                )
                                error_count += 1
                start = time.time()
                while True:
                    try:
                        device = await asyncio.wait_for(endpoints[0].receive(), 1)
                    except asyncio.TimeoutError:
                        device = None
                        if time.time() - start < 5:
                            for endpoint in endpoints:
                                endpoint.send_broadcast()
                        else:
                            for endpoint in endpoints:
                                endpoint.abort()
                            endpoints = []
                            break
                    if device is not None:
                        if device not in self._devices:
                            if self.startFirst:
                                if await device.update():
                                    self._devices.append(device)
                                    _LOGGER.debug("Discovered %s" % (device))
                                    found_new += 1
                                else:
                                    _LOGGER.debug("Failed to start %s" % (device.name))
                            else:
                                if await device.fill_out_secondary_info():
                                    self._devices.append(device)
                                    _LOGGER.debug("Discovered %s" % (device))
                                    found_new += 1
                                else:
                                    _LOGGER.debug(
                                        "Failed to retrieve secondary info for %s"
                                        % (device.name)
                                    )
                        if device not in found_devices:
                            found_devices.append(device)
                            found_total += 1
                        for callback in self._callbacks:
                            try:
                                if inspect.iscoroutinefunction(callback):
                                    loop.create_task(callback(self._devices.copy()))
                                else:
                                    callback(self._devices.copy())
                            except Exception:
                                _LOGGER.error(
                                    "Callback error\n%s" % (traceback.format_exc())
                                )
                error_count = 0
                found_old = found_total - found_new
                found_devices = None

                if found_old > 1:
                    _LOGGER.debug(
                        "Discovered %s existing fan%s"
                        % (found_old, "" if found_old == 1 else "s",)
                    )
                elif found_new == 0:
                    _LOGGER.debug("Discovered 0 fans")
                await asyncio.sleep(self.refreshMinutes * 60 + random.uniform(-10, 10))
            except asyncio.CancelledError:
                _LOGGER.debug("Broadcaster task cancelled")
                return
            except Exception:
                _LOGGER.error("Broadcaster task error\n%s" % traceback.format_exc())
                error_count += 1
                await asyncio.sleep(1)
            finally:
                for endpoint in endpoints:
                    endpoint.abort()
                endpoints = None
                found_devices = None
        _LOGGER.error("Broadcaster task ended")

    def start(self):
        """Starts both broadcaster and listener tasks.
        Will maintain a list of discovered fans.
        """
        if not self._is_running:
            loop = asyncio.get_event_loop()
            self._broadcaster_task = loop.create_task(self._broadcaster())

    def stop(self):
        """Stops both broadcaster and listener tasks.
        Any discovered fans will remain in memory and will continue to update.
        """
        if self._is_running is True:
            self._broadcaster_task.cancel()
            self._is_running = False

    def remove_discovered_devices(self):
        """Stops both broadcaster and listener tasks.
        Any discovered fans will be stopped and removed from memory.
        """
        self.stop()
        for fan in self._devices:
            fan.stop()
        self._devices = []


async def Discover_Any(timeoutSeconds=5) -> bool:
    """Return True if any SenseME fans are found on the network.
    This function will always take timeoutSeconds to complete.
    This method is a coroutine.
    """
    discovery = SensemeDiscovery(True, 1)
    discovery.start()
    await asyncio.sleep(timeoutSeconds)
    count = len(discovery.devices)
    discovery.stop()
    _LOGGER.debug("Discovered %s fan%s" % (count, "" if count == 1 else "s"))
    return count > 0
