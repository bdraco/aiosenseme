# aiosenseme library

[![PyPI version](https://badge.fury.io/py/aiosenseme.svg)](https://badge.fury.io/py/aiosenseme) [![Downloads](https://pepy.tech/badge/aiosenseme)](https://pepy.tech/project/aiosenseme)

This asynchronous Python library provides periodic discovery, control and push-based status for SenseME fans by Big Ass Fans. It was developed mainly to provide access to SenseME fans for [Home Assistant](https://www.home-assistant.io/) using asyncio but should work fine in other applications.

This library (based on [TomFaulkner's](https://github.com/TomFaulkner/SenseMe) library) keeps an open socket to each controlled fan so that state changes from any source including local control are pushed more or less immediately. This approach is far more robust and responsive. A discovery task was also added to periodically detect SenseME devices on the network.

Sniffing the packets and documenting the protocol was the work of [Bruce](http://bruce.pennypacker.org/tag/senseme-plugin/). His work in making an [Indigo plugin](https://github.com/bpennypacker/SenseME-Indigo-Plugin) made this library possible.

## Command line access

The aiosenseme package now installs a command line script along with the package. To discover all fans on the network type the following.

```console
$ aiosenseme --discover
Studio Beam Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.5.0
  IP Addr: 192.168.1.2, MAC Addr: FF:FF:FF:FF:FF:FF
  Token: 73264cb2-1234-1234-1234-012345678912
Studio Vault Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.5.0
  IP Addr: 192.168.1.3, MAC Addr: FF:FF:FF:FF:FF:FF
  Token: 73264cb2-1234-1234-1234-012345678913
```

Here both the fan speed is set and the light is turned on. The room name (Studio Fans) was used to set the fan so all fans in that room changed to the same state. Keep in mind that changing an individual fan that is a member of a room will do the same thing. Notice also that Whoosh was turned off when the fan speed was set specific value.

```console
$ aiosenseme --name "Studio Fans" --speed 3 --light on
Studio Beam Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.5.0
  IP Addr: 192.168.1.2, MAC Addr: FF:FF:FF:FF:FF:FF
  Token: 73264cb2-1234-1234-1234-012345678912
State: Fan is on (speed: 2), Light is off, Whoosh: on
New State: Fan is on (speed: 3), Light is on (brightness: 16), Whoosh: off
```

You can also select the fan by IP address.

```console
$ aiosenseme -n 192.168.1.3 --speed 4
Studio Vault Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.5.0
  IP Addr: 192.168.1.3, MAC Addr: FF:FF:FF:FF:FF:FF
  Token: 73264cb2-1234-1234-1234-012345678912
State: Fan is off, Light is off, Whoosh: on
New State: Fan is on (speed: 4), Light is off, Whoosh: off
```

To just read the fan state type the following.

```console
$ aiosenseme -n "Studio Vault Fan"
Studio Vault Fan
  Room Name: Studio Fans, Room Type: Family Room
  Model: Haiku Fan with light, FW Version: 2.5.0
  IP Addr: 192.168.1.3, MAC Addr: FF:FF:FF:FF:FF:FF
  Token: 73264cb2-1234-1234-1234-012345678912
State: Fan is off, Light is off, Whoosh: off
```

## Issues

* UDP port 31415 must be available and not blocked by a firewall.
* This library will not handle multiple instances of discovery running on the same machine.
