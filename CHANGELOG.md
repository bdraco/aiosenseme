# Changelog for aiosenseme library

## v0.3.0

* Lots of linting changes.
* API breaking changes.
  * aiosenseme.Discover() is now aiosenseme.discover()
  * aiosenseme.Discover_Any() is now aiosenseme.discover_any()
* Aiosenseme.discover() will now match Fan Name, Room Name and IP address

## v0.2.1

* Requiring Python 3.7 was too restrictive. Back to allowing and testing Python 3.6.

## v0.2.0

* API breaking changes.
  * SensemeFan.group_status() is now SensemeFan.room_status()
  * SensemeFan.group_name() is now SensemeFan.room_name()
  * SensemeFan.group_room_type() is now SensemeFan.room_type()
* Now requiring python 3.7 or above. Not testing on anything lower.
* Add Discover() function to aiosenseme.
* Improved error handling in SensemeDiscovery and some testing on MacOS.
* Handle fan models differently and hopefully better in SensemeFan.
* Added SensemeFan.models() class method which returns an list of known models.
* API Added command line script capability.
* Added Type Hints.

## v0.1.1

* Add L-Series Haiku fan to known model list.

## v0.1.0

* Initial release.
