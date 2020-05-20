"""SensemeFan Class.

This class connects to a SenseME fan by Big Ass Fans to retrieve and maintain its
complete state. It keep a connection always open to the fan and will receive virtually
instantaneous state changes (push) from any source (i.e. remote control or Haiku App).
The always open connection will automatically reconnect on errors or when the SenseME
fan disconnects. Control and access to the fan's current state is provided by class
properties. State changes are announced via callbacks.

Based on work from Bruce at http://bruce.pennypacker.org/tag/senseme-plugin/
and https://github.com/bpennypacker/SenseME-Indigo-Plugin

Based on work from TomFaulkner at https://github.com/TomFaulkner/SenseMe

Source can be found at https://github.com/mikelawrence/aiosenseme
"""
import asyncio
import inspect
import ipaddress
import logging
import random
import time
import traceback
from typing import Any, Callable, Tuple

_LOGGER = logging.getLogger(__name__)

PORT = 31415

ONOFF = ["ON", "OFF"]
DIRECTIONS = ["FWD", "REV"]
AUTOCOMFORTS = ["OFF", "COOLING", "HEATING", "FOLLOWTSTAT"]
ROOM_TYPES = [
    "Undefined",  # 0, not in a room
    "Other",  # 1
    "Master Bedroom",  # 2
    "Bedroom",  # 3
    "Den",  # 4
    "Family Room",  # 5
    "Living Room",  # 6
    "Kids Room",  # 7
    "Kitchen",  # 8
    "Dining Room",  # 9
    "Basement",  # 10
    "Office",  # 11
    "Patio",  # 12
    "Porch",  # 13
    "Hallway",  # 14
    "Entryway",  # 15
    "Bathroom",  # 16
    "Laundry",  # 17
    "Stairs",  # 18
    "Closet",  # 19
    "Sunroom",  # 20
    "Media Room",  # 21
    "Gym",  # 22
    "Garage",  # 23
    "Outside",  # 24
    "Loft",  # 25
    "Playroom",  # 26
    "Pantry",  # 27
    "Mudroom",  # 28
]

DEVICE_MODELS = {
    "FAN,HAIKU,SENSEME": "Haiku Fan",
    "FAN,HAIKU,HSERIES": "Haiku Fan",  # H Series is now called plain Haiku
    "FAN,LSERIES": "Haiku L Fan",
    "LIGHT,HAIKU": "Haiku Light",
}

DEVICE_TYPES = {
    "FAN,HAIKU,SENSEME": "FAN",
    "FAN,HAIKU,HSERIES": "FAN",
    "FAN,LSERIES": "FAN",
    "LIGHT,HAIKU": "LIGHT",
}


class SensemeEndpoint:
    """High-level endpoint for SenseME protocol."""

    def __init__(self):
        """Initialize Senseme Discovery Endpoint."""
        self.receive_queue = asyncio.Queue()
        self.opened = False
        self.transport = None

    def abort(self):
        """Close the transport immediately. Buffered write data will be flushed."""
        self.transport.abort()
        self.close()

    def close(self):
        """Close the transport gracefully. Buffered write data will be sent."""
        if self.transport is None:
            return
        self.receive_queue.put_nowait(None)  # tell receive() socket is closed
        if self.transport:
            self.transport.close()

    def is_closing(self) -> bool:
        """Return True if the endpoint is closed or closing."""
        if not self.opened:
            return False  # unopened connection is not closed
        if self.transport is None:
            return True  # opened connection but no transport is closed
        return self.transport.is_closing()

    async def receive(self) -> str:
        """Wait for a message from the SenseME fan.

        Return None when the socket is closed.
        This method is a coroutine.
        """
        if self.receive_queue.empty() and self.transport.is_closing():
            return None
        return await self.receive_queue.get()

    def send(self, cmd):
        """Send a command to the SenseME fan."""
        self.transport.write(cmd.encode("utf-8"))


class SensemeProtocol(asyncio.Protocol):
    """Protocol for SenseME communication."""

    def __init__(self, name, endpoint: SensemeEndpoint):
        """Initialize Senseme Protocol."""
        self._name = name
        self._endpoint = endpoint

    # Protocol methods
    def connection_made(self, transport: asyncio.Protocol):
        """Socket connect on SenseME Protocol."""
        _LOGGER.debug("%s: Connected", self._name)
        self._endpoint.transport = transport
        self._endpoint.opened = True

    def connection_lost(self, exc):  # pylint: disable=unused-argument
        """Lost connection SenseME Protocol."""
        _LOGGER.debug("%s: Connection lost", self._name)
        self._endpoint.close()  # half-closed connections are not permitted

    # Streaming Protocol methods
    def data_received(self, data: str) -> str:
        """UDP packet received on SenseME Protocol."""
        if data:
            msg = data.decode("utf-8")
            try:
                self._endpoint.receive_queue.put_nowait(msg)
            except asyncio.QueueFull:
                _LOGGER.error("%s: Receive queue full", self._name)

    def eof_received(self) -> bool:
        """EOF received on SenseME Protocol."""
        return False  # tell the transport to close itself


class SensemeDevice:
    """SensemeDevice base class."""

    def __init__(
        self,
        name: str,
        id: str,  # pylint: disable=redefined-builtin
        ip: str,
        model: str,
        refresh_minutes: int = 1,
    ):
        """Initialize SensemeDevice Class."""
        self._name = name
        self.refresh_minutes = refresh_minutes
        self._id = id
        self._ip = ip
        self._model = model
        self._room_name = None
        self._fw_name = ""
        self._fw_version = None
        self._has_light = None
        self._is_running = False
        self._is_connected = False
        self._data = dict()
        self._endpoint = None
        self._listener_task = None
        self._updater_task = None
        self._error_count = 0
        self._leftover = ""
        self._callbacks = []
        self._first_update = False

    def __eq__(self, other: Any) -> bool:
        """Equals magic method."""
        try:
            ip_addr = ipaddress.ip_address(other)
            return ip_addr == ipaddress.ip_address(self._ip)
        except ValueError:
            pass
        if isinstance(other, str):
            return other in [self._name, self._room_name]
        if isinstance(other, SensemeFan):
            return self._id == other.id
        return NotImplemented

    def __hash__(self) -> int:
        """Hash magic method."""
        return hash(self._id)

    @property
    def is_sec_info_complete(self) -> bool:
        """Return if all secondary information is complete."""
        if self._fw_version is None:
            return False
        if self._has_light is None:
            return False
        if self._room_name is None:
            return False
        return True

    async def _query_device(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, cmd: str
    ) -> str:
        """Send command to SenseME device and parses response.

        None is returned if response was 'ERROR;PARSE'
        """
        msg = f"<{self.name};{cmd};GET>"
        # _LOGGER.debug("Sent command: '%s'", msg)
        writer.write(msg.encode("utf-8"))
        leftover = ""
        while True:
            # socket will throw a timeout error and abort this function if
            # no proper response is received
            data = await reader.read(1048)
            data = data.decode("utf-8")
            data = leftover + data
            leftover = ""
            # The data received may have multiple parenthesized data
            # points. Split them and put each message onto the queue.
            # Convert "(msg1)(msg2)(msg3)" to "(msg1)|(msg2)|(msg3)"
            # then split on the '|'
            for rsp in data.replace(")(", ")|(").split("|"):
                if rsp[-1] != ")":
                    self._leftover = rsp
                else:
                    # _LOGGER.debug("Received response: '%s'" ,p)
                    # remove '(device name' at the beginning and the ')' at
                    # the end of the string
                    _, result = rsp[:-1].split(";", 1)
                    values = result.split(";")
                    key = ";".join(values[:-1])
                    value = ";".join(values[-1:])
                    if key == "ERROR":
                        _LOGGER.error("%s: Sent bad command: %s", self._name, msg)
                    else:
                        if cmd in rsp:
                            # correct response, return the value
                            # _LOGGER.debug("Received response: '%s'", value)
                            return value

    async def fill_out_sec_info(self) -> bool:
        """Retrieve secondary info from the SenseME device directly.

        Secondary data is fw_version, has_light and room_name which can only be
        filled in after connecting with the device. The secondary data is also populated
        when the device is started and after the device is connected.
        This method is a coroutine.
        """
        if self.is_sec_info_complete:
            # info is already complete
            return True
        try:
            reader, writer = await asyncio.open_connection(self.ip, PORT)
            self._fw_name = await self._query_device(reader, writer, "FW;NAME")
            self._fw_version = await self._query_device(
                reader, writer, f"FW;{self._fw_name}"
            )
            self._has_light = (
                await self._query_device(reader, writer, "DEVICE;LIGHT")
            ).upper() in ("PRESENT", "PRESENT;COLOR")
            self._room_name = await self._query_device(reader, writer, "GROUP;LIST")
            return True
        except OSError:
            _LOGGER.debug(
                "%s: Failed to retrieve secondary information from device\n%s",
                self._name,
                traceback.format_exc(),
            )
            return False
        finally:
            # close the socket
            writer.close()
            await writer.wait_closed()

    @property
    def name(self) -> str:
        """Return name of device."""
        return self._name

    @property
    def id(self) -> str:
        """Return id of device. Also known as MAC address."""
        return self._id

    @property
    def mac(self) -> str:
        """Return MAC address of device. Also known as id."""
        return self._id

    @property
    def ip(self) -> str:
        """Return IP address of device."""
        return self._ip

    @property
    def connected(self) -> bool:
        """Return True when device is connected."""
        return self._is_connected

    @property
    def model(self) -> str:
        """Return Model of device."""
        return DEVICE_MODELS.get(self._model.upper(), self._model.upper())

    @property
    def device_type(self) -> str:
        """Return type of device."""
        return DEVICE_TYPES.get(self._model.upper(), "FAN")

    @classmethod
    def models(cls) -> list:
        """Return list of possible model names."""
        no_duplicates = []
        for model_name in DEVICE_MODELS.values():
            if model_name not in no_duplicates:
                no_duplicates.append(model_name)
        return no_duplicates

    @property
    def fw_version(self) -> str:
        """Return the version of the firmware running on the SenseME device."""
        return self._fw_version

    @property
    def has_light(self) -> bool:
        """Return True if the device has an installed light."""
        return self._has_light

    @property
    def device_indicators(self) -> str:
        """Return True if the device LED indicator is enabled."""
        value = self._data.get("DEVICE;INDICATORS", None)
        if value:
            return value == "ON"
        return None

    @device_indicators.setter
    def device_indicators(self, value: bool):
        """Enable/disable the device LED indicator."""
        if value:
            state = "ON"
        else:
            state = "OFF"
        self._send_command(f"DEVICE;INDICATORS;{state}")

    @property
    def device_beeper(self) -> bool:
        """Return the device audible alert enabled state."""
        status = self._data.get("DEVICE;BEEPER", None)
        if status:
            return status == "ON"
        return None

    @device_beeper.setter
    def device_beeper(self, value: bool):
        """Enable/disable the device audible alert."""
        if value:
            state = "ON"
        else:
            state = "OFF"
        self._send_command(f"DEVICE;BEEPER;{state}")

    @property
    def network_ap_on(self) -> bool:
        """Return the wireless access point running state."""
        status = self._data.get("NW;AP;STATUS", None)
        if status:
            return status == "ON"
        return None

    @property
    def network_dhcp_on(self) -> bool:
        """Return the device local DHCP service running state."""
        dhcp = self._data.get("NW;DHCP", None)
        if dhcp:
            return dhcp == "ON"
        return None

    @property
    def network_ip(self) -> str:
        """Return the network IP address of the device.

        This IP address is reported by the SenseME device and not necessarily the same IP
        address used to connect with the device.
        """
        addresses = self._data.get("NW;PARAMS;ACTUAL", None)
        if addresses:
            addresses = addresses.split(";")
            return addresses[0]
        return None

    @property
    def network_gateway(self) -> str:
        """Return the network gateway address of the device."""
        addresses = self._data.get("NW;PARAMS;ACTUAL", None)
        if addresses:
            addresses = addresses.split(";")
            return addresses[1]
        return None

    @property
    def network_subnetmask(self) -> str:
        """Return the network gateway address of the device."""
        addresses = self._data.get("NW;PARAMS;ACTUAL", None)
        if addresses:
            addresses = addresses.split(";")
            return addresses[2]
        return None

    @property
    def network_ssid(self) -> str:
        """Return the wireless SSID the device is connected to."""
        return self._data.get("NW;SSID", None)

    @property
    def network_token(self) -> str:
        """Return the network token of the device."""
        return self._data.get("NW;TOKEN", None)

    @property
    def room_status(self) -> bool:
        """Return True if the device is in a room."""
        room_name = self._data.get("GROUP;LIST", None)
        room_type = self._data.get("GROUP;ROOM;TYPE", None)
        if room_name and room_type:
            return room_name != "EMPTY" and room_type != "0"
        return None

    @property
    def room_name(self) -> str:
        """Return the room name of the device.

        'EMPTY' is returned if not in a group.
        """
        return self._data.get("GROUP;LIST", None)

    @property
    def room_type(self) -> str:
        """Return the room type of the device."""
        room_type = int(self._data.get("GROUP;ROOM;TYPE", None))
        if room_type:
            if room_type >= len(ROOM_TYPES):
                room_type = 0
            return ROOM_TYPES[room_type]
        return None

    @property
    def light_on(self) -> bool:
        """Return True when light is on at any brightness."""
        state = self._data.get("LIGHT;PWR", None)
        if state:
            return state == "ON"
        return None

    @light_on.setter
    def light_on(self, state: bool):
        """Set the light power state."""
        value = "ON" if state else "OFF"
        self._send_command(f"LIGHT;PWR;{value}")

    @property
    def light_brightness(self) -> int:
        """Return the light brightness."""
        level = self._data.get("LIGHT;LEVEL;ACTUAL", None)
        if level:
            return int(level)
        return None

    @light_brightness.setter
    def light_brightness(self, level: int):
        """Set the light brightness."""
        if level < 0:
            level = 0
        if level > 16:
            level = 16
        self._send_command(f"LIGHT;LEVEL;SET;{level}")

    @property
    def light_brightness_min(self) -> int:
        """Return the light brightness minimum."""
        min_brightness = self._data.get("LIGHT;LEVEL;MIN", None)
        if min_brightness:
            return int(min_brightness)
        return None

    @property
    def light_brightness_max(self) -> int:
        """Return the light brightness maximum."""
        max_brightness = self._data.get("LIGHT;LEVEL;MAX", None)
        if max_brightness:
            return int(max_brightness)
        return None

    @property
    def light_brightness_limits_room(self) -> Tuple:
        """Return a tuple of the min and max light brightness for the room.

        A room can limit the minimum/maximum light brightness while keeping the same
        number of light brightness levels. On the Haiku by BAF application this setting
        can be found by clicking the room info button. You have to have at least one
        fan with installed light added to a room.
        """
        raw = self._data.get("LIGHT;BOOKENDS", None)
        if raw is None:
            return None
        values = raw.split(";")
        if len(values) != 2:
            return None
        min_bright = int(values[0])
        max_bright = int(values[1])
        return min_bright, max_bright

    @property
    def motion_sensor(self) -> bool:
        """Return True when device motion sensor says room is occupied.

        Available on all SenseME fans.
        """
        status = self._data.get("SNSROCC;STATUS", None)
        if status:
            return status == "OCCUPIED"
        return None

    def add_callback(self, callback: Callable):
        """Add callback function/coroutine. Called when parameters are updated."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            if inspect.iscoroutinefunction(callback):
                _LOGGER.debug("%s: Added coroutine callback", self._name)
            else:
                _LOGGER.debug("%s: Added function callback", self._name)

    def remove_callback(self, callback):
        """Remove existing callback function/coroutine."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            _LOGGER.debug("%s: Removed callback", self._name)

    async def update(self) -> bool:
        """Wait for first update of all parameters in SenseME device.

        This method is a coroutine.
        """
        if self._first_update:
            return True
        if self._is_running is False:
            self.start()
        start = int(time.time())
        while not self._first_update:
            await asyncio.sleep(0.01)
            if int(time.time()) - start >= 5:
                return False
        return True

    def _execute_callbacks(self):
        """Run all callbacks to indicate something has changed."""
        for callback in self._callbacks:
            if inspect.iscoroutinefunction(callback):
                loop = asyncio.get_event_loop()
                loop.create_task(callback())
            else:
                callback()

    def _send_command(self, cmd):
        """Send a command to SenseME device."""
        msg = f"<{self._name};{cmd}>"
        self._endpoint.send(msg)
        # _LOGGER.debug("%s: Command sent '%s'", self._name, cmd)

    def _update_status(self):
        """Issues commands to get complete status from device."""
        _LOGGER.debug("%s: Status update", self._name)
        self._send_command("GETALL")
        # GETALL doesn't return the status of the motion detector,
        # so also request the motion detector status
        self._send_command("SNSROCC;STATUS;GET")

    async def _updater(self):
        """Periodically update device parameters.

        This method is a coroutine.
        """
        while True:
            try:
                self._update_status()
                await asyncio.sleep(self.refresh_minutes * 60 + random.uniform(-10, 10))
            except asyncio.CancelledError:
                _LOGGER.debug("%s: Updater task cancelled", self._name)
                return
            except OSError:
                _LOGGER.debug(
                    "%s: Updater task error\n%s", self._name, traceback.format_exc()
                )
                await asyncio.sleep(self.refresh_minutes * 60 + random.uniform(-10, 10))
            except Exception:
                _LOGGER.error(
                    "%s: Unhandled updater task error\n%s",
                    self._name,
                    traceback.format_exc(),
                )
                await asyncio.sleep(10)
                raise
        _LOGGER.error("%s: Updater task ended", self._name)

    async def _listener(self):
        """Task that listens for device status changes.

        This method is a coroutine.
        """
        while True:
            try:
                if self._error_count > 10:
                    _LOGGER.error("%s: Listener task too many errors", self._name)
                    self._is_connected = False
                    self._execute_callbacks()
                    self._updater_task.cancel()
                    if self._endpoint is not None:
                        self._endpoint.close()
                    self._endpoint = None
                    break
                if self._endpoint is None:
                    self._is_connected = False
                    self._execute_callbacks()
                    self._endpoint = SensemeEndpoint()
                    loop = asyncio.get_event_loop()
                    try:
                        _LOGGER.debug("%s: Connecting", self._name)
                        await loop.create_connection(
                            lambda: SensemeProtocol(self._name, self._endpoint),
                            self._ip,
                            PORT,
                        )
                    except OSError:
                        _LOGGER.debug(
                            "%s: Connect failed, " "try again in a minute\n%s",
                            self._name,
                            traceback.format_exc(),
                        )
                        self._endpoint = None
                        await asyncio.sleep(60)
                        continue
                    self._updater_task = loop.create_task(self._updater())
                    self._error_count = 0
                    self._is_connected = True
                    self._execute_callbacks()
                data = await self._endpoint.receive()
                if data is None:
                    # endpoint is closed, let task know it's time open another
                    _LOGGER.warning("%s: Connection lost", self._name)
                    self._is_connected = False
                    self._execute_callbacks()  # tell callbacks we disconnected
                    self._endpoint = None
                    self._updater_task.cancel()
                    await asyncio.sleep(1)
                    continue
                # add previous partial data to new data
                data = self._leftover + data
                self._leftover = ""
                # The data received may have multiple parenthesized data
                # points. Split them and put each individual message onto the
                # queue. Convert "(msg1)(msg2)(msg3)" to "(msg1)|(msg2)|(msg3)"
                # then split on the '|'
                for msg in data.replace(")(", ")|(").split("|"):
                    if msg[-1] != ")":
                        self._leftover = msg
                        continue
                    # remove '(device name' at the beginning and the ')'
                    # at the end of the string
                    _, result = msg[:-1].split(";", 1)
                    # most messages have only one value at the end
                    valuecount = 1
                    if "BOOKENDS" in result:
                        valuecount = 2
                    elif "NW;PARAMS;ACTUAL" in result:
                        valuecount = 3
                    elif "DEVICE;LIGHT" in result:
                        valuecount = len(result.split(";")) - 2
                    # split on ';' and the associate the correct
                    # number of values
                    values = result.split(";")
                    key = ";".join(values[:-valuecount])
                    value = ";".join(values[-valuecount:])
                    if key == "ERROR":
                        _LOGGER.error(
                            "%s: Command error response: '%s'", self._name, value,
                        )
                        continue
                    if key == "TIME;VALUE":
                        # ignore time parameter
                        continue
                    if self._data.get(key, "?????") == value:
                        # parameter is the same value
                        continue
                    if key == "SNSROCC;TIMEOUT;MIN":
                        # first update complete when SNSROCC;TIMEOUT;MIN is received
                        # last parameter common to both Haiku Fan and Haiku Light
                        self._first_update = True
                    self._data[key] = value
                    _LOGGER.debug(
                        "%s: Param updated: [%s]='%s'", self._name, key, value,
                    )
                    # update certain local variables that are not part of data
                    if key == "FW;NAME":
                        self._fw_name = value
                    elif key == ("FW;" + self._fw_name):
                        self._fw_version = value
                    elif key == "DEVICE;LIGHT":
                        value = value.upper()
                        self._has_light = value in ("PRESENT", "PRESENT;COLOR")
                    elif key == "GROUP;LIST":
                        self._room_name = value
                    self._execute_callbacks()
            except asyncio.CancelledError:
                _LOGGER.debug("%s: Listener task cancelled", self._name)
                return
            except OSError:
                _LOGGER.debug(
                    "%s: Listener task\n%s", self._name, traceback.format_exc()
                )
                self._error_count += 1
                await asyncio.sleep(1)
            except Exception:
                _LOGGER.error(
                    "%s: Listener task error\n%s", self._name, traceback.format_exc()
                )
                raise
        _LOGGER.error("%s: Listener task ended", self._name)

    def start(self):
        """Start the async task to handle responses from the device."""
        if not self._is_running:
            loop = asyncio.get_event_loop()
            self._listener_task = loop.create_task(self._listener())
            self._is_running = True
            _LOGGER.debug("%s: Started", self._name)

    def stop(self):
        """Signals thread to stop and returns immediately."""
        if self._is_running is True:
            self._listener_task.cancel()
            self._updater_task.cancel()
            self._is_running = False


class SensemeFan(SensemeDevice):
    """SensemeFan Class."""

    def __str__(self) -> str:
        """Return string representation of SensemeFan object."""
        string = f"Name: {self._name}"
        if self._room_name is not None:
            string += f", Room Name: {self._room_name}"
        string += f", ID: {self._id}"
        string += f", IP: {self._ip}"
        string += f", Model: {self.model}"
        if self._fw_version is not None:
            string += f", FW Version: {self._fw_version}"
        if self._has_light is not None:
            string += f", Has Light: {self._has_light}"
        return string

    @property
    def is_fan(self) -> str:
        """Return True if this device is a fan."""
        return True

    @property
    def is_light(self) -> str:
        """Return True if the device is a standalone light."""
        return False

    @property
    def has_light(self) -> bool:
        """Return True if the fan has an installed light."""
        return self._has_light

    @property
    def fan_on(self) -> bool:
        """Return True when fan is on at any speed."""
        state = self._data.get("FAN;PWR", None)
        if state:
            return state == "ON"
        return None

    @fan_on.setter
    def fan_on(self, state: bool):
        """Set the fan power state."""
        state = "ON" if state else "OFF"
        self._send_command(f"FAN;PWR;{state}")

    @property
    def fan_speed(self) -> int:
        """Return the fan speed."""
        speed = self._data.get("FAN;SPD;ACTUAL", None)
        if speed:
            return int(speed)
        return None

    @fan_speed.setter
    def fan_speed(self, speed: int):
        """Set the fan speed."""
        if speed < 0:
            speed = 0
        elif speed > self.fan_speed_max:
            speed = self.fan_speed_max
        self._send_command(f"FAN;SPD;SET;{speed}")

    @property
    def fan_speed_min(self) -> int:
        """Return the fan speed minimum."""
        min_speed = self._data.get("FAN;SPD;MIN", None)
        if min_speed:
            return int(min_speed)
        return None

    @property
    def fan_speed_max(self) -> int:
        """Return the fan speed maximum."""
        max_speed = self._data.get("FAN;SPD;MAX", None)
        if max_speed:
            return int(max_speed)
        return None

    @property
    def fan_speed_limits_room(self) -> Tuple:
        """Return a tuple of the min/max fan speeds the room is configured to support.

        A room can limit the minimum/maximum fan speed while keeping the same number of
        speed settings. On the Haiku by BAF application this setting can be found by
        clicking the room info button. There must be at least one fan added to a room.
        """
        raw = self._data.get("FAN;BOOKENDS", None)
        if raw is None:
            return None
        values = raw.split(";")
        if len(values) != 2:
            return None
        min_speed = int(values[0])
        max_speed = int(values[1])
        return min_speed, max_speed

    @fan_speed_limits_room.setter
    def fan_speed_limits_room(self, speeds: Tuple):
        """Set a tuple of the min/max fan speeds the room is configured to support."""
        if speeds[0] >= speeds[1]:
            _LOGGER.error("Min speed cannot exceed max speed")
            return
        self._send_command(f"FAN;BOOKENDS;SET;{speeds[0]};{speeds[1]}")

    @property
    def fan_dir(self) -> str:
        """Return the fan direction."""
        return self._data.get("FAN;DIR", None)

    @fan_dir.setter
    def fan_dir(self, direction: str):
        """Set the fan direction."""
        if direction not in DIRECTIONS:
            raise ValueError(
                f"{direction} is not a valid direction. Must be one of {DIRECTIONS}"
            )
        self._send_command(f"FAN;DIR;SET;{direction}")

    @property
    def fan_whoosh(self) -> bool:
        """Return True when fan whoosh mode is on."""
        state = self._data.get("FAN;WHOOSH;STATUS", None)
        if state:
            return state == "ON"
        return None

    @fan_whoosh.setter
    def fan_whoosh(self, state: bool):
        """Set the fan whoosh mode."""
        value = "ON" if state else "OFF"
        self._send_command(f"FAN;WHOOSH;{value}")

    @property
    def fan_autocomfort(self) -> str:
        """Get the auto comfort mode from the fan.

        'OFF' no automatic adjustment.
        'COOLING' increases fan speed as temp increases.
        'HEATING' means slow mixing of air while room is occupied and faster mix speeds
                  while room is not occupied.
        'FOLLOWTSTAT' means change between 'COOLING' and 'HEATING based on thermostat.
        """
        return self._data.get("SMARTMODE;STATE", None)

    @fan_autocomfort.setter
    def fan_autocomfort(self, state: str):
        """Set the fan auto comfort mode.

        'OFF' no automatic adjustment.
        'COOLING' increases fan speed as temp increases.
        'HEATING' means slow mixing of air while room is occupied and faster mix speeds
                  while room is not occupied.
        'FOLLOWTSTAT' means change between 'COOLING' and 'HEATING based on thermostat.
        """
        value = "ON" if state else "OFF"
        self._send_command(f"SMARTMODE;STATE;SET;{value}")

    @property
    def fan_smartmode(self) -> str:
        """Get the current smart mode from the fan.

        'OFF' no automatic adjustment.
        'COOLING' increases fan speed as temp increases.
        'HEATING' means slow mixing of air while room is occupied and faster mix speeds
                  while room is not occupied.
        """
        return self._data.get("SMARTMODE;ACTUAL", None)

    @property
    def fan_cooltemp(self) -> float:
        """Return the auto shutoff temperature for 'COOLING' smart mode in Celsius."""
        temp = int(self._data.get("LEARN;ZEROTEMP", None))
        if temp:
            return float(temp) / 100.0
        return None

    @fan_cooltemp.setter
    def fan_cooltemp(self, temp: float):
        """Set the auto shutoff temperature for 'COOLING' smart mode in Celsius."""
        # force temperature into range
        if temp < 10:
            temp = 10
        elif temp > 31.5:
            temp = 31.5
        temp = int(round(temp * 100))
        self._send_command(f"LEARN;ZEROTEMP;SET;{temp}")

    @property
    def motion_fan_auto(self) -> bool:
        """Return True when fan is in automatic on with motion mode."""
        state = self._data.get("FAN;AUTO", None)
        if state:
            return state == "ON"
        return None

    @motion_fan_auto.setter
    def motion_fan_auto(self, state: bool):
        """Set the fan automatic on with motion mode."""
        state = "ON" if state else "OFF"
        self._send_command(f";FAN;AUTO;{state}")

    @property
    def motion_light_auto(self) -> bool:
        """Return True when light is in automatic on with motion mode."""
        state = self._data.get(";LIGHT;AUTO", None)
        if state:
            return state == "ON"
        return None

    @motion_light_auto.setter
    def motion_light_auto(self, state: bool):
        """Set the light automatic on with motion mode."""
        state = "ON" if state else "OFF"
        self._send_command(f";LIGHT;AUTO;{state}")


class SensemeLight(SensemeDevice):
    """SensemeLight Class."""

    def __str__(self) -> str:
        """Return string representation of SensemeFan object."""
        string = f"Name: {self._name}"
        if self._room_name is not None:
            string += f", Room Name: {self._room_name}"
        string += f", ID: {self._id}"
        string += f", IP: {self._ip}"
        string += f", Model: {self.model}"
        if self._fw_version is not None:
            string += f", FW Version: {self._fw_version}"

        return string

    @property
    def is_fan(self) -> str:
        """Return True if this device is a fan."""
        return False

    @property
    def is_light(self) -> str:
        """Return True if the device is a standalone light."""
        return True

    @property
    def has_light(self) -> bool:
        """Return True if the fan has an installed light."""
        return True

    @property
    def light_colortemp(self) -> int:
        """Return the light color temperature."""
        level = self._data.get("LIGHT;COLOR;TEMP;VALUE", None)
        if level:
            return int(level)
        return None

    @light_colortemp.setter
    def light_colortemp(self, color_temp: int):
        """Set the light color temperature."""
        if color_temp < self.light_colortemp_min:
            color_temp = self.light_colortemp_min
        if color_temp > self.light_colortemp_max:
            color_temp = self.light_colortemp_max
        color_temp = int(round(color_temp / 100.0)) * 100
        self._send_command(f"LIGHT;COLOR;TEMP;VALUE;SET;{color_temp}")

    @property
    def light_colortemp_min(self) -> int:
        """Return the light color temperature minimum."""
        min_color_temp = self._data.get("LIGHT;COLOR;TEMP;MIN", None)
        if min_color_temp:
            return int(min_color_temp)
        return None

    @property
    def light_colortemp_max(self) -> int:
        """Return the light color temperature maximum."""
        max_color_temp = self._data.get("LIGHT;COLOR;TEMP;MAX", None)
        if max_color_temp:
            return int(max_color_temp)
        return None
