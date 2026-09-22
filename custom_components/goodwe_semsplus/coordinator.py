"""Data update coordinator for GoodWe SEMS+."""

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import SemsPlusApiError, SemsPlusAuthError, SemsPlusClient
from .const import (
    DEVICE_INFORMATION_INTERVAL_SECONDS,
    DOMAIN,
    MAX_PARALLEL_REQUESTS,
    PRODUCTION_INTERVAL_SECONDS,
    PRODUCTION_TOTAL_INTERVAL_SECONDS,
    SCAN_INTERVAL_SECONDS,
    STATION_INFO_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def _extract_devices(device_data: dict) -> list[dict]:
    """Extract per-device records from SEMS+ grouped device status payload."""
    devices: list[dict] = []

    for detail in device_data.get("deviceDetailList", []):
        for status_group in detail.get("statusDetailList", []):
            detail_map = status_group.get("detailMap", {})
            if not isinstance(detail_map, dict):
                continue
            status_value = status_group.get("status")
            for value in detail_map.values():
                if not isinstance(value, dict):
                    continue
                if status_value is not None and "status" not in value:
                    value = {**value, "status": status_value}
                devices.append(value)

    return devices


def _production_periods(station: dict) -> dict[str, tuple[str, str, str]]:
    """Build the (dimension, start, end) periods for today, this month and lifetime.

    The endpoint aggregates over the given range, so the lifetime total is the
    range from the station's creation date until now.
    """
    now = dt_util.now()
    end = now.replace(hour=23, minute=59, second=59, microsecond=0).strftime(TIME_FORMAT)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = day_start.replace(day=1)

    created = station.get("createTime") or ""
    try:
        total_start = datetime.strptime(str(created)[:19], TIME_FORMAT)
    except ValueError:
        total_start = day_start - timedelta(days=365 * 20)

    return {
        "day": ("day", day_start.strftime(TIME_FORMAT), end),
        "month": ("month", month_start.strftime(TIME_FORMAT), end),
        "total": ("year", total_start.strftime(TIME_FORMAT), end),
    }


class SemsPlusCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch data from SEMS+ API."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SemsPlusClient,
        scan_interval: int = SCAN_INTERVAL_SECONDS,
    ) -> None:
        _LOGGER.debug(
            "Initializing SemsPlusCoordinator with scan interval: %d seconds", scan_interval
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.client = client
        self._semaphore = asyncio.Semaphore(MAX_PARALLEL_REQUESTS)
        # Slow-moving data is kept between cycles and refreshed on its own schedule.
        self._cache: dict[str, dict] = {}
        self._fetched_at: dict[tuple[str, str], float] = {}
        _LOGGER.debug("SemsPlusCoordinator initialized")

    async def _call(self, func, *args):
        """Run a blocking API call in the executor, bounded by the semaphore."""
        async with self._semaphore:
            return await self.hass.async_add_executor_job(func, *args)

    def _is_due(self, station_id: str, kind: str, interval: int) -> bool:
        """Return True when this kind of data has not been fetched recently."""
        last = self._fetched_at.get((station_id, kind))
        return last is None or (self.hass.loop.time() - last) >= interval

    def _mark_fetched(self, station_id: str, kind: str) -> None:
        self._fetched_at[(station_id, kind)] = self.hass.loop.time()

    async def _async_update_data(self) -> dict:
        """Fetch data from SEMS+ API."""
        _LOGGER.debug("Starting data update from SEMS+ API")
        try:
            stations = await self._call(self.client.get_stations)
        except SemsPlusAuthError as err:
            raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err
        except SemsPlusApiError as err:
            _LOGGER.error("API error while listing stations: %s", err, exc_info=True)
            raise UpdateFailed(f"API error: {err}") from err

        _LOGGER.debug("Received %d stations", len(stations))

        wanted = [s for s in stations if s.get("id")]
        results = await asyncio.gather(
            *(self._update_station(station) for station in wanted),
            return_exceptions=True,
        )

        data: dict = {"stations": {}}
        failures: list[BaseException] = []
        for station, result in zip(wanted, results):
            if isinstance(result, SemsPlusAuthError):
                raise ConfigEntryAuthFailed(f"Authentication failed: {result}")
            if isinstance(result, BaseException):
                failures.append(result)
                cached = self._cache.get(station["id"])
                if cached:
                    # One station failing should not blank out the rest.
                    _LOGGER.warning(
                        "Update for station %s failed, keeping the previous data: %s",
                        station.get("name", station["id"]),
                        result,
                    )
                    data["stations"][station["id"]] = cached
                continue
            data["stations"][station["id"]] = result

        if failures and not data["stations"]:
            raise UpdateFailed(f"API error: {failures[0]}")

        _LOGGER.info(
            "Data update complete: %d stations with %d total devices",
            len(data["stations"]),
            sum(len(s["devices"]) for s in data["stations"].values()),
        )
        return data

    async def _update_station(self, station: dict) -> dict:
        """Fetch one station's data, reusing cached slow-moving parts."""
        station_id = station["id"]
        cached = self._cache.get(station_id, {})

        station_flow = await self._call(self.client.get_station_flow, station_id)
        device_data = await self._call(self.client.get_device_status, station_id)
        devices = _extract_devices(device_data if isinstance(device_data, dict) else {})

        station_info = cached.get("info") or {}
        if self._is_due(station_id, "info", STATION_INFO_INTERVAL_SECONDS):
            station_info = await self._call(self.client.get_station_info, station_id)
            self._mark_fetched(station_id, "info")

        production = dict(cached.get("production") or {})
        await self._update_production(station, production)

        device_information = dict(cached.get("device_information") or {})
        if self._is_due(station_id, "device_information", DEVICE_INFORMATION_INTERVAL_SECONDS):
            for device in devices:
                sn = device.get("sn")
                if not sn:
                    continue
                try:
                    device_information[sn] = await self._call(
                        self.client.get_device_information, sn
                    )
                except SemsPlusApiError as err:
                    _LOGGER.debug("No device information for %s: %s", sn, err)
            self._mark_fetched(station_id, "device_information")

        result = {
            "info": station_info,
            "flow": station_flow,
            "devices": devices,
            "name": station.get("name", station_id),
            # The station list entry carries figures such as productionToday
            # that the basic info endpoint does not return.
            "summary": station,
            # Energy and revenue totals per period, keyed day/month/total.
            "production": production,
            # Static per-device data such as model type, keyed by serial number.
            "device_information": device_information,
        }
        self._cache[station_id] = result
        return result

    async def _update_production(self, station: dict, production: dict) -> None:
        """Refresh the energy totals that are due, in place."""
        station_id = station["id"]
        periods = _production_periods(station)
        due = {
            key: interval
            for key, interval in (
                ("day", PRODUCTION_INTERVAL_SECONDS),
                ("month", PRODUCTION_INTERVAL_SECONDS),
                ("total", PRODUCTION_TOTAL_INTERVAL_SECONDS),
            )
            if self._is_due(station_id, f"production_{key}", interval)
        }

        for key in due:
            dimension, start, end = periods[key]
            try:
                production[key] = await self._call(
                    self.client.get_station_production, station_id, dimension, start, end
                )
            except SemsPlusApiError as err:
                # Energy totals are optional; the rest of the station still updates.
                _LOGGER.debug("No %s production for station %s: %s", key, station_id, err)
                continue
            self._mark_fetched(station_id, f"production_{key}")
