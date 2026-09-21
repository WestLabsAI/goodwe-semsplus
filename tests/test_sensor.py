"""Tests for GoodWe SEMS+ sensor platform."""

import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, ".")

from custom_components.goodwe_semsplus.const import DOMAIN
from custom_components.goodwe_semsplus.sensor import (
    STATION_SENSORS,
    SemsPlusDeviceStatusSensor,
    SemsPlusStationSensor,
    async_setup_entry,
)


@pytest.mark.asyncio
async def test_sensor_async_setup_entry_creates_entities():
    """Test sensor setup creates station and device entities."""
    coordinator = MagicMock()
    coordinator.data = {
        "stations": {
            "station-1": {
                "name": "Main Station",
                "flow": {"pAc": 1.0},
                "info": {"pac": 1000, "eDay": 5.5, "eMonth": 120, "eTotal": 2500},
                "devices": [
                    {"sn": "INV-001", "deviceName": "Inverter 1", "status": 1},
                    {"sn": "INV-002", "deviceName": "Inverter 2", "status": 3},
                ],
            }
        }
    }

    hass = MagicMock()
    hass.data = {DOMAIN: {"entry-1": coordinator}}

    entry = MagicMock()
    entry.entry_id = "entry-1"

    add_entities = MagicMock()

    await async_setup_entry(hass, entry, add_entities)

    add_entities.assert_called_once()
    entities = add_entities.call_args[0][0]
    # One entity per station sensor definition + 2 device status sensors
    assert len(entities) == len(STATION_SENSORS) + 2


def test_station_sensor_native_value_from_flow_power_kw_to_watt():
    """Test station power sensor uses flow.pAc and converts kW to W."""
    coordinator = MagicMock()
    coordinator.data = {
        "stations": {
            "station-1": {
                "flow": {"pAc": "1.2345"},
                "info": {},
            }
        }
    }

    sensor = SemsPlusStationSensor(
        coordinator=coordinator,
        station_id="station-1",
        station_name="Main Station",
        sensor_def=STATION_SENSORS[0],
    )

    assert sensor.native_value == 1234.5


def test_station_sensor_native_value_non_numeric_returns_none():
    """Test station non-numeric values are treated as unavailable."""
    coordinator = MagicMock()
    coordinator.data = {
        "stations": {
            "station-1": {
                "info": {
                    "pac": "n/a",
                }
            }
        }
    }

    sensor = SemsPlusStationSensor(
        coordinator=coordinator,
        station_id="station-1",
        station_name="Main Station",
        sensor_def=STATION_SENSORS[0],
    )

    assert sensor.native_value is None


def _station_sensor(station_data, key):
    """Build a station sensor for the given key over one station's data."""
    coordinator = MagicMock()
    coordinator.data = {"stations": {"station-1": station_data}}
    sensor_def = next(d for d in STATION_SENSORS if d["key"] == key)
    return SemsPlusStationSensor(
        coordinator=coordinator,
        station_id="station-1",
        station_name="Main Station",
        sensor_def=sensor_def,
    )


def test_flow_sensors_report_signed_powers_in_watt():
    """Flow powers are converted to W and keep their sign (battery charging, grid import)."""
    flow = {
        "pAc": 0.33561,
        "pSystem": 2.286,
        "pConsum": 0.33861,
        "pGrid": -0.003,
        "pBat": -1.95039,
        "soc": 48,
    }
    station = {"flow": flow, "info": {}}

    assert _station_sensor(station, "pv_power").native_value == pytest.approx(2286)
    assert _station_sensor(station, "load_power").native_value == pytest.approx(338.61)
    assert _station_sensor(station, "grid_power").native_value == pytest.approx(-3)
    assert _station_sensor(station, "battery_power").native_value == pytest.approx(-1950.39)
    assert _station_sensor(station, "battery_soc").native_value == 48


def test_flow_sensors_unknown_while_station_is_idle():
    """An idle station reports only pAc; the other flow sensors are unknown, not zero."""
    station = {"flow": {"pAc": 0, "flows": {}}, "info": {}}

    assert _station_sensor(station, "pac").native_value == 0
    for key in ("pv_power", "load_power", "grid_power", "battery_power", "battery_soc"):
        assert _station_sensor(station, key).native_value is None


def test_energy_today_falls_back_to_station_list():
    """Energy Today uses productionToday from the station list when info lacks eDay."""
    fallback = {"info": {}, "summary": {"productionToday": 4.3}}
    assert _station_sensor(fallback, "eDay").native_value == 4.3

    preferred = {"info": {"eDay": 5.5}, "summary": {"productionToday": 4.3}}
    assert _station_sensor(preferred, "eDay").native_value == 5.5


def test_device_status_sensor_maps_status_and_unknown():
    """Test device status sensor maps known status and handles unknown device."""
    coordinator = MagicMock()
    coordinator.data = {
        "stations": {
            "station-1": {
                "devices": [
                    {"sn": "INV-001", "status": 3},
                ]
            }
        }
    }

    sensor_known = SemsPlusDeviceStatusSensor(
        coordinator=coordinator,
        station_id="station-1",
        device_sn="INV-001",
        device_name="Inverter 1",
    )
    assert sensor_known.native_value == "stopped"

    sensor_unknown = SemsPlusDeviceStatusSensor(
        coordinator=coordinator,
        station_id="station-1",
        device_sn="INV-404",
        device_name="Missing Inverter",
    )
    assert sensor_unknown.native_value == "unknown"
