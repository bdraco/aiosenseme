# aiosenseme [![PyPI version](https://badge.fury.io/py/aiosenseme.svg)](https://badge.fury.io/py/aiosenseme)

This asynchronous Python library provides periodic discovery, control and push-based status for SenseME fans by Big Ass Fans. It was developed mainly to provide access to SenseME fans for [Home Assistant](https://www.home-assistant.io/) using asyncio but should work fine in other applications.

This library (based on [TomFaulkner's](https://github.com/TomFaulkner/SenseMe) library) keeps an open socket to each controlled fan so that state changes from any source including local control are pushed more or less immediately. This approach is far more robust and responsive. A discovery task was also added to periodically detect SenseME devices on the network.

Sniffing the packets and documenting the protocol was the work of [Bruce](http://bruce.pennypacker.org/tag/senseme-plugin/). His work in making an [Indigo plugin](https://github.com/bpennypacker/SenseME-Indigo-Plugin) made this library possible.

## Requirements

Python 3.6 is required to use this library.
SenseME devices communicate on UDP port 31415 using broadcast and unicast traffic.
