"""Script interface for aiosenseme library."""

import argparse
import asyncio
import logging
from typing import List

import aiosenseme
from aiosenseme import SensemeDiscovery, SensemeFan
from aiosenseme import __version__

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
    "--listen",
    action="store",
    dest="listen",
    default=None,
    help="listen to SenseME device name or IP address",
)
ARGS.add_argument(
    "--debug",
    action="store_true",
    dest="debug",
    default=False,
    help="enable debug level logging",
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
    "-n",
    "--name",
    action="store",
    dest="name",
    default=None,
    help="SenseME device name, room name or IP address",
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
    choices=range(0, 8),
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


def print_device(device: SensemeFan):
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
    msg += f"  IP Addr: {device.ip}, MAC Addr: {device.mac}\n"
    msg += f"  Token: {device.network_token}"
    print(msg)


def print_state(prefix: str, device: SensemeFan):
    """Print information about a devices's current state."""
    msg = prefix
    if device.is_fan:
        if device.fan_on:
            msg += f": Fan is on (speed: {device.fan_speed}"
            if device.fan_whoosh:
                msg += ", whoosh: on)"
            else:
                msg += ", whoosh: off)"
        else:
            msg += ": Fan is off"
        if device.light_on:
            msg += f", Light is on (brightness: {device.light_brightness})"
        else:
            msg += ", Light is off"
    elif device.is_light:
        if device.light_on:
            msg += f": Light is on (brightness: {device.light_brightness}, color temp: {device.light_colortemp})"
        else:
            msg += ": Light is off"
    else:
        msg += ": Unknown SenseME device"
    print(msg)


async def discovered(devices: List[SensemeFan]):
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
    args = ARGS.parse_args()
    if args.debug is True:
        logging.basicConfig(level=logging.DEBUG)
    if args.version is True:
        print("aiosenseme %s" % __version__)
        print("Copyright (C) 2020 by Mike Lawrence")
        print(
            "This is free software. You may redistribute copies of it under the terms"
        )
        print(
            "of the GNU General Public License <http://www.gnu.org/licenses/gpl.html>."
        )
        print("There is NO WARRANTY, to the extent permitted by law.")
        return
    if args.listen is not None:
        # Force debugging on
        logging.basicConfig(level=logging.DEBUG)
        device = await aiosenseme.discover(args.listen, 5)
        if device is None:
            print(f"Name/Room/IP address '{args.listen}' not found")
            return
        while True:
            await asyncio.sleep(4)
    if args.discover is True:
        try:
            discovery = SensemeDiscovery(True, 1)
            discovery.add_callback(discovered)
            discovery.start()
            await asyncio.sleep(4)
        finally:
            discovery.stop()
        return
    if args.models is True:
        msg = "Known SenseME models: "
        first = True
        for model in SensemeFan.models():
            if first:
                first = False
                msg += model
            else:
                msg += ", " + model
        print(msg)
        return
    if args.name is None:
        print("You must specify a SenseME device name using -n or --name")
        return
    device = await aiosenseme.discover(args.name, 2)
    if device is None:
        print(f"Name/Room/IP address '{args.name}' not found")
        return
    print_device(device)
    print_state("State", device)
    changed = False
    try:
        if device.is_fan:
            if args.whoosh is not None:
                print(f"whoosh={args.whoosh}")
                if device.fan_whoosh != (args.whoosh == "on"):
                    changed = True
                device.fan_whoosh = args.whoosh == "on"
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
                args.colortemp = int(round(args.colortemp / 100.0)) * 100
                if device.colortemp != args.colortemp:
                    changed = True
                device.colortemp = args.colortemp
        if changed:
            await asyncio.sleep(0.5)
            print_state("New State", device)
    finally:
        device.stop()


def cli():
    """Command line interface for SensemeDiscovery."""
    task = asyncio.Task(process_args())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(task)
