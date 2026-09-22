"""Sensor platform for GoodWe SEMS+."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_STATUS_MAP, DOMAIN
from .coordinator import SemsPlusCoordinator
from .device import device_device_info, station_device_info

_LOGGER = logging.getLogger(__name__)

UNIT_SPECIFIC_YIELD = "kWh/kWp"
UNIT_IRRADIATION = "kWh/m²"


# Each sensor reads `field` from one part of the station data:
#   "flow"       real-time power flow
#   "summary"    the station's entry in the station list
#   "info"       the station basic info
#   "production" energy and revenue totals, `period` selects day/month/total
# Flow powers are reported in kW and scaled to W. `fallback` names a
# (source, field) pair to use when the primary field is missing.
#
# Sign conventions of the flow powers, verified against the SEMS+ portal:
#   pGrid: positive = export to the grid, negative = import from the grid
#   pBat:  positive = battery discharging, negative = battery charging
STATION_SENSORS = [
    {
        "key": "pac",
        "source": "flow",
        "field": "pAc",
        "scale": 1000,
        "name": "Current Power",
        "unit": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "eDay",
        "source": "production",
        "period": "day",
        "field": "proSystemTotalStats",
        "fallback": ("summary", "productionToday"),
        "name": "Energy Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "eMonth",
        "source": "production",
        "period": "month",
        "field": "proSystemTotalStats",
        "name": "Energy This Month",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "eTotal",
        "source": "production",
        "period": "total",
        "field": "proSystemTotalStats",
        "name": "Total Energy",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "grid_export_today",
        "source": "production",
        "period": "day",
        "field": "proGridStats",
        "name": "Grid Export Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "grid_import_today",
        "source": "production",
        "period": "day",
        "field": "proPurchaseStats",
        "name": "Grid Import Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "self_consumption_today",
        "source": "production",
        "period": "day",
        "field": "proConsumStats",
        "name": "Self Consumption Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "pv_power",
        "source": "flow",
        "field": "pSystem",
        "scale": 1000,
        "name": "PV Power",
        "unit": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "load_power",
        "source": "flow",
        "field": "pConsum",
        "scale": 1000,
        "name": "Load Power",
        "unit": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "grid_power",
        "source": "flow",
        "field": "pGrid",
        "scale": 1000,
        "name": "Grid Power",
        "unit": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "battery_power",
        "source": "flow",
        "field": "pBat",
        "scale": 1000,
        "name": "Battery Power",
        "unit": UnitOfPower.WATT,
        "device_class": SensorDeviceClass.POWER,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "battery_soc",
        "source": "flow",
        "field": "soc",
        "name": "Battery State of Charge",
        "unit": PERCENTAGE,
        "device_class": SensorDeviceClass.BATTERY,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    # The station list is fetched every cycle anyway, so these cost no extra request.
    {
        "key": "battery_charge_today",
        "source": "summary",
        "field": "proCharStatsToday",
        "name": "Battery Charge Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "battery_discharge_today",
        "source": "summary",
        "field": "proDischarStatsToday",
        "name": "Battery Discharge Today",
        "unit": UnitOfEnergy.KILO_WATT_HOUR,
        "device_class": SensorDeviceClass.ENERGY,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "full_load_hours_today",
        "source": "summary",
        "field": "fullHourToday",
        "name": "Full Load Hours Today",
        "unit": UnitOfTime.HOURS,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "specific_yield",
        "source": "summary",
        "field": "specificYield",
        "name": "Specific Yield",
        "unit": UNIT_SPECIFIC_YIELD,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "irradiation_today",
        "source": "summary",
        "field": "irradiationToday",
        "name": "Irradiation Today",
        "unit": UNIT_IRRADIATION,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
]

# Revenue sensors carry the account currency, which the production response states.
REVENUE_SENSORS = [
    {
        "key": "revenue_today",
        "period": "day",
        "field": "profitProStats",
        "name": "Revenue Today",
    },
    {
        "key": "revenue_total",
        "period": "total",
        "field": "profitProStats",
        "name": "Total Revenue",
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up SEMS+ sensors from a config entry."""
    coordinator: SemsPlusCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    for station_id, station_data in coordinator.data.get("stations", {}).items():
        station_name = station_data.get("name", station_id)

        # Station-level sensors
        for sensor_def in STATION_SENSORS:
            entities.append(
                SemsPlusStationSensor(
                    coordinator=coordinator,
                    station_id=station_id,
                    station_name=station_name,
                    sensor_def=sensor_def,
                )
            )

        for sensor_def in REVENUE_SENSORS:
            entities.append(
                SemsPlusRevenueSensor(
                    coordinator=coordinator,
                    station_id=station_id,
                    station_name=station_name,
                    sensor_def=sensor_def,
                )
            )

        # Device-level sensors (inverters)
        for device in station_data.get("devices", []):
            device_sn = device.get("sn", "")
            if not device_sn:
                continue
            device_name = device.get("name") or device_sn
            entities.append(
                SemsPlusDeviceStatusSensor(
                    coordinator=coordinator,
                    station_id=station_id,
                    device_sn=device_sn,
                    device_name=device_name,
                )
            )

    async_add_entities(entities)


class SemsPlusStationSensor(CoordinatorEntity, SensorEntity):
    """Sensor for station-level data."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SemsPlusCoordinator,
        station_id: str,
        station_name: str,
        sensor_def: dict,
    ) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._key = sensor_def["key"]
        self._source = sensor_def["source"]
        self._period = sensor_def.get("period")
        self._field = sensor_def["field"]
        self._scale = sensor_def.get("scale", 1)
        self._fallback = sensor_def.get("fallback")
        self._attr_name = sensor_def["name"]
        self._attr_unique_id = f"{station_id}_{self._key}"
        self._attr_native_unit_of_measurement = sensor_def["unit"]
        self._attr_device_class = sensor_def["device_class"]
        self._attr_state_class = sensor_def["state_class"]
        self._attr_device_info = station_device_info(station_id, station_name)

    @property
    def _station(self) -> dict:
        return self.coordinator.data.get("stations", {}).get(self._station_id, {})

    def _read(self, station: dict, source: str, field: str, period: str | None = None):
        """Read one field out of the station data."""
        part = station.get(source) or {}
        if period is not None:
            part = part.get(period) or {}
        return part.get(field) if isinstance(part, dict) else None

    @property
    def native_value(self):
        """Return the sensor value."""
        station = self._station

        # A station that is not producing omits most flow fields, so a missing field
        # means unknown rather than zero.
        value = self._read(station, self._source, self._field, self._period)
        if value is None and self._fallback:
            source, field = self._fallback
            value = self._read(station, source, field)
        if value is None:
            return None
        try:
            return float(value) * self._scale
        except (ValueError, TypeError):
            return None


class SemsPlusRevenueSensor(SemsPlusStationSensor):
    """Revenue sensor whose unit follows the account currency."""

    def __init__(
        self,
        coordinator: SemsPlusCoordinator,
        station_id: str,
        station_name: str,
        sensor_def: dict,
    ) -> None:
        super().__init__(
            coordinator,
            station_id,
            station_name,
            {
                **sensor_def,
                "source": "production",
                "unit": None,
                "device_class": SensorDeviceClass.MONETARY,
                "state_class": SensorStateClass.TOTAL,
            },
        )

    @property
    def native_unit_of_measurement(self):
        """Return the currency the gateway reported alongside the revenue."""
        production = self._station.get("production") or {}
        period = production.get(self._period) or {}
        return period.get("currency")


class SemsPlusDeviceStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor for individual device (inverter) status."""

    _attr_has_entity_name = True
    _attr_name = "Status"

    def __init__(
        self,
        coordinator: SemsPlusCoordinator,
        station_id: str,
        device_sn: str,
        device_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._station_id = station_id
        self._device_sn = device_sn
        self._attr_unique_id = f"{device_sn}_status"
        station = coordinator.data.get("stations", {}).get(station_id, {})
        information = (station.get("device_information") or {}).get(device_sn)
        self._attr_device_info = device_device_info(device_sn, device_name, information)

    @property
    def native_value(self):
        """Return device status."""
        station = self.coordinator.data.get("stations", {}).get(self._station_id, {})
        for device in station.get("devices", []):
            sn = device.get("sn", "")
            if sn == self._device_sn:
                status = device.get("status", "unknown")
                return DEVICE_STATUS_MAP.get(status, str(status))
        return "unknown"
