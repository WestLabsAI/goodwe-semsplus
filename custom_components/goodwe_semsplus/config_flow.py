"""Config flow for GoodWe SEMS+ integration."""

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD

from .api import SemsPlusAuthError, SemsPlusClient
from .const import (
    CONF_COMMAND_DELAY,
    CONF_SCAN_INTERVAL,
    DEFAULT_COMMAND_DELAY,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
    SCAN_INTERVAL_SECONDS,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class GoodWeSemsPlusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GoodWe SEMS+."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return GoodWeSemsPlusOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        _LOGGER.debug("Config flow user step started")
        errors = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            _LOGGER.info("Validating credentials for: %s", email)
            password = user_input[CONF_PASSWORD]

            # Validate credentials
            client = SemsPlusClient(email, password)
            try:
                _LOGGER.info("Attempting to authenticate with credentials")
                await self.hass.async_add_executor_job(client.get_user)
                _LOGGER.info("Credentials validated successfully")
            except SemsPlusAuthError as err:
                _LOGGER.warning("Authentication failed during config: %s", err)
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception("Unexpected error during config: %s", err)
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(email)
                self._abort_if_unique_id_configured()
                _LOGGER.info("Config entry created for: %s", email)
                return self.async_create_entry(
                    title=f"SEMS+ ({email})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict) -> ConfigFlowResult:
        """Start reauthentication after the gateway rejected the credentials."""
        _LOGGER.info("Reauthentication started for: %s", entry_data.get(CONF_EMAIL))
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Ask for the password again and update the existing entry."""
        entry = self._get_reauth_entry()
        errors = {}

        if user_input is not None:
            email = entry.data[CONF_EMAIL]
            client = SemsPlusClient(email, user_input[CONF_PASSWORD])
            try:
                await self.hass.async_add_executor_job(client.get_user)
            except SemsPlusAuthError as err:
                _LOGGER.warning("Reauthentication failed: %s", err)
                errors["base"] = "invalid_auth"
            except Exception as err:
                _LOGGER.exception("Unexpected error during reauthentication: %s", err)
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"email": entry.data.get(CONF_EMAIL, "")},
            errors=errors,
        )


class GoodWeSemsPlusOptionsFlow(OptionsFlow):
    """Handle options for GoodWe SEMS+."""

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle options step."""
        _LOGGER.debug("Options flow init step started")
        if user_input is not None:
            _LOGGER.debug("Saving options: %s", user_input)
            return self.async_create_entry(title="", data=user_input)

        current_delay = self.config_entry.options.get(CONF_COMMAND_DELAY, DEFAULT_COMMAND_DELAY)
        current_interval = self.config_entry.options.get(CONF_SCAN_INTERVAL, SCAN_INTERVAL_SECONDS)
        _LOGGER.debug(
            "Current settings: command delay %d s, scan interval %d s",
            current_delay,
            current_interval,
        )

        options_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=current_interval,
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_SCAN_INTERVAL_SECONDS, max=MAX_SCAN_INTERVAL_SECONDS),
                ),
                vol.Optional(
                    CONF_COMMAND_DELAY,
                    default=current_delay,
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=3600)),
            }
        )

        return self.async_show_form(step_id="init", data_schema=options_schema)

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        """Handle options step with user input."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return await self.async_step_init()
