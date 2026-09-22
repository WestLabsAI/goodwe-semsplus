"""Constants for the GoodWe SEMS+ integration."""

DOMAIN = "goodwe_semsplus"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_COMMAND_DELAY = "command_delay_seconds"
CONF_SCAN_INTERVAL = "scan_interval_seconds"

DEFAULT_COMMAND_DELAY = 30  # 30 seconds

SEMS_HOST = "https://semsplus.goodwe.com"
GATEWAY_HOST = "https://eu-gateway.semsportal.com"
LOGIN_URL = f"{SEMS_HOST}/web/sems/sems-user/api/v1/auth/cross-login"

API_BASE = f"{GATEWAY_HOST}/web/sems"
USER_URL = f"{API_BASE}/sems-user/api/v1/user/get-user"
STATIONS_URL = f"{API_BASE}/sems-plant/api/stations/simple-query"
# Installer accounts see no personal stations; the portal lists the stations they manage here.
PORTAL_STATIONS_URL = f"{API_BASE}/sems-plant/api/portal/stations/page"
STATION_INFO_URL = f"{API_BASE}/sems-plant/api/portal/stations/basic/info"
STATION_FLOW_URL = f"{API_BASE}/sems-plant/api/stations/flow"
# Energy and revenue totals over a period; the station list carries only today's production.
STATION_PRODUCTION_URL = f"{API_BASE}/sems-plant/api/stations/production"
DEVICE_STATUS_URL = f"{API_BASE}/sems-plant/api/stations/device/all-status"
# Static per-device information such as model type and rated power.
DEVICE_INFORMATION_URL = f"{API_BASE}/sems-plant/api/equipments/{{sn}}/information"
CONTROL_URL = f"{API_BASE}/sems-remote/api/v1/address/remote/setDeviceFunctionParameters"

SCAN_INTERVAL_SECONDS = 30
MIN_SCAN_INTERVAL_SECONDS = 30
MAX_SCAN_INTERVAL_SECONDS = 3600
MAX_REAUTHENTICATION_ATTEMPTS = 3  # Maximum times to re-authenticate per request

# The gateway does not state how long a token is valid. Start at five hours and shorten
# the assumed lifetime whenever the gateway rejects a token earlier than that.
TOKEN_LIFETIME_SECONDS = 5 * 3600
MIN_TOKEN_LIFETIME_SECONDS = 600
PORTAL_STATIONS_PAGE_SIZE = 50
PORTAL_STATIONS_MAX_PAGES = 20  # Upper bound on paging, i.e. up to 1000 stations

# Concurrent API requests. The gateway is a shared cloud service, so this stays modest.
MAX_PARALLEL_REQUESTS = 4

# Data that does not change every cycle is fetched on its own, slower schedule.
STATION_INFO_INTERVAL_SECONDS = 3600
PRODUCTION_INTERVAL_SECONDS = 300
PRODUCTION_TOTAL_INTERVAL_SECONDS = 3600
DEVICE_INFORMATION_INTERVAL_SECONDS = 86400

# Metrics requested from the production endpoint. The portal asks for the same list;
# charge and discharge are appended because the station chart config offers them, and
# are dropped again if the gateway rejects them.
PRODUCTION_ITEMS = [
    "proSystemTotalStats",
    "proGridStats",
    "proPurchaseStats",
    "proConsumStats",
    "profitProStats",
    "profitGridStats",
]
PRODUCTION_ITEMS_EXTRA = ["proCharStats", "proDischarStats"]

DEVICE_STATUS_MAP = {
    3: "stopped",
    5: "online",
}
