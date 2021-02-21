"""Script interface for aiosenseme library."""

import argparse
import asyncio
import json
import logging
from typing import List

import aiosenseme
from aiosenseme import SensemeDevice, SensemeDiscovery, __version__

ARGS = argparse.ArgumentParser(
    description="Discover and control SenseME devices by Big Ass Fans."
)
ARGS.add_argument(
    "-V",
    "--version",
    action="store_true",
    dest="version",
    default=False,
    help="display version number",
)
ARGS.add_argument(
    "--debug",
    action="store_true",
    dest="debug",
    default=False,
    help="enable debug level logging",
)
ARGS.add_argument(
    "--listen",
    action="store_true",
    dest="listen",
    default=False,
    help="Connect to device and show changes to the fan",
)
ARGS.add_argument(
    "-j",
    "--json",
    action="store_true",
    dest="json",
    default=False,
    help="return device information and state as json",
)
ARGS.add_argument(
    "-d",
    "--discover",
    action="store_true",
    dest="discover",
    default=False,
    help="discover all SenseME devices on the network",
)
ARGS.add_argument(
    "-m",
    "--models",
    action="store_true",
    dest="models",
    default=False,
    help="list known SenseME device models",
)
ARGS.add_argument(
    "-i",
    "--ip",
    action="store",
    dest="ip",
    default=None,
    help="IP Address",
)
ARGS.add_argument(
    "-n",
    "--name",
    action="store",
    dest="name",
    default=None,
    help="SenseME device name",
)
ARGS.add_argument(
    "-f",
    "--fan",
    action="store",
    dest="fan",
    default=None,
    choices=["on", "off"],
    help="fan power",
)
ARGS.add_argument(
    "-s",
    "--speed",
    action="store",
    dest="speed",
    default=None,
    type=int,
    choices=range(1, 8),
    help="fan speed",
)
ARGS.add_argument(
    "-l",
    "--light",
    action="store",
    dest="light",
    default=None,
    choices=["on", "off"],
    help="light power",
)
ARGS.add_argument(
    "-b",
    "--brightness",
    action="store",
    dest="brightness",
    default=None,
    type=int,
    choices=range(0, 17),
    help="light brightness",
)
ARGS.add_argument(
    "-c",
    "--colortemp",
    action="store",
    dest="colortemp",
    default=None,
    type=int,
    choices=range(2200, 5100, 100),
    help="light color temperature",
)
ARGS.add_argument(
    "-w",
    "--whoosh",
    action="store",
    dest="whoosh",
    default=None,
    choices=["on", "off"],
    help="fan whoosh mode",
)

# array of discovered devices
_DEVICES = []


def print_device(device: SensemeDevice):
    """Print information about a device."""
    msg = f"{device.name}\n"
    if device.room_status:
        msg += f"  Room Name: {device.room_name}, Room Type: {device.room_type}\n"
    if device.is_fan:
        if device.has_light:
            msg += f"  Model: {device.model} with light, "
        else:
            msg += f"  Model: {device.model} without light, "
    elif device.is_light:
        msg += f"  Model: {device.model}, "
    else:
        msg += f"  Model: {device.model}, "
    msg += f"FW Version: {device.fw_version}\n"
    msg += f"  IP Addr: {device.address}, MAC Addr: {device.mac}\n"
    msg += f"  UUID: {device.uuid}"
    print(msg)


def print_state(prefix: str, device: SensemeDevice):
    """Print information about a devices's current state."""
    msg = prefix
    if device.is_fan:
        if device.fan_on:
            msg += f": Fan is on (speed: {device.fan_speed}"
            if device.fan_whoosh_mode:
                msg += ", whoosh mode is on"
            msg += ")"
        else:
            msg += ": Fan is off"
        if device.light_on:
            msg += f", Light is on (brightness: {device.light_brightness})"
        else:
            msg += ", Light is off"
        if device.sleep_mode:
            msg += ", Sleep Mode is on"
    elif device.is_light:
        if device.light_on:
            msg += f": Light is on (brightness: {device.light_brightness}"
            msg += f", color temp: {device.light_color_temp})"
        else:
            msg += ": Light is off"
    else:
        msg += ": Unknown SenseME device"
    print(msg)


async def discovered(devices: List[SensemeDevice]):
    """Discovered SenseME device callback function.

    Called when discovery has detected a SenseME device.
    Each time a device is discovered all devices discovered are reported.
    """
    global _DEVICES
    for device in devices:
        if device not in _DEVICES:
            _DEVICES.append(device)
            print_device(device)


async def process_args():
    """Process command line arguments."""
    try:
        device = None
        args = ARGS.parse_args()
        if args.debug or args.listen:
            logging.basicConfig(level=logging.DEBUG)
        if args.version is True:
            print("aiosenseme %s" % __version__)
            print("Copyright (C) 2021 by Mike Lawrence")
            print(
                "This is free software. "
                "You may redistribute copies of it under the terms"
            )
            print(
                "of the GNU General Public License "
                "<http://www.gnu.org/licenses/gpl.html>."
            )
            print("There is NO WARRANTY, to the extent permitted by law.")
            return
        if args.discover is True:
            try:
                print("Attempting to discover SenseME devices...")
                discovery = SensemeDiscovery(start_first=True)
                discovery.add_callback(discovered)
                discovery.start()
                await asyncio.sleep(5)
                count = len(discovery.devices)
                if count == 0:
                    print("Found no SenseME devices.")
                else:
                    if count == 1:
                        plural = ""
                    else:
                        plural = "s"
                    print(f"Found {count} SenseME device{plural}.")
            finally:
                discovery.stop()
                return
        if args.models is True:
            msg = "Known SenseME models: "
            first = True
            for model in SensemeDevice.models():
                if first:
                    first = False
                    msg += model
                else:
                    msg += ", " + model
            print(msg)
            return
        if not args.name and not args.ip:
            print("You must specify a SenseME device by using -n/--name or -i/--ip")
            return
        if args.ip is not None:
            device = await aiosenseme.async_get_device_by_ip_address(
                args.ip, timeout_seconds=5
            )
            if device is None:
                print(f"Device at IP '{args.ip}' not found")
                return
            await device.async_update(timeout_seconds=5)
        elif args.name is not None:
            device = await aiosenseme.discover(args.name, 5)
            if device is None:
                print(f"Name or Room '{args.name}' not found")
                return
        if args.listen:
            while True:
                await asyncio.sleep(1.0)
        if args.json:
            info = device.get_device_info
            info["model"] = device.model
            info["fw_version"] = device.fw_version
            info["device_indicators"] = device.device_indicators
            info["device_beeper"] = device.device_beeper
            info["network_ip"] = device.network_ip
            info["network_subnetmask"] = device.network_subnetmask
            info["network_gateway"] = device.network_gateway
            info["network_ssid"] = device.network_ssid
            info["room_name"] = device.room_name
            info["room_type"] = device.room_type
            info["motion_detected"] = device.motion_detected
            info["sleep_mode"] = device.sleep_mode
            if device.is_fan:
                info["fan_on"] = device.fan_on
                info["fan_speed"] = device.fan_speed
                info["fan_speed_min"] = device.fan_speed_min
                info["fan_speed_max"] = device.fan_speed_max
                info["fan_speed_limits_room"] = device.fan_speed_limits_room
                info["fan_dir"] = device.fan_dir
                info["fan_whoosh_mode"] = device.fan_whoosh_mode
                info["fan_autocomfort"] = device.fan_autocomfort
                info["fan_smartmode"] = device.fan_smartmode
                info["fan_cooltemp"] = device.fan_cooltemp
                info["motion_fan_auto"] = device.motion_fan_auto
            if device.is_light:
                info["light_color_temp"] = device.light_color_temp
                info["light_color_temp_min"] = device.light_color_temp_min
                info["light_color_temp_max"] = device.light_color_temp_max
            if device.has_light:
                info["light_on"] = device.light_on
                info["light_brightness"] = device.light_brightness
                info["light_brightness_min"] = device.light_brightness_min
                info["light_brightness_max"] = device.light_brightness_max
                info[
                    "light_brightness_limits_room"
                ] = device.light_brightness_limits_room
                info["motion_light_auto"] = device.motion_light_auto
            print(json.dumps(info, sort_keys=True, indent=4))
            return
        print_device(device)
        print_state("State", device)
        changed = False
        if device.is_fan:
            if args.whoosh is not None:
                print(f"whoosh={args.whoosh}")
                if device.fan_whoosh_mode != (args.whoosh == "on"):
                    changed = True
                device.fan_whoosh_mode = args.whoosh == "on"
            if args.speed is not None:
                if args.fan is not None:
                    print(
                        "When specifying --fanspeed there is no " "reason to set --fan"
                    )
                if device.fan_speed != args.speed:
                    changed = True
                device.fan_speed = args.speed
            elif args.fan is not None:
                if device.fan_on != (args.fan == "on"):
                    changed = True
                device.fan_on = args.fan == "on"
            if device.has_light:
                if args.colortemp is not None:
                    print("Fan lights do not have adjustable color temperature")
                if args.brightness is not None:
                    if args.light is not None:
                        print(
                            "When specifying --brightness there is no "
                            "reason to set --light"
                        )
                    if device.light_brightness != args.brightness:
                        changed = True
                    device.light_brightness = args.brightness
                elif args.light is not None:
                    if device.light_on != (args.light == "on"):
                        changed = True
                    device.light_on = args.light == "on"
            else:
                if (
                    args.brightness is not None
                    or args.light is not None
                    or args.colortemp is not None
                ):
                    print("Fan does not have a light to adjust")
        else:
            if args.brightness is not None:
                if args.light is not None:
                    print(
                        "When specifying --brightness there is no "
                        "reason to set --light"
                    )
                if device.light_brightness != args.brightness:
                    changed = True
                device.light_brightness = args.brightness
            elif args.light is not None:
                if device.light_on != (args.light == "on"):
                    changed = True
                device.light_on = args.light == "on"
            if args.colortemp is not None:
                if device.light_color_temp != args.colortemp:
                    changed = True
                device.light_color_temp = args.colortemp
        if changed:
            await asyncio.sleep(1.0)
            print_state("New State", device)
    finally:
        if device is not None:
            device.stop()


def cli():
    """Command line interface for SensemeDiscovery."""
    task = asyncio.Task(process_args())
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(task)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
