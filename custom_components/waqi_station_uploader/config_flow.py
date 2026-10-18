"""Config and options flow for the WAQI uploader."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import WaqiAuthError, WaqiConnectionError, WaqiError, async_validate_token
from .const import (
    CONF_HUMIDITY_ENTITY,
    CONF_INTERVAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_PM10_ENTITY,
    CONF_PM25_ENTITY,
    CONF_CO2_ENTITY,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TEMPERATURE_ENTITY,
    CONF_TOKEN,
    DEFAULT_INTERVAL,
    DEFAULT_STATION_ID,
    DEFAULT_STATION_NAME,
    DOMAIN,
    MAX_INTERVAL,
    MIN_INTERVAL,
    TOKEN_PAGE_URL,
)

ENTITY_KEYS = (
    CONF_PM25_ENTITY,
    CONF_PM10_ENTITY,
    CONF_CO2_ENTITY,
    CONF_TEMPERATURE_ENTITY,
    CONF_HUMIDITY_ENTITY,
)


def _sensor_selector(device_class: SensorDeviceClass) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="sensor", device_class=device_class)
    )


def _settings_schema() -> vol.Schema:
    """Fields shared by the initial setup and the options flow."""
    return vol.Schema(
        {
            vol.Required(CONF_TOKEN): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_STATION_NAME): str,
            vol.Optional(CONF_LATITUDE): vol.Coerce(float),
            vol.Optional(CONF_LONGITUDE): vol.Coerce(float),
            vol.Required(CONF_PM25_ENTITY): _sensor_selector(SensorDeviceClass.PM25),
            vol.Optional(CONF_PM10_ENTITY): _sensor_selector(SensorDeviceClass.PM10),
            vol.Optional(CONF_CO2_ENTITY): _sensor_selector(SensorDeviceClass.CO2),
            vol.Optional(CONF_TEMPERATURE_ENTITY): _sensor_selector(
                SensorDeviceClass.TEMPERATURE
            ),
            vol.Optional(CONF_HUMIDITY_ENTITY): _sensor_selector(
                SensorDeviceClass.HUMIDITY
            ),
            vol.Required(CONF_INTERVAL): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_INTERVAL,
                    max=MAX_INTERVAL,
                    step=30,
                    unit_of_measurement="s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )


async def _validate(hass: HomeAssistant, user_input: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if (CONF_LATITUDE in user_input) != (CONF_LONGITUDE in user_input):
        errors["base"] = "location_incomplete"
        return errors
    try:
        await async_validate_token(async_get_clientsession(hass), user_input[CONF_TOKEN])
    except WaqiAuthError:
        errors[CONF_TOKEN] = "invalid_auth"
    except WaqiConnectionError:
        errors["base"] = "cannot_connect"
    except WaqiError:
        errors["base"] = "unknown"
    return errors


def _normalise(user_input: dict[str, Any]) -> dict[str, Any]:
    options = {k: v for k, v in user_input.items() if v not in (None, "")}
    options[CONF_INTERVAL] = int(options[CONF_INTERVAL])
    return options


class WaqiUploaderConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Initial setup."""
        errors: dict[str, str] = {}
        if user_input is not None:
            station_id = user_input.pop(CONF_STATION_ID).strip()
            await self.async_set_unique_id(station_id)
            self._abort_if_unique_id_configured()
            errors = await _validate(self.hass, user_input)
            if not errors:
                options = _normalise(user_input)
                return self.async_create_entry(
                    title=options[CONF_STATION_NAME],
                    data={CONF_STATION_ID: station_id},
                    options=options,
                )
            user_input[CONF_STATION_ID] = station_id

        schema = vol.Schema(
            {vol.Required(CONF_STATION_ID): str}
        ).extend(_settings_schema().schema)
        suggested = user_input or {
            CONF_STATION_ID: DEFAULT_STATION_ID,
            CONF_STATION_NAME: DEFAULT_STATION_NAME,
            CONF_LATITUDE: self.hass.config.latitude,
            CONF_LONGITUDE: self.hass.config.longitude,
            CONF_INTERVAL: DEFAULT_INTERVAL,
        }
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, suggested),
            errors=errors,
            description_placeholders={"token_url": TOKEN_PAGE_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return WaqiUploaderOptionsFlow()


class WaqiUploaderOptionsFlow(OptionsFlow):
    """Change token, location, sensors or interval."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = await _validate(self.hass, user_input)
            if not errors:
                return self.async_create_entry(data=_normalise(user_input))

        suggested = user_input or dict(self.config_entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(_settings_schema(), suggested),
            errors=errors,
        )
