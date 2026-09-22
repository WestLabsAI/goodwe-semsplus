"""Tests for GoodWe SEMS+ coordinator."""

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

sys.path.insert(0, ".")

from custom_components.goodwe_semsplus.api import SemsPlusApiError, SemsPlusAuthError
from custom_components.goodwe_semsplus.coordinator import SemsPlusCoordinator


def _client() -> MagicMock:
    """Build an API client mock answering every endpoint the coordinator uses."""
    client = MagicMock()
    client.get_stations = MagicMock(
        return_value=[
            {"id": "station-1", "name": "Main Station"},
            {"name": "Missing ID"},
        ]
    )
    client.get_station_info = MagicMock(return_value={"id": "plant-1", "pac": 500})
    client.get_station_flow = MagicMock(return_value={"pAc": 0.5, "status": "1"})
    client.get_station_production = MagicMock(return_value={"proSystemTotalStats": 45.6})
    client.get_device_information = MagicMock(return_value={"modelType": "GW25K-ET"})
    client.get_device_status = MagicMock(
        return_value={
            "deviceDetailList": [
                {
                    "deviceType": "INVERTER",
                    "statusDetailList": [
                        {
                            "status": 1,
                            "snList": ["INV-001"],
                            "detailMap": {
                                "INV-001": {
                                    "sn": "INV-001",
                                    "name": "Inverter 1",
                                    "deviceType": "INVERTER",
                                }
                            },
                        },
                        {
                            "status": 3,
                            "snList": ["INV-002"],
                            "detailMap": {
                                "INV-002": {
                                    "sn": "INV-002",
                                    "name": "Inverter 2",
                                    "deviceType": "INVERTER",
                                }
                            },
                        },
                    ],
                }
            ]
        }
    )
    return client


@pytest.mark.asyncio
async def test_coordinator_update_data_success_nested_devices(hass):
    """Test coordinator update builds normalized station/device structure."""
    client = _client()

    async def run_executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=run_executor_job)

    coordinator = SemsPlusCoordinator(hass, client)
    data = await coordinator._async_update_data()

    assert "station-1" in data["stations"]
    assert "" not in data["stations"]
    assert data["stations"]["station-1"]["name"] == "Main Station"
    assert data["stations"]["station-1"]["flow"]["pAc"] == 0.5
    assert data["stations"]["station-1"]["summary"] == {"id": "station-1", "name": "Main Station"}
    assert len(data["stations"]["station-1"]["devices"]) == 2
    assert data["stations"]["station-1"]["devices"][0]["sn"] == "INV-001"
    assert data["stations"]["station-1"]["production"]["day"] == {"proSystemTotalStats": 45.6}
    assert data["stations"]["station-1"]["device_information"]["INV-001"] == {
        "modelType": "GW25K-ET"
    }


@pytest.mark.asyncio
async def test_coordinator_refetches_only_the_fast_data(hass):
    """Only the power flow and device status are read on every cycle."""
    client = _client()

    async def run_executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=run_executor_job)

    coordinator = SemsPlusCoordinator(hass, client)
    await coordinator._async_update_data()
    data = await coordinator._async_update_data()

    assert client.get_station_flow.call_count == 2
    assert client.get_device_status.call_count == 2
    # Station info, energy totals and device information are on slower schedules.
    assert client.get_station_info.call_count == 1
    assert client.get_device_information.call_count == 2  # once per device, first cycle only
    assert client.get_station_production.call_count == 3  # day, month and total, once
    # The cached values are still served on the cycle that did not re-read them.
    assert data["stations"]["station-1"]["production"]["month"] == {"proSystemTotalStats": 45.6}


@pytest.mark.asyncio
async def test_coordinator_keeps_previous_data_when_one_station_fails(hass):
    """A single failing station does not blank out the others."""
    client = _client()

    async def run_executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=run_executor_job)

    coordinator = SemsPlusCoordinator(hass, client)
    await coordinator._async_update_data()

    client.get_station_flow = MagicMock(side_effect=SemsPlusApiError("station offline"))
    data = await coordinator._async_update_data()

    assert data["stations"]["station-1"]["flow"] == {"pAc": 0.5, "status": "1"}


@pytest.mark.asyncio
async def test_coordinator_update_data_auth_error_starts_reauth(hass):
    """Rejected credentials ask the user for the password instead of just failing."""
    client = MagicMock()
    client.get_stations = MagicMock(side_effect=SemsPlusAuthError("bad credentials"))
    client.get_station_flow = MagicMock()

    async def run_executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=run_executor_job)

    coordinator = SemsPlusCoordinator(hass, client)

    with pytest.raises(ConfigEntryAuthFailed, match="Authentication failed"):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_coordinator_update_data_api_error_raises_updatefailed(hass):
    """Test API errors are wrapped as UpdateFailed."""
    client = MagicMock()
    client.get_stations = MagicMock(side_effect=SemsPlusApiError("api unavailable"))
    client.get_station_flow = MagicMock()

    async def run_executor_job(func, *args):
        return func(*args)

    hass.async_add_executor_job = AsyncMock(side_effect=run_executor_job)

    coordinator = SemsPlusCoordinator(hass, client)

    with pytest.raises(UpdateFailed, match="API error"):
        await coordinator._async_update_data()
