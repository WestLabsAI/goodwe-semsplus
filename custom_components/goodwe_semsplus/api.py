"""API client for GoodWe SEMS+ using pure requests."""

import base64
import hashlib
import json
import logging
import time

import requests

from .const import (
    CONTROL_URL,
    DEVICE_INFORMATION_URL,
    DEVICE_STATUS_URL,
    LOGIN_URL,
    MAX_REAUTHENTICATION_ATTEMPTS,
    MIN_TOKEN_LIFETIME_SECONDS,
    PORTAL_STATIONS_MAX_PAGES,
    PORTAL_STATIONS_PAGE_SIZE,
    PORTAL_STATIONS_URL,
    PRODUCTION_ITEMS,
    PRODUCTION_ITEMS_EXTRA,
    SEMS_HOST,
    STATION_FLOW_URL,
    STATION_INFO_URL,
    STATION_PRODUCTION_URL,
    STATIONS_URL,
    TOKEN_LIFETIME_SECONDS,
    USER_URL,
)

_LOGGER = logging.getLogger(__name__)

CHROME_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)


class SemsPlusAuthError(Exception):
    """Authentication failed."""


class SemsPlusApiError(Exception):
    """API request failed."""


def _make_pwd(plaintext: str) -> str:
    """pwd = base64( MD5-hex(password) )."""
    md5_hex = hashlib.md5(plaintext.encode()).hexdigest()
    return base64.b64encode(md5_hex.encode()).decode()


def _encode_signature(token_json: str) -> str:
    """X-Signature = base64( sha256(timestamp@uid@token).hex + '@' + timestamp )."""
    if not token_json:
        return ""
    try:
        data = json.loads(token_json)
    except (json.JSONDecodeError, TypeError):
        data = {}
    ts = str(int(time.time() * 1000))
    uid = data.get("uid", "")
    token = data.get("token", "")
    hash_input = f"{ts}@{uid}@{token}"
    sig_hash = hashlib.sha256(hash_input.encode()).hexdigest()
    return base64.b64encode(f"{sig_hash}@{ts}".encode()).decode()


_EMPTY_TOKEN = json.dumps(
    {
        "uid": "",
        "timestamp": 0,
        "token": "",
        "client": "semsPlusWeb",
        "version": "",
        "language": "en",
    },
    separators=(",", ":"),
)


def _station_list(data) -> list:
    """Extract the station list from a paged or plain station response."""
    if isinstance(data, dict):
        return data.get("dataList", data.get("list", [])) or []
    return data or []


def _gateway_headers(token_json: str) -> dict:
    """Build gateway-specific headers including token and signature."""
    return {
        "token": token_json,
        "X-Signature": _encode_signature(token_json),
        "Access-Control-Allow-Origin": "*",
        "neutral": "0",
        "currentLang": "en",
    }


class SemsPlusClient:
    """Client for communicating with the GoodWe SEMS+ API."""

    def __init__(self, email: str, password: str) -> None:
        self._email = email
        self._password = password
        self._session: requests.Session | None = None
        self._token_json: str = ""
        self._token_issued: float = 0
        self._token_expiry: float = 0
        self._token_lifetime: float = TOKEN_LIFETIME_SECONDS
        self._reauthentication_attempts: int = 0
        self._use_portal_stations: bool = False
        self._production_items: list[str] = PRODUCTION_ITEMS + PRODUCTION_ITEMS_EXTRA
        _LOGGER.debug("SemsPlusClient initialized for %s", email)

    def _authenticate(self) -> None:
        """Perform login using pure requests to obtain API token."""
        _LOGGER.debug("Starting SEMS+ authentication for account: %s", self._email)

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": CHROME_UA,
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
                "Origin": SEMS_HOST,
                "Referer": f"{SEMS_HOST}/",
            }
        )
        _LOGGER.debug("Session headers configured")

        # Visit homepage to get session cookies
        _LOGGER.debug("Fetching homepage to establish session cookies from %s", SEMS_HOST)
        session.get(SEMS_HOST, timeout=30)
        _LOGGER.debug("Homepage fetch complete, session cookies established")

        payload = {
            "account": self._email,
            "pwd": _make_pwd(self._password),
            "agreement": 1,
            "isChinese": False,
            "isLocal": False,
        }
        _LOGGER.debug("Login payload prepared (pwd hash generated)")

        try:
            _LOGGER.debug("Sending login request to %s", LOGIN_URL)
            r = session.post(
                LOGIN_URL,
                json=payload,
                headers=_gateway_headers(_EMPTY_TOKEN),
                timeout=15,
            )
            r.raise_for_status()
            resp = r.json()
            _LOGGER.debug(
                "Login response received: status_code=%d, response_keys=%s",
                r.status_code,
                list(resp.keys()),
            )
        except requests.RequestException as err:
            _LOGGER.error("Login request failed: %s", err, exc_info=True)
            raise SemsPlusAuthError(f"Login request failed: {err}") from err

        code = resp.get("code", resp.get("status", -1))
        _LOGGER.debug("Login response code: %s", code)
        if code not in (0, 200, "00000", "200"):
            msg = resp.get("msg", resp)
            _LOGGER.error("Login failed with code %s: %s", code, msg)
            raise SemsPlusAuthError(f"Login failed (code {code}): {msg}")

        data = resp.get("data", {})
        data["client"] = "semsPlusWeb"
        token_json = json.dumps(data, separators=(",", ":"))
        _LOGGER.debug("Token JSON constructed: length=%d", len(token_json))

        session.headers.update({"token": token_json})
        self._session = session
        self._token_json = token_json
        self._token_issued = time.time()
        self._token_expiry = self._token_issued + self._token_lifetime
        self._reauthentication_attempts = 0  # Reset counter on successful auth
        _LOGGER.info(
            "SEMS+ authentication successful, token assumed valid for %.0f minutes",
            self._token_lifetime / 60,
        )

    def _shorten_token_lifetime(self) -> None:
        """Learn the real token lifetime from a token the gateway rejected early.

        The login response carries no expiry, so the assumed lifetime is corrected
        downwards whenever a token turns out to be shorter-lived than assumed. This
        avoids a failed request before every refresh.
        """
        age = time.time() - self._token_issued
        if not self._token_issued or age >= self._token_lifetime:
            return
        lifetime = max(MIN_TOKEN_LIFETIME_SECONDS, age * 0.9)
        if lifetime < self._token_lifetime:
            _LOGGER.debug(
                "Token rejected after %.0f minutes, assuming a lifetime of %.0f minutes from now on",
                age / 60,
                lifetime / 60,
            )
            self._token_lifetime = lifetime

    def _ensure_session(self) -> requests.Session:
        """Ensure we have a valid session, re-authenticating if needed."""
        if self._session is None:
            _LOGGER.debug("No session exists, authenticating")
            self._authenticate()
        elif time.time() > self._token_expiry:
            _LOGGER.debug("Token expired (expiry: %s), re-authenticating", self._token_expiry)
            self._authenticate()
        else:
            remaining = self._token_expiry - time.time()
            _LOGGER.debug("Using existing session, token valid for %.0f seconds", remaining)
        return self._session

    def _request(self, method: str, url: str, **kwargs) -> dict:
        """Make an authenticated API request."""
        session = self._ensure_session()
        token_json = session.headers.get("token", "")
        headers = kwargs.pop("headers", {})
        headers.update(_gateway_headers(token_json))

        try:
            resp = session.request(method, url, headers=headers, timeout=15, **kwargs)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as err:
            raise SemsPlusApiError(f"Request to {url} failed: {err}") from err

        code = data.get("code", "")
        _LOGGER.debug("API response code: %s", code)
        if code == "C0602":
            # Token expired, re-auth and retry with limit
            self._shorten_token_lifetime()
            self._reauthentication_attempts += 1
            _LOGGER.warning(
                "Token expired (C0602), reauthentication attempt %d of %d",
                self._reauthentication_attempts,
                MAX_REAUTHENTICATION_ATTEMPTS,
            )
            if self._reauthentication_attempts > MAX_REAUTHENTICATION_ATTEMPTS:
                _LOGGER.error(
                    "Max reauthentication attempts (%d) exceeded for request %s %s",
                    MAX_REAUTHENTICATION_ATTEMPTS,
                    method,
                    url,
                )
                raise SemsPlusApiError(
                    f"Max reauthentication attempts ({MAX_REAUTHENTICATION_ATTEMPTS}) exceeded: {data}"
                )
            self._authenticate()
            token_json = self._session.headers.get("token", "")
            headers.update(_gateway_headers(token_json))
            _LOGGER.debug("Retrying request after token refresh: %s %s", method, url)
            resp = self._session.request(method, url, headers=headers, timeout=15, **kwargs)
            resp.raise_for_status()
            data = resp.json()
            code = data.get("code", "")
            _LOGGER.debug("Retry response code: %s", code)

        if code not in ("00000", 0, 200, "200"):
            _LOGGER.error("API error %s: %s", code, data)
            raise SemsPlusApiError(f"API error {code}: {data}")

        # Reset reauthentication counter on successful response
        if self._reauthentication_attempts > 0:
            _LOGGER.debug(
                "Resetting reauthentication attempts from %d to 0 after successful response",
                self._reauthentication_attempts,
            )
            self._reauthentication_attempts = 0

        _LOGGER.debug("API request successful, returning data")
        return data.get("data", data)

    def get_user(self) -> dict:
        """Get user info."""
        return self._request("GET", USER_URL)

    def get_stations(self) -> list:
        """Get list of stations.

        Owner accounts get their stations from ``stations/simple-query``. Installer
        accounts manage stations through an organisation, so that endpoint returns
        an empty list for them; the SEMS+ portal lists those stations via
        ``portal/stations/page`` instead, which is used as a fallback. Once the
        fallback has returned stations it is used directly on later calls.
        """
        if not self._use_portal_stations:
            data = self._request(
                "POST",
                STATIONS_URL,
                json={
                    "pageIndex": 1,
                    "pageSize": 50,
                },
            )
            stations = _station_list(data)
            if stations:
                return stations
            _LOGGER.debug("No personal stations found, trying the portal station list")

        stations = self._get_portal_stations()
        if stations and not self._use_portal_stations:
            _LOGGER.info("Using the portal station list (%d stations)", len(stations))
            self._use_portal_stations = True
        return stations

    def _get_portal_stations(self) -> list:
        """Page through the portal station list used by installer accounts."""
        stations: list = []
        for page in range(1, PORTAL_STATIONS_MAX_PAGES + 1):
            data = self._request(
                "POST",
                PORTAL_STATIONS_URL,
                json={"current": page, "size": PORTAL_STATIONS_PAGE_SIZE},
            )
            batch = _station_list(data)
            stations.extend(batch)
            try:
                total = int(data.get("total")) if isinstance(data, dict) else None
            except (TypeError, ValueError):
                total = None
            if not batch or total is None or len(stations) >= total:
                break
        return stations

    def get_station_info(self, station_id: str) -> dict:
        """Get station basic info (power, energy, etc.)."""
        return self._request(
            "POST",
            f"{STATION_INFO_URL}?stationId={station_id}",
            json={},
        )

    def get_station_flow(self, station_id: str) -> dict:
        """Get real-time power flow (pAc kW, status, refreshTime)."""
        return self._request(
            "GET",
            f"{STATION_FLOW_URL}?stationId={station_id}",
        )

    def get_device_status(self, station_id: str) -> dict:
        """Get all device statuses for a station."""
        return self._request(
            "GET",
            f"{DEVICE_STATUS_URL}?stationId={station_id}",
        )

    def get_station_production(
        self, station_id: str, dimension: str, start_time: str, end_time: str
    ) -> dict:
        """Get energy and revenue totals for a station over a period.

        ``dimension`` is one of ``day``, ``week``, ``month`` or ``year``; the period
        itself comes from ``start_time``/``end_time`` (``%Y-%m-%d %H:%M:%S``). The
        response holds one value per requested metric, in kWh and account currency.
        """
        payload = {
            "stationId": station_id,
            "items": self._production_items,
            "dimension": dimension,
            "isReport": False,
            "startTime": start_time,
            "endTime": end_time,
        }
        try:
            data = self._request("POST", STATION_PRODUCTION_URL, json=payload)
        except SemsPlusApiError:
            if self._production_items == PRODUCTION_ITEMS:
                raise
            # Battery charge/discharge are not offered by every station; fall back to
            # the metrics the portal itself always requests.
            _LOGGER.debug("Production query rejected, retrying without %s", PRODUCTION_ITEMS_EXTRA)
            self._production_items = PRODUCTION_ITEMS
            payload["items"] = self._production_items
            data = self._request("POST", STATION_PRODUCTION_URL, json=payload)
        return data if isinstance(data, dict) else {}

    def get_device_information(self, sn: str) -> dict:
        """Get static information for one device, keyed by metric code.

        The gateway answers with a list of ``{"code": ..., "data": ...}`` entries
        holding values such as ``modelType`` and ``ratedPower``.
        """
        data = self._request("GET", DEVICE_INFORMATION_URL.format(sn=sn))
        entries = data if isinstance(data, list) else []
        return {
            item["code"]: item.get("data")
            for item in entries
            if isinstance(item, dict) and item.get("code")
        }

    def stop_inverter(self, sn: str, plant_id: str, device_name: str) -> dict:
        """Send stop command to inverter."""
        return self._control_inverter(sn, plant_id, device_name, 2, "stop")

    def start_inverter(self, sn: str, plant_id: str, device_name: str) -> dict:
        """Send start command to inverter."""
        return self._control_inverter(sn, plant_id, device_name, 3, "start_up")

    def restart_inverter(self, sn: str, plant_id: str, device_name: str) -> dict:
        """Send restart command to inverter."""
        return self._control_inverter(sn, plant_id, device_name, 1, "restart")

    def _control_inverter(
        self,
        sn: str,
        plant_id: str,
        device_name: str,
        address_value: int,
        status_setting: str,
    ) -> dict:
        """Send a remote control command to the inverter."""
        session = self._ensure_session()
        token_json = session.headers.get("token", "")
        resp = session.post(
            CONTROL_URL,
            headers=_gateway_headers(token_json),
            json={
                "sn": sn,
                "addressMap": {"80017": address_value},
                "addrFuncMap": {"80017": "1990397626802589697"},
                "controlItemLogs": {"status_setting": status_setting},
                "waitingForDevice": True,
                "plantId": plant_id,
                "deviceName": device_name,
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()
