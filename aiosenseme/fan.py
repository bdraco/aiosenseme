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
import logging
import random
import time
import traceback

_LOGGER = logging.getLogger(__name__)

PORT = 31415

ONOFF = ["ON", "OFF"]
DIRECTIONS = ["FWD", "REV"]
AUTOCOMFORTS = ["OFF", "COOLING", "HEATING", "FOLLOWTSTAT"]
ROOM_TYPES = [
    "Undefined",
    "Master Bedroom",
    "Bedroom",
    "Den",
    "Family Room",
    "Living Room",
    "Kids Room",
    "Kitchen",
    "Dining Room",
    "Basement",
    "Office",
    "Patio",
    "Porch",
    "Hallway",
    "Entryway",
    "Bathroom",
    "Laundry",
    "Stairs",
    "Closet",
    "Sunroom",
    "Media Room",
    "Gym",
    "Garage",
    "Outside",
    "Loft",
    "Playroom",
    "Pantry",
    "Mudroom",
]


class SensemeProtocol(asyncio.Protocol):
    """Protocol for SenseME communication."""

    def __init__(self, name, endpoint):
        self._name = name
        self._endpoint = endpoint

    # Protocol methods
    def connection_made(self, transport):
        _LOGGER.debug("%s: Connected" % self._name)
        self._endpoint._transport = transport
        self._opened = True

    def connection_lost(self, exe):
        _LOGGER.debug("%s: Connection lost" % self._name)
        self._endpoint.close()  # half-closed connections are not permitted

    # Streaming Protocol methods
    def data_received(self, data):
        if data:
            msg = data.decode("utf-8")
            try:
                self._endpoint.receive_queue.put_nowait(msg)
            except asyncio.QueueFull:
                _LOGGER.error("%s: Receive queue full" % self._name)

    def eof_received(self):
        return False  # tell the transport to close itself


class SensemeEndpoint:
    """High-level endpoint for SenseME protocol."""

    def __init__(self):
        self.receive_queue = asyncio.Queue()
        self._opened = False
        self._transport = None

    def abort(self):
        """Close the transport immediately. Buffered write data will be flushed."""
        self._transport.abort()
        self.close()

    def close(self):
        """Close the transport gracefully. Buffered write data will be sent."""
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
        """Wait for a message from the SenseME fan.
        Return None when the socket is closed.
        This method is a coroutine.
        """
        if self.receive_queue.empty() and self._transport.is_closing():
            return None
        return await self.receive_queue.get()

    def send(self, cmd):
        """Send a command to the SenseME fan."""
        self._transport.write(cmd.encode("utf-8"))


class SensemeFan:
    """SensemeFan Class."""

    def __init__(self, name, id, ip, model, refreshMinutes=1):
        self._name = name
        self.refreshMinutes = refreshMinutes
        self._id = id
        self._ip = ip
        self._model = model
        self._group_name = None
        self._fw_name = ""
        self._fw_version = None
        self._has_light = None
        self._is_running = False
        self._is_connected = False
        self._data = dict()
        self._endpoint = None
        self._listener_task = None
        self._updater_task = None
        self._errorCount = 0
        self._leftover = ""
        self._callbacks = []
        self._first_update = False

    def __eq__(self, other):
        if not isinstance(other, SensemeFan):
            return NotImplemented

        # same if they have the same id (MAC address)
        return self._id == other.id

    def __hash__(self):
        return hash(self._id)

    def __str__(self):
        string = f"Name: {self._name}"
        string += f", ID: {self._id}"
        string += f", IP: {self._ip}"
        string += f", Model: {self.model}"
        if self._group_name is not None:
            string += f", Group Name: {self._group_name}"
        if self._fw_version is not None:
            string += f", FW Version: {self._fw_version}"
        if self._has_light is not None:
            string += f", Has Light: {self._has_light}"
        return string

    @property
    def is_sec_info_complete(self) -> bool:
        """Return if all secondary information is complete."""
        if self._fw_version is None:
            return False
        if self._has_light is None:
            return False
        if self._group_name is None:
            return False
        return True

    async def fill_out_sec_info(self) -> bool:
        """Retrieves secondary info (fw_version, has_light and group_name) from the
        SenseME fan directly. The secondary data is also populated when the thread is
        started and after the fan is connected.
        This method is a coroutine.
        """

        async def _query_fan(reader, writer, cmd) -> str:
            """Sends command to SenseME fan and parses response.

            None is returned if response was 'ERROR;PARSE'
            """
            msg = f"<{self.name};{cmd};GET>"
            # _LOGGER.debug("Sent command: '%s'" % (msg))
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
                for p in data.replace(")(", ")|(").split("|"):
                    if p[-1] != ")":
                        self._leftover = p
                    else:
                        # _LOGGER.debug("Received response: '%s'" % (p))
                        # remove '(fan name' at the beginning and the ')' at
                        # the end of the string
                        _, result = p[:-1].split(";", 1)
                        values = result.split(";")
                        key = ";".join(values[:-1])
                        value = ";".join(values[-1:])
                        if key == "ERROR":
                            _LOGGER.error(
                                "%s: Sent bad command: %s" % (self._name, msg)
                            )
                        else:
                            if cmd in p:
                                # correct response, return the value
                                return value

        if self.is_sec_info_complete:
            # info is already complete
            return True
        try:
            reader, writer = await asyncio.open_connection(self.ip, PORT)
            self._fw_name = await _query_fan(reader, writer, "FW;NAME")
            self._fw_version = await _query_fan(
                reader, writer, "FW;%s" % (self._fw_name)
            )
            self._has_light = (
                await _query_fan(reader, writer, "DEVICE;LIGHT")
            ).upper() == "PRESENT"
            self._group_name = await _query_fan(reader, writer, "GROUP;LIST")
            return True
        except Exception:
            _LOGGER.debug(
                "%s: Failed to retrieve secondary information from fan\n%s"
                % (self._name, traceback.format_exc())
            )
            return False
        finally:
            # close the socket
            writer.close()
            await writer.wait_closed()

    @property
    def name(self) -> str:
        """Return name of fan."""
        return self._name

    @property
    def id(self) -> str:
        """Return MAC address of fan. Also known as id."""
        return self._id

    @property
    def ip(self) -> str:
        """Return IP address of fan."""
        return self._ip

    @property
    def connected(self) -> bool:
        """Return True when fan is connected."""
        return self._is_connected

    @property
    def model(self) -> str:
        """Return Model of fan."""
        if "FAN" in self._model.upper() and "HAIKU" in self._model.upper():
            if self._has_light:
                return "Haiku Fan with Light"
            else:
                return "Haiku Fan"
        elif "FAN" in self._model.upper() and "LSERIES" in self._model.upper():
            return "Haiku L Fan"
        else:
            return self._model

    @property
    def fw_version(self) -> str:
        """Return the version of the firmware running on the SenseME fan."""
        return self._fw_version

    @property
    def has_light(self) -> bool:
        """Return True if the fan has an installed light."""
        return self._has_light

    @property
    def device_indicators(self) -> str:
        """Return True if the device LED indicator is enabled."""
        value = self._data.get("DEVICE;INDICATORS", None)
        if value:
            return value == "ON"
        else:
            return None

    @device_indicators.setter
    def device_indicators(self, value):
        """Enable/disable the device LED indicator."""
        state = "ON"
        if not value:
            state = "OFF"
        self._send_command(f"DEVICE;INDICATORS;{state}")

    @property
    def device_beeper(self) -> bool:
        """Return the device audible alert enabled state."""
        status = self._data.get("DEVICE;BEEPER", None)
        if status:
            return status == "ON"
        else:
            return None

    @device_beeper.setter
    def device_beeper(self, value):
        """Enable/disable the device audible alert."""
        state = "ON"
        if not value:
            state = "OFF"
        self._send_command(f"DEVICE;BEEPER;{state}")

    @property
    def network_ap_on(self) -> bool:
        """Return the wireless access point running state."""
        status = self._data.get("NW;AP;STATUS", None)
        if status:
            return status == "ON"
        else:
            return None

    @property
    def network_dhcp_on(self) -> bool:
        """Return the fan local DHCP service running state."""
        dhcp = self._data.get("NW;DHCP", None)
        if dhcp:
            return dhcp == "ON"
        else:
            return None

    @property
    def network_ip(self) -> str:
        """Return the network IP address of the fan.
        This IP address is reported by the SenseME fan and not necessarily the same IP
        address used to connect with the fan.
        """
        addresses = self._data.get("NW;PARAMS;ACTUAL", None)
        if addresses:
            addresses = addresses.split(";")
            return addresses[0]
        else:
            return None

    @property
    def network_gateway(self) -> str:
        """Return the network gateway address of the fan."""
        addresses = self._data.get("NW;PARAMS;ACTUAL", None)
        if addresses:
            addresses = addresses.split(";")
            return addresses[1]
        else:
            return None

    @property
    def network_subnetmask(self) -> str:
        """Return the network gateway address of the fan."""
        addresses = self._data.get("NW;PARAMS;ACTUAL", None)
        if addresses:
            addresses = addresses.split(";")
            return addresses[2]
        else:
            return None

    @property
    def network_ssid(self) -> str:
        """Return the wireless SSID the fan is connected to."""
        return self._data.get("NW;SSID", None)

    @property
    def network_token(self) -> str:
        """Return the network token of the fan."""
        return self._data.get("NW;TOKEN", None)

    @property
    def group_status(self) -> bool:
        """Return True if the fan is in a group."""
        group_name = self._data.get("GROUP;LIST", None)
        group_type = self._data.get("GROUP;ROOM;TYPE", None)
        if group_name and group_type:
            return group_name != "EMPTY" and group_type != "0"
        else:
            return None

    @property
    def group_name(self) -> str:
        """Return the group name of the fan.

        'EMPTY' is returned if not in a group.
        """
        return self._data.get("GROUP;LIST", None)

    @property
    def group_room_type(self) -> str:
        """Return the group room type of the fan."""
        group_type = int(self._data.get("GROUP;ROOM;TYPE", None))
        if group_type:
            if group_type >= len(ROOM_TYPES):
                group_type = 0
            return ROOM_TYPES[group_type]
        else:
            return None

    @property
    def fan_on(self) -> bool:
        """Return True when fan is on at any speed."""
        state = self._data.get("FAN;PWR", None)
        if state:
            return True if state == "ON" else False
        else:
            return None

    @fan_on.setter
    def fan_on(self, state):
        """Set the fan power state."""
        state = "ON" if state else "OFF"
        self._send_command(f"FAN;PWR;{state}")

    @property
    def fan_speed(self) -> int:
        """Return the fan speed."""
        speed = self._data.get("FAN;SPD;ACTUAL", None)
        if speed:
            return int(speed)
        else:
            return None

    @fan_speed.setter
    def fan_speed(self, speed):
        """Sets the fan speed."""
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
        else:
            return None

    @property
    def fan_speed_max(self) -> int:
        """Return the fan speed maximum."""
        max_speed = self._data.get("FAN;SPD;MAX", None)
        if max_speed:
            return int(max_speed)
        else:
            return None

    @property
    def fan_speed_limits_room(self):
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
        min = int(values[0])
        max = int(values[1])
        return min, max

    @fan_speed_limits_room.setter
    def fan_speed_limits_room(self, speeds):
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
    def fan_dir(self, dir: str):
        """Set the fan direction."""
        if dir not in DIRECTIONS:
            raise ValueError(
                f"{dir} is not a valid direction. Must be one of {DIRECTIONS}"
            )
        self._send_command(f"FAN;DIR;SET;{dir}")

    @property
    def fan_whoosh(self) -> bool:
        """Return True when fan whoosh mode is on."""
        state = self._data.get("FAN;WHOOSH;STATUS", None)
        if state:
            return True if state == "ON" else False
        else:
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
        else:
            return None

    @fan_cooltemp.setter
    def fan_cooltemp(self, temp):
        """Set the auto shutoff temperature for 'COOLING' smart mode in Celsius."""
        # force temperature into range
        if temp < 10:
            temp = 10
        elif temp > 31.5:
            temp = 31.5
        temp = int(round(temp * 100))
        self._send_command(f"LEARN;ZEROTEMP;SET;{temp}")

    @property
    def light_on(self) -> bool:
        """Return True when light is on at any brightness."""
        state = self._data.get("LIGHT;PWR", None)
        if state:
            return True if state == "ON" else False
        else:
            return None

    @light_on.setter
    def light_on(self, state):
        """Set the light power state."""
        value = "ON" if state else "OFF"
        self._send_command(f"LIGHT;PWR;{value}")

    @property
    def light_brightness(self) -> int:
        """Return the light brightness."""
        level = self._data.get("LIGHT;LEVEL;ACTUAL", None)
        if level:
            return int(level)
        else:
            return None

    @light_brightness.setter
    def light_brightness(self, level):
        """Sets the light brightness."""
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
        else:
            return None

    @property
    def light_brightness_max(self) -> int:
        """Return the light brightness maximum."""
        max_brightness = self._data.get("LIGHT;LEVEL;MAX", None)
        if max_brightness:
            return int(max_brightness)
        else:
            return None

    @property
    def light_brightness_limits_room(self):
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
        min = int(values[0])
        max = int(values[1])
        return min, max

    @light_brightness_limits_room.setter
    def light_brightness_limits_room(self, speeds):
        """Set a tuple of the min and max light brightness for the room."""
        if speeds[0] >= speeds[1]:
            _LOGGER.error("Min speed cannot exceed max speed")
            return
        self._send_command(f"LIGHT;BOOKENDS;SET;{speeds[0]};{speeds[1]}")

    @property
    def motion_sensor(self) -> bool:
        """Return True when fan motion sensor says room is occupied.

        Available on all SenseME fans.
        """
        status = self._data.get("SNSROCC;STATUS", None)
        if status:
            return status == "OCCUPIED"
        else:
            return None

    @property
    def motion_fan_auto(self) -> bool:
        """Return True when fan is in automatic on with motion mode."""
        state = self._data.get("FAN;AUTO", None)
        if state:
            return True if state == "ON" else False
        else:
            return None

    @motion_fan_auto.setter
    def motion_fan_auto(self, state):
        """Set the fan automatic on with motion mode."""
        state = "ON" if state else "OFF"
        self._send_command(f";FAN;AUTO;{state}")

    @property
    def motion_light_auto(self) -> bool:
        """Return True when light is in automatic on with motion mode."""
        state = self._data.get(";LIGHT;AUTO", None)
        if state:
            return True if state == "ON" else False
        else:
            return None

    @motion_light_auto.setter
    def motion_light_auto(self, state):
        """Set the light automatic on with motion mode."""
        state = "ON" if state else "OFF"
        self._send_command(f";LIGHT;AUTO;{state}")

    def add_callback(self, callback):
        """Add callback function/coroutine. Called when parameters are updated."""
        if callback not in self._callbacks:
            self._callbacks.append(callback)
            if inspect.iscoroutinefunction(callback):
                _LOGGER.debug("%s: Added coroutine callback" % self._name)
            else:
                _LOGGER.debug("%s: Added function callback" % self._name)

    def remove_callback(self, callback):
        """Remove existing callback function/coroutine."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
            _LOGGER.debug("%s: Removed callback" % self._name)

    async def update(self) -> bool:
        """Wait for first update of all parameters in SenseME fan.
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
            try:
                if inspect.iscoroutinefunction(callback):
                    loop = asyncio.get_event_loop()
                    loop.create_task(callback())
                else:
                    callback()
            except Exception:
                _LOGGER.error(
                    "%s: Callback error\n%s" % (self._name, traceback.format_exc())
                )

    def _send_command(self, cmd):
        """Send a command to SenseME fan."""
        msg = "<%s;%s>" % (self._name, cmd)
        self._endpoint.send(msg)
        # _LOGGER.debug("%s: Command sent '%s'" % (self._name, cmd))

    def _update_status(self):
        """Issues commands to get complete status from fan."""
        _LOGGER.debug("%s: Status update" % self._name)
        self._send_command("GETALL")
        # GETALL doesn't return the status of the motion detector,
        # so also request the motion detector status
        self._send_command("SNSROCC;STATUS;GET")

    async def _updater(self):
        """Periodically update fan parameters.
        This method is a coroutine.
        """
        # _LOGGER.debug("%s: Updater task started" % self._name)
        while True:
            try:
                self._update_status()
                await asyncio.sleep(self.refreshMinutes * 60 + random.uniform(-10, 10))
            except asyncio.CancelledError:
                _LOGGER.debug("%s: Updater task cancelled" % self._name)
                return
            except Exception:
                _LOGGER.debug(
                    "%s: Updater task error\n%s" % (self._name, traceback.format_exc())
                )
                await asyncio.sleep(1)
        _LOGGER.error("%s: Updater task ended" % self._name)

    async def _listener(self):
        """This function listens for fan status changes.
        This method is a coroutine.
        """
        while True:
            try:
                if self._errorCount > 10:
                    _LOGGER.error("%s: Listener task too many errors" % self._name)
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
                        _LOGGER.debug("%s: Connecting" % self._name)
                        await loop.create_connection(
                            lambda: SensemeProtocol(self._name, self._endpoint),
                            self._ip,
                            PORT,
                        )
                    except Exception:
                        _LOGGER.debug(
                            "%s: Connect failed, "
                            "try again in a minute\n%s"
                            % (self._name, traceback.format_exc())
                        )
                        self._endpoint = None
                        await asyncio.sleep(60)
                        continue
                    self._updater_task = loop.create_task(self._updater())
                    self._errorCount = 0
                    self._is_connected = True
                    self._execute_callbacks()
                data = await self._endpoint.receive()
                if data is None:
                    # endpoint is closed, let task know it's time open another
                    _LOGGER.warning("%s: Connection lost" % self._name)
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
                for p in data.replace(")(", ")|(").split("|"):
                    if p[-1] != ")":
                        self._leftover = p
                    else:
                        try:
                            # remove '(fan name' at the beginning and the ')'
                            # at the end of the string
                            _, result = p[:-1].split(";", 1)
                            # most messages have only one value at the end
                            valuecount = 1
                            if "BOOKENDS" in result:
                                valuecount = 2
                            elif "NW;PARAMS;ACTUAL" in result:
                                valuecount = 3
                            # split on ';' and the associate the correct
                            # number of values
                            values = result.split(";")
                            key = ";".join(values[:-valuecount])
                            value = ";".join(values[-valuecount:])
                            if key == "ERROR":
                                _LOGGER.error(
                                    "%s: Command error response: '%s'"
                                    % (self._name, value)
                                )
                            else:
                                # first update when WINTERMODE;STATE is received
                                if key == "WINTERMODE;STATE":
                                    self._first_update = True
                                # update parameter only if changed and not
                                # "TIME;VALUE"
                                if (
                                    self._data.get(key, "?????") != value
                                    and key != "TIME;VALUE"
                                ):
                                    self._data[key] = value
                                    _LOGGER.debug(
                                        "%s: Param updated: [%s]='%s'"
                                        % (self._name, key, value)
                                    )
                                    # update certain local variables
                                    # that are not part of data
                                    if key == "FW;NAME":
                                        self._fw_name = value
                                    elif key == ("FW;" + self._fw_name):
                                        self._fw_version = value
                                    elif key == "DEVICE;LIGHT":
                                        value = value.upper()
                                        self._has_light = value == "PRESENT"
                                    elif key == "GROUP;LIST":
                                        self._group_name = value
                                    self._execute_callbacks()
                        except Exception as e:
                            self._errorCount += 1
                            _LOGGER.error(
                                "%s: Failed to parse message '%s', error: %s"
                                % (self._name, p, str(e))
                            )
            except asyncio.CancelledError:
                _LOGGER.debug("%s: Listener task cancelled" % self._name)
                return
            except Exception:
                _LOGGER.debug(
                    "%s: Listener task\n%s" % (self._name, traceback.format_exc())
                )
                self._errorCount += 1
                await asyncio.sleep(1)
        _LOGGER.error("%s: Listener task ended" % self._name)

    def start(self):
        """Start the async task to handle responses from the fan."""
        if not self._is_running:
            loop = asyncio.get_event_loop()
            self._listener_task = loop.create_task(self._listener())
            self._is_running = True
            # _LOGGER.debug("%s: Started" % self._name)

    def stop(self):
        """Signals thread to stop and returns immediately."""
        if self._is_running is True:
            self._listener_task.cancel()
            self._updater_task.cancel()
            self._is_running = False
