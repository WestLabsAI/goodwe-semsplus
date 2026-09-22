"""The GoodWe SEMS+ integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .api import SemsPlusClient
from .const import CONF_SCAN_INTERVAL, DOMAIN, SCAN_INTERVAL_SECONDS
from .coordinator import SemsPlusCoordinator
from .device import device_device_info, station_device_info

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.BUTTON]


def _register_devices(hass: HomeAssistant, entry: ConfigEntry, data: dict) -> None:
    """Register stations and their devices, linking each device to its station.

    Devices are registered here rather than through an entity's ``via_device`` so
    the parent is set with ``via_device_id``, which replaces the ``via_device``
    parameter deprecated in Home Assistant 2026.9.
    """
    registry = dr.async_get(hass)

    for station_id, station in data.get("stations", {}).items():
        station_entry = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **station_device_info(station_id, station.get("name", station_id)),
        )
        information = station.get("device_information") or {}
        for device in station.get("devices", []):
            device_sn = device.get("sn")
            if not device_sn:
                continue
            registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                via_device_id=station_entry.id,
                **device_device_info(
                    device_sn,
                    device.get("name") or device_sn,
                    information.get(device_sn),
                ),
            )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GoodWe SEMS+ from a config entry."""
    _LOGGER.info("Setting up GoodWe SEMS+ integration for entry: %s", entry.entry_id)
    _LOGGER.debug("Config entry data keys: %s", list(entry.data.keys()))

    client = SemsPlusClient(
        email=entry.data[CONF_EMAIL],
        password=entry.data[CONF_PASSWORD],
    )
    _LOGGER.info("SemsPlusClient created")

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL_SECONDS)
    coordinator = SemsPlusCoordinator(hass, client, scan_interval)
    _LOGGER.info("Performing initial coordinator refresh")
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.info("Initial coordinator refresh complete")

    _register_devices(hass, entry, coordinator.data)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator
    _LOGGER.info("Coordinator registered in hass.data")

    _LOGGER.info("Setting up platforms: %s", PLATFORMS)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("Platforms setup complete")

    # Set up listener for options updates
    entry.async_on_unload(entry.add_update_listener(async_update_listener))
    _LOGGER.debug("Options update listener registered")

    _LOGGER.info("GoodWe SEMS+ setup complete for entry: %s", entry.entry_id)
    return True


async def async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options updates."""
    _LOGGER.info("Options updated for entry: %s, reloading", entry.entry_id)
    _LOGGER.debug("Updated options: %s", entry.options)
    # Reload the entry when options change
    await hass.config_entries.async_reload(entry.entry_id)
    _LOGGER.debug("Entry reload initiated")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading GoodWe SEMS+ entry: %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("Entry removed from hass.data")
    _LOGGER.info("GoodWe SEMS+ unload complete for entry: %s", entry.entry_id)
    return unload_ok
