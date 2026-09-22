"""Device registry helpers shared by the platforms."""

from .const import DOMAIN


def station_device_info(station_id: str, station_name: str) -> dict:
    """Device info for the station itself."""
    return {
        "identifiers": {(DOMAIN, station_id)},
        "name": station_name,
        "manufacturer": "GoodWe",
        "model": "PV plant",
    }


def device_device_info(device_sn: str, device_name: str, information: dict | None) -> dict:
    """Device info for one device of a station.

    The parent station is linked by the device registry in ``__init__``, so no
    deprecated ``via_device`` is passed here.
    """
    info = {
        "identifiers": {(DOMAIN, device_sn)},
        "name": device_name,
        "manufacturer": "GoodWe",
        "serial_number": device_sn,
    }
    model = (information or {}).get("modelType")
    if model:
        info["model"] = model
    return info
