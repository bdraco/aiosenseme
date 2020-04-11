"""Script interface for aiosenseme library."""

import argparse
import asyncio
import logging
from typing import List

import aiosenseme
from aiosenseme import SensemeDiscovery, SensemeFan
from aiosenseme import __version__

ARGS = argparse.ArgumentParser(
    description="Discover and control Haiku/SenseME fans by Big Ass Fans."
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
    "-d",
    "--discover",
    action="store_true",
    dest="discover",
    default=False,
    help="discover all fans on the network",
)
ARGS.add_argument(
    "-m",
    "--models",
    action="store_true",
    dest="models",
    default=False,
    help="list known fan models",
)
ARGS.add_argument(
    "-n",
    "--name",
    action="store",
    dest="name",
    default=None,
    help="fan name, room name or IP address",
)
ARGS.add_argument(
    "-p",
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
    "-w",
    "--whoosh",
    action="store",
    dest="whoosh",
    default=None,
    choices=["on", "off"],
    help="whoosh mode",
)

# array of discovered devices
_DEVICES = []


def print_fan(fan: SensemeFan):
    """Print information about fan."""
    msg = f"{fan.name}\n"
    if fan.room_status:
        msg += f"  Room Name: {fan.room_name}, Room Type: {fan.room_type}\n"
    if fan.has_light:
        msg += f"  Model: {fan.model} with light, "
    else:
        msg += f"  Model: {fan.model} without light, "
    msg += f"FW Version: {fan.fw_version}\n"
    msg += f"  IP Addr: {fan.ip}, MAC Addr: {fan.mac}\n"
    msg += f"  Token: {fan.network_token}"
    print(msg)


def print_fan_state(prefix: str, fan: SensemeFan):
    """Print information about fan current state."""
    msg = prefix
    if fan.fan_on:
        msg += f": Fan is on (speed: {fan.fan_speed})"
    else:
        msg += ": Fan is off"
    if fan.light_on:
        msg += f", Light is on (brightness: {fan.light_brightness})"
    else:
        msg += ", Light is off"
    if fan.fan_whoosh:
        msg += ", Whoosh: on"
    else:
        msg += ", Whoosh: off"
    print(msg)


async def discovered(fans: List[SensemeFan]):
    """Discovered fan callback function.

    Called when discovery has detected a SenseME fan.
    Each time a device is discovered all devices discovered are reported.
    """
    global _DEVICES
    for fan in fans:
        if fan not in _DEVICES:
            _DEVICES.append(fan)
            print_fan(fan)


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
    elif args.discover is True:
        try:
            discovery = SensemeDiscovery(True, 1)
            discovery.add_callback(discovered)
            discovery.start()
            await asyncio.sleep(4)
        finally:
            discovery.stop()
    elif args.models is True:
        msg = "Known fan models: "
        first = True
        for model in SensemeFan.models():
            if first:
                first = False
                msg += model
            else:
                msg += ", " + model
        print(msg)
        return
    else:
        if args.name is None:
            print("You must specify a fan name using -n or --name")
            return
        fan = await aiosenseme.discover(args.name, 2)
        if fan is None:
            print(f"Fan/Room/IP address '{args.name}' not found")
            return
        print_fan(fan)
        print_fan_state("State", fan)
        try:
            changed = False
            if args.whoosh is not None:
                print(f"whoosh={args.whoosh}")
                if fan.fan_whoosh != (args.whoosh == "on"):
                    changed = True
                fan.fan_whoosh = args.whoosh == "on"
            if args.speed is not None:
                if args.fan is not None:
                    print(
                        "When specifying --fanspeed there is no " "reason to set --fan"
                    )
                if fan.fan_speed != args.speed:
                    changed = True
                fan.fan_speed = args.speed
            elif args.fan is not None:
                if fan.fan_on != (args.fan == "on"):
                    changed = True
                fan.fan_on = args.fan == "on"
            if args.brightness is not None:
                if args.light is not None:
                    print(
                        "When specifying --brightness there is no "
                        "reason to set --light"
                    )
                if fan.light_brightness != args.brightness:
                    changed = True
                fan.light_brightness = args.brightness
            elif args.light is not None:
                if fan.light_on != (args.light == "on"):
                    changed = True
                fan.light_on = args.light == "on"
            if changed:
                await asyncio.sleep(0.5)
                print_fan_state("New State", fan)

        finally:
            fan.stop()


def cli():
    """Command line interface for SensemeDiscovery."""
    task = asyncio.Task(process_args())
    loop = asyncio.get_event_loop()
    loop.run_until_complete(task)
