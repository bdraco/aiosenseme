# aiosenseme library

[![PyPI version](https://badge.fury.io/py/aiosenseme.svg)](https://badge.fury.io/py/aiosenseme) [![Downloads](https://pepy.tech/badge/aiosenseme)](https://pepy.tech/project/aiosenseme)

This asynchronous Python library provides periodic discovery, control and push-based status for SenseME fans and lights by Big Ass Fans. It was developed mainly to provide access to SenseME devices for [Home Assistant](https://www.home-assistant.io/) using asyncio but should work fine in other applications.

This library (based on [TomFaulkner's](https://github.com/TomFaulkner/SenseMe) library) keeps an open socket to each controlled fan so that state changes from any source including local control are pushed more or less immediately. This approach is far more robust and responsive. A discovery task was also added to periodically detect SenseME devices on the network.

Sniffing the packets and documenting the protocol was the work of [Bruce](http://bruce.pennypacker.org/tag/senseme-plugin/). His work in making an [Indigo plugin](https://github.com/bpennypacker/SenseME-Indigo-Plugin) made this library possible.

Thanks to [PenitentTangent2401](https://github.com/PenitentTangent2401) for help in debugging the standalone Haiku Light.

## Model Notes

* Confirmed support of Haiku, Haiku H, and Haiku L fans.
* Confirmed support of discontinued standalone Haiku Light.
* Supports [Wireless Wall Control](https://www.bigassfans.com/support/haiku-wireless-wall-control/) indirectly through fan status reporting.
* Probably supports Haiku C fans.
* The [i6 fan](https://www.bigassfans.com/fans/i6/) is NOT currently supported.

## Command line access

The aiosenseme package now installs a command line script along with the package. To discover all devices on the network type the following. Here discovery found two standard Haiku Fans and a Haiku Light. The fans are in ```Studio Fans``` room and the Haiku Light is not part of a room.

```console
$ aiosenseme --discover
Studio Beam Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.6.0
  IP Addr: 192.168.1.2, MAC Addr: FF:FF:FF:FF:FF:FF
  UUID: 73264cb2-1234-1234-1234-012345678912
Studio Vault Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.6.0
  IP Addr: 192.168.1.3, MAC Addr: FF:FF:FF:FF:FF:FF
  UUID: 73264cb2-1234-1234-1234-012345678913
Hallway Light
  Model: Haiku Light, FW Version: 2.6.0
  IP Addr: 192.168.1.3, MAC Addr: FF:FF:FF:FF:FF:FF
  UUID: 73264cb2-1234-1234-1234-012345678913
```

To get information and state of the device type the following. This uses discovery to match the specified device name or room name.

```console
$ aiosenseme -n "Studio Vault Fan"
Studio Vault Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.6.0
  IP Addr: 192.168.1.3, MAC Addr: FF:FF:FF:FF:FF:FF
  UUID: 73264cb2-1234-1234-1234-012345678912
State: Fan is off, Light is off
```

Here both the fan speed is set and the light is turned on. Notice also that Whoosh was turned off when the fan speed was set specific value.

```console
$ aiosenseme --name "Studio Vault Fan" --speed 3 --light on
Studio Beam Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.6.0
  IP Addr: 192.168.1.2, MAC Addr: FF:FF:FF:FF:FF:FF
  UUID: 73264cb2-1234-1234-1234-012345678912
State: Fan is on (speed: 2), Light is off, Whoosh: on
New State: Fan is on (speed: 3), Light is on (brightness: 16)
```

You can also select the fan by IP address. This connects directly to the fan without using discovery.

```console
$ aiosenseme -i 192.168.1.3 --speed 4
Studio Vault Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.6.0
  IP Addr: 192.168.1.3, MAC Addr: FF:FF:FF:FF:FF:FF
  UUID: 73264cb2-1234-1234-1234-012345678912
State: Fan is off, Light is off
New State: Fan is on (speed: 4), Light is off
```

To change the color temperature of a Haiku Light type the following. Changing a Haiku Light color temp will not turn the light on if it is already off.

```console
$ aiosenseme --name "Hallway Light" --light on --colortemp 5000
Hallway Light
  Model: Haiku Light, FW Version: 2.6.0
  IP Addr: 192.168.1.3, MAC Addr: FF:FF:FF:FF:FF:FF
  UUID: 73264cb2-1234-1234-1234-012345678913
State: Light is off
State: Light is on (brightness: 9, color temp: 5000)
```

To get a fan's information and state formatted as json.

```console
$ aiosenseme -i 192.168.1.3 -j
{
    "address": "192.168.1.3",
    "base_model": "FAN,HAIKU,SENSEME",
    "device_beeper": true,
    "device_indicators": true,
    "fan_autocomfort": "OFF",
    "fan_cooltemp": 22.77,
    "fan_dir": "FWD",
    "fan_on": false,
    "fan_smartmode": "OFF",
    "fan_speed": 0,
    "fan_speed_limits_room": [
        1,
        7
    ],
    "fan_speed_max": 7,
    "fan_speed_min": 1,
    "fan_whoosh_mode": false,
    "fw_version": "2.6.0",
    "has_light": true,
    "has_sensor": true,
    "is_fan": true,
    "is_light": false,
    "light_brightness": 0,
    "light_brightness_limits_room": [
        1,
        16
    ],
    "light_brightness_max": 16,
    "light_brightness_min": 1,
    "light_on": false,
    "mac": "FF:FF:FF:FF:FF:FF",
    "model": "Haiku Fan",
    "motion_detected": false,
    "motion_fan_auto": false,
    "motion_light_auto": false,
    "name": "Studio Vault Fan",
    "network_gateway": "255.255.255.0",
    "network_ip": "192.168.1.3",
    "network_ssid": "Network IoT",
    "network_subnetmask": "192.168.1.1",
    "room_name": "Studio",
    "room_type": "Family Room",
    "sleep_mode": false,
    "uuid": "73264cb2-1234-1234-1234-012345678913"
}
```

## Issues

* There is a lot of error handling and reconnection logic to help with the fact that these devices sometimes stop working on the network. I have managed to decrease the likelihood of this happening by keeping an open connection to the device at all times instead of using multiple socket connections but it still happens.
* Discovery sometimes just does not work and it can happen for an extended period. Connecting via IP address instead of discovery may still work.
* Early testing indicates the i6 fan from Big Ass Fans is not compatible with this library. The Big Ass Fans [website](https://www.bigassfans.com/fans/i6/) says the i6 fan has SenseME technology but it uses a different app which requires Bluetooth for initial setup. There is some [evidence](https://github.com/mikelawrence/senseme-hacs/issues/5) that WiFi is still used to control the fan from the app once setup.
* The occupancy sensor is treated differently than other fan settings/states; occupancy state changes are not pushed immediately and must be detected with periodic status updates. So unfortunately this sensor will not seem very responsive.
* UDP port 31415 must be available and not blocked by a firewall.
* This library will not handle multiple instances of discovery running on the same machine.
