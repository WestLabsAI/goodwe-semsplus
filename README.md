# GoodWe SEMS+ Home Assistant Integration

Custom Home Assistant integration for GoodWe SEMS+ using pure requests (no Selenium/browser required).

## Install via HACS (Community Store)

This integration is installed through HACS as a custom repository.

### Prerequisites

- Home Assistant is running
- HACS is installed and configured

### Steps

1. In Home Assistant, open HACS.
2. Click the three-dot menu in the top-right and select `Custom repositories`.
3. Add this repository URL:
   - `https://github.com/timvanderHorst/goodwe-semsplus`
4. Set category to `Integration`.
5. Click `Add`.
6. Search in HACS for `GoodWe SEMS+`.
7. Open the integration and click `Download`.
8. Restart Home Assistant.
9. Go to `Settings` -> `Devices & Services` -> `Add Integration`.
10. Search for `GoodWe SEMS+` and add it.
11. Enter your SEMS+ account email and password.

### Version requirement for HACS

- HACS expects a valid version in `custom_components/goodwe_semsplus/manifest.json`.
- Create a GitHub release tag that matches the manifest version (for example `v0.2.0` for version `0.2.0`).
- If HACS shows "The version can not be used with HACS", verify the manifest version format and that a matching release tag exists.

## Manual installation (alternative)

1. Copy `custom_components/goodwe_semsplus` into your Home Assistant `config/custom_components` folder.
2. Restart Home Assistant.
3. Add the integration from `Settings` -> `Devices & Services`.

## Sensors

Each station gets these sensors:

| Sensor | Unit | Notes |
|---|---|---|
| Current Power | W | AC output of the inverter. For hybrid systems this differs from PV power while the battery charges or discharges. |
| PV Power | W | Solar generation. |
| Load Power | W | Household consumption. |
| Grid Power | W | Positive while exporting to the grid, negative while importing. |
| Battery Power | W | Positive while the battery discharges, negative while it charges. |
| Battery State of Charge | % | |
| Energy Today | kWh | |
| Energy This Month | kWh | |
| Total Energy | kWh | Since the station was commissioned. |
| Grid Export Today | kWh | |
| Grid Import Today | kWh | |
| Self Consumption Today | kWh | |
| Battery Charge Today | kWh | |
| Battery Discharge Today | kWh | |
| Full Load Hours Today | h | |
| Specific Yield | kWh/kWp | |
| Irradiation Today | kWh/m² | |
| Revenue Today | account currency | |
| Total Revenue | account currency | |

Every device of a station also gets a **Status** sensor, and inverters get Stop, Start
and Restart buttons. Those buttons switch an inverter off, on or through a restart, so
they are created disabled; enable the ones you want in the entity registry.

A station that is not producing, for example at night or before commissioning, reports
only its AC output; the other power sensors are unknown until the station produces again.

## Options

`Settings` -> `Devices & Services` -> `GoodWe SEMS+` -> `Configure`:

- **Update interval**: how often the power flow and device status of every station are
  read. That is two requests per station per update, so raise this when the account
  manages many stations. Energy totals refresh every 5 minutes, lifetime totals and
  station details hourly, regardless of this setting.
- **Delay after a control command**: how long the control buttons stay unavailable
  after a press.

## Notes

- Accounts with the installer role, which manage stations through an organisation, are supported: when the account owns no stations, the integration uses the station list of the SEMS+ portal.
- Credentials are stored through the Home Assistant config entry flow. When the gateway
  rejects them, Home Assistant asks for the password again instead of only logging an error.
- The integration uses cloud polling.
- If login fails, verify your SEMS+ credentials and that the account can log in at `https://semsplus.goodwe.com`.

## Support

- Issues: `https://github.com/timvanderHorst/goodwe-semsplus/issues`
