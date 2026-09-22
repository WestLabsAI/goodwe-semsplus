"""Tests for the GoodWe SEMS+ API client using requests-mock."""

import sys

import pytest
import requests_mock

sys.path.insert(0, ".")

from custom_components.goodwe_semsplus.api import (
    SemsPlusApiError,
    SemsPlusAuthError,
    SemsPlusClient,
)
from custom_components.goodwe_semsplus.const import (
    CONTROL_URL,
    DEVICE_INFORMATION_URL,
    DEVICE_STATUS_URL,
    LOGIN_URL,
    MAX_REAUTHENTICATION_ATTEMPTS,
    PORTAL_STATIONS_URL,
    PRODUCTION_ITEMS,
    PRODUCTION_ITEMS_EXTRA,
    SEMS_HOST,
    STATION_FLOW_URL,
    STATION_INFO_URL,
    STATION_PRODUCTION_URL,
    STATIONS_URL,
    USER_URL,
)

MOCK_EMAIL = "test@example.com"
MOCK_PASSWORD = "test_password"
MOCK_STATION_ID = "station-123"
MOCK_PLANT_ID = "plant-123"
MOCK_SN = "DEVICE-001"
MOCK_DEVICE_NAME = "SolarGoodwe"


@pytest.fixture
def mock_requests():
    """Fixture to mock HTTP requests."""
    with requests_mock.Mocker() as m:
        yield m


class TestSemsPlusClient:
    """Test suite for SemsPlusClient with mocked requests."""

    def setup_method(self):
        """Setup common test data."""
        self.email = MOCK_EMAIL
        self.password = MOCK_PASSWORD
        self.station_id = MOCK_STATION_ID
        self.plant_id = MOCK_PLANT_ID
        self.sn = MOCK_SN
        self.device_name = MOCK_DEVICE_NAME

    def _mock_login_response(self):
        """Return a mocked login response."""
        return {
            "code": "00000",
            "msg": "success",
            "data": {
                "uid": "user-123",
                "token": "mock-token-xyz",
                "timestamp": 1234567890,
                "client": "semsPlusWeb",
            },
        }

    def _mock_user_response(self):
        """Return a mocked user info response."""
        return {
            "code": "00000",
            "msg": "success",
            "data": {
                "uid": "user-123",
                "email": MOCK_EMAIL,
                "countryCode": "NL",
            },
        }

    def _mock_stations_response(self):
        """Return a mocked stations list response."""
        return {
            "code": "00000",
            "msg": "success",
            "data": {
                "dataList": [
                    {
                        "id": self.station_id,
                        "stationId": self.station_id,
                        "stationName": "Test Station",
                        "countryCode": "NL",
                    }
                ]
            },
        }

    def _mock_empty_stations_response(self):
        """Return a mocked station list without stations, as installer accounts receive it."""
        return {"code": "00000", "msg": "success", "data": {"dataList": []}}

    def _mock_portal_page(self, station_ids, total):
        """Return a mocked page of the portal station list."""
        return {
            "code": "00000",
            "data": {
                "dataList": [{"id": station_id, "name": station_id} for station_id in station_ids],
                "size": 50,
                "current": 1,
                "total": total,
            },
        }

    def _mock_station_info_response(self):
        """Return a mocked station info response."""
        return {
            "code": "00000",
            "msg": "success",
            "data": {
                "id": self.station_id,
                "stationId": self.station_id,
                "stationName": "Test Station",
                "pac": 3500,
                "eDay": 12.5,
                "eMonth": 250.0,
                "eTotal": 5000.0,
            },
        }

    def _mock_station_flow_response(self):
        """Return a mocked station flow response."""
        return {
            "code": "00000",
            "msg": "success",
            "data": {
                "pAc": 3500,
                "status": "online",
                "refreshTime": 1234567890,
            },
        }

    def _mock_device_status_response(self):
        """Return a mocked device status response."""
        return {
            "code": "00000",
            "msg": "success",
            "data": {
                "deviceDetailList": [
                    {
                        "statusDetailList": [
                            {
                                "sn": self.sn,
                                "deviceName": self.device_name,
                                "status": 1,
                                "pac": 3500,
                            }
                        ]
                    }
                ]
            },
        }

    def _mock_control_response(self):
        """Return a mocked control response."""
        return {
            "code": "00000",
            "msg": "success",
            "data": {"status": "success"},
        }

    def test_login_and_get_user(self, mock_requests):
        """Test login and get user."""
        # Mock homepage GET for session cookies
        mock_requests.get(SEMS_HOST, text="")
        # Mock login endpoint
        mock_requests.post(
            LOGIN_URL,
            json=self._mock_login_response(),
        )
        # Mock get user endpoint
        mock_requests.get(
            USER_URL,
            json=self._mock_user_response(),
        )

        client = SemsPlusClient(self.email, self.password)
        user = client.get_user()

        assert user["uid"] == "user-123"
        assert user["email"] == MOCK_EMAIL

    def test_get_stations(self, mock_requests):
        """Test getting stations list."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.post(STATIONS_URL, json=self._mock_stations_response())

        client = SemsPlusClient(self.email, self.password)
        stations = client.get_stations()

        assert len(stations) == 1
        assert stations[0]["stationId"] == self.station_id

    def test_get_stations_falls_back_to_portal_for_installer_accounts(self, mock_requests):
        """Installer accounts have no personal stations, so the portal list is used."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        personal = mock_requests.post(STATIONS_URL, json=self._mock_empty_stations_response())
        portal = mock_requests.post(
            PORTAL_STATIONS_URL, json=self._mock_portal_page(["station-a", "station-b"], 2)
        )

        client = SemsPlusClient(self.email, self.password)
        stations = client.get_stations()

        assert [station["id"] for station in stations] == ["station-a", "station-b"]
        assert portal.last_request.json() == {"current": 1, "size": 50}

        # The fallback is remembered, later calls skip the personal station query.
        client.get_stations()
        assert personal.call_count == 1
        assert portal.call_count == 2

    def test_get_stations_pages_through_portal_list(self, mock_requests):
        """Every page of the portal station list is collected."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.post(STATIONS_URL, json=self._mock_empty_stations_response())
        portal = mock_requests.post(
            PORTAL_STATIONS_URL,
            [
                {"json": self._mock_portal_page(["station-a", "station-b"], 3)},
                {"json": self._mock_portal_page(["station-c"], 3)},
            ],
        )

        client = SemsPlusClient(self.email, self.password)
        stations = client.get_stations()

        assert [station["id"] for station in stations] == ["station-a", "station-b", "station-c"]
        assert [request.json()["current"] for request in portal.request_history] == [1, 2]

    def test_get_stations_without_any_stations(self, mock_requests):
        """An account without stations gets an empty list and no remembered fallback."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        personal = mock_requests.post(STATIONS_URL, json=self._mock_empty_stations_response())
        mock_requests.post(PORTAL_STATIONS_URL, json=self._mock_portal_page([], 0))

        client = SemsPlusClient(self.email, self.password)

        assert client.get_stations() == []
        client.get_stations()
        assert personal.call_count == 2

    def test_get_station_info(self, mock_requests):
        """Test getting station info."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.post(
            f"{STATION_INFO_URL}?stationId={self.station_id}",
            json=self._mock_station_info_response(),
        )

        client = SemsPlusClient(self.email, self.password)
        info = client.get_station_info(self.station_id)

        assert info["stationId"] == self.station_id
        assert info["pac"] == 3500

    def test_get_station_flow(self, mock_requests):
        """Test getting station flow."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.get(
            f"{STATION_FLOW_URL}?stationId={self.station_id}",
            json=self._mock_station_flow_response(),
        )

        client = SemsPlusClient(self.email, self.password)
        flow = client.get_station_flow(self.station_id)

        assert flow["pAc"] == 3500
        assert flow["status"] == "online"

    def test_get_device_status(self, mock_requests):
        """Test getting device status."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.get(
            f"{DEVICE_STATUS_URL}?stationId={self.station_id}",
            json=self._mock_device_status_response(),
        )

        client = SemsPlusClient(self.email, self.password)
        status = client.get_device_status(self.station_id)

        # _request returns data.get("data", data), so we get the inner data directly
        assert status["deviceDetailList"][0]["statusDetailList"][0]["sn"] == self.sn

    def test_get_station_production(self, mock_requests):
        """Energy and revenue totals are requested for the given period."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.post(
            STATION_PRODUCTION_URL,
            json={
                "code": "00000",
                "data": {
                    "proSystemTotalStats": 45.6,
                    "proGridStats": 38.57,
                    "proPurchaseStats": 0.07,
                    "proConsumStats": 2.9,
                    "profitProStats": 3.2832,
                    "currency": "EUR",
                },
            },
        )

        client = SemsPlusClient(self.email, self.password)
        production = client.get_station_production(
            self.station_id, "day", "2026-09-22 00:00:00", "2026-09-22 23:59:59"
        )

        assert production["proSystemTotalStats"] == 45.6
        assert production["currency"] == "EUR"
        request = mock_requests.request_history[-1].json()
        assert request["stationId"] == self.station_id
        assert request["dimension"] == "day"
        assert request["startTime"] == "2026-09-22 00:00:00"

    def test_get_station_production_drops_unsupported_metrics(self, mock_requests):
        """Charge and discharge are dropped once the gateway rejects them."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.post(
            STATION_PRODUCTION_URL,
            [
                {"json": {"code": "C0001", "msg": "unknown item"}},
                {"json": {"code": "00000", "data": {"proSystemTotalStats": 45.6}}},
                {"json": {"code": "00000", "data": {"proSystemTotalStats": 812.4}}},
            ],
        )

        client = SemsPlusClient(self.email, self.password)
        first = client.get_station_production(
            self.station_id, "day", "2026-09-22 00:00:00", "2026-09-22 23:59:59"
        )
        second = client.get_station_production(
            self.station_id, "month", "2026-09-01 00:00:00", "2026-09-22 23:59:59"
        )

        assert first["proSystemTotalStats"] == 45.6
        assert second["proSystemTotalStats"] == 812.4
        assert mock_requests.request_history[-3].json()["items"] == (
            PRODUCTION_ITEMS + PRODUCTION_ITEMS_EXTRA
        )
        # The retry and every later call ask only for the supported metrics.
        assert mock_requests.request_history[-2].json()["items"] == PRODUCTION_ITEMS
        assert mock_requests.request_history[-1].json()["items"] == PRODUCTION_ITEMS

    def test_get_device_information(self, mock_requests):
        """Device information is returned keyed by metric code."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.get(
            DEVICE_INFORMATION_URL.format(sn=self.sn),
            json={
                "code": "00000",
                "data": [
                    {"code": "modelType", "data": "GW25K-ET"},
                    {"code": "ratedPower", "data": "25.0"},
                    {"data": "no code, skipped"},
                ],
            },
        )

        client = SemsPlusClient(self.email, self.password)
        information = client.get_device_information(self.sn)

        assert information == {"modelType": "GW25K-ET", "ratedPower": "25.0"}

    def test_token_lifetime_shortens_after_an_early_rejection(self, mock_requests):
        """A token rejected early shortens the assumed lifetime for the next login."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.get(
            USER_URL,
            [
                {"json": {"code": "C0602", "msg": "token expired"}},
                {"json": self._mock_user_response()},
            ],
        )

        client = SemsPlusClient(self.email, self.password)
        before = client._token_lifetime
        client.get_user()

        assert client._token_lifetime < before
        assert client._token_expiry > 0

    def test_stop_inverter(self, mock_requests):
        """Test stopping inverter."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.post(CONTROL_URL, json=self._mock_control_response())

        client = SemsPlusClient(self.email, self.password)
        result = client.stop_inverter(self.sn, self.plant_id, self.device_name)

        assert result["code"] == "00000"

    def test_start_inverter(self, mock_requests):
        """Test starting inverter."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.post(CONTROL_URL, json=self._mock_control_response())

        client = SemsPlusClient(self.email, self.password)
        result = client.start_inverter(self.sn, self.plant_id, self.device_name)

        assert result["code"] == "00000"

    def test_restart_inverter(self, mock_requests):
        """Test restarting inverter."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        mock_requests.post(CONTROL_URL, json=self._mock_control_response())

        client = SemsPlusClient(self.email, self.password)
        result = client.restart_inverter(self.sn, self.plant_id, self.device_name)

        assert result["code"] == "00000"

    def test_login_failure(self, mock_requests):
        """Test login failure."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(
            LOGIN_URL,
            json={"code": "C0601", "msg": "Login failed"},
        )

        client = SemsPlusClient(self.email, self.password)

        with pytest.raises(SemsPlusAuthError, match="Login failed"):
            client.get_user()

    def test_max_reauthentication_attempts_exceeded(self, mock_requests):
        """Test that exceeding max reauthentication attempts raises error."""
        mock_requests.get(SEMS_HOST, text="")
        mock_requests.post(LOGIN_URL, json=self._mock_login_response())
        # Mock USER_URL to return C0602 (token expired)
        mock_requests.get(USER_URL, json={"code": "C0602", "msg": "Token expired"})

        client = SemsPlusClient(self.email, self.password)
        # Establish initial session by making one call
        with pytest.raises(SemsPlusApiError):
            client.get_user()  # First call gets C0602, increments counter

        # Now set counter to max to test the limit check on next request
        client._reauthentication_attempts = MAX_REAUTHENTICATION_ATTEMPTS

        # This should raise SemsPlusApiError about max attempts exceeded
        with pytest.raises(SemsPlusApiError, match="Max reauthentication attempts"):
            client.get_user()
