"""Tests for the waqi_station_uploader integration."""

from __future__ import annotations

from datetime import timedelta
import json

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util

from custom_components.waqi_station_uploader.const import (
    CONF_CO2_ENTITY,
    CONF_CO2_LIMIT,
    CONF_HUMIDITY_ENTITY,
    CONF_INTERVAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_PM10_ENTITY,
    CONF_PM25_ENTITY,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TEMPERATURE_ENTITY,
    CONF_TOKEN,
    DOMAIN,
    TOKEN_CHECK_URL,
    UPLOAD_URL,
)

TOKEN = "dummy-token-for-test-purpose-only"

OPTIONS = {
    CONF_TOKEN: TOKEN,
    CONF_STATION_NAME: "Home",
    CONF_LATITUDE: 3.1,
    CONF_LONGITUDE: 101.6,
    CONF_PM25_ENTITY: "sensor.station_pm25",
    CONF_PM10_ENTITY: "sensor.station_pm10",
    CONF_TEMPERATURE_ENTITY: "sensor.station_temperature",
    CONF_HUMIDITY_ENTITY: "sensor.station_humidity",
    CONF_INTERVAL: 60,
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


def _set_states(hass: HomeAssistant, pm25="12", pm10="20", temp="86", hum="60") -> None:
    hass.states.async_set("sensor.station_pm25", pm25, {"unit_of_measurement": "µg/m³"})
    hass.states.async_set("sensor.station_pm10", pm10, {"unit_of_measurement": "µg/m³"})
    hass.states.async_set("sensor.station_temperature", temp, {"unit_of_measurement": "°F"})
    hass.states.async_set("sensor.station_humidity", hum, {"unit_of_measurement": "%"})


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id="test-station",
        data={CONF_STATION_ID: "test-station"},
        options=OPTIONS,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_config_flow(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(TOKEN_CHECK_URL, json={"status": "ok", "data": {}})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: " my-station ", **OPTIONS}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_STATION_ID: "my-station"}
    assert result["options"][CONF_PM25_ENTITY] == "sensor.station_pm25"
    assert result["options"][CONF_CO2_LIMIT] == 600


async def test_config_flow_bad_token(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(TOKEN_CHECK_URL, json={"status": "error", "data": "Invalid key"})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "x", **OPTIONS}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_TOKEN: "invalid_auth"}


async def test_periodic_upload_averages(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(UPLOAD_URL, json={"status": "ok"})
    _set_states(hass)
    await _setup(hass)

    # Changes during the window are averaged
    hass.states.async_set("sensor.station_pm25", "18", {"unit_of_measurement": "µg/m³"})
    hass.states.async_set("sensor.station_pm25", "unavailable")
    hass.states.async_set("sensor.station_pm25", "24", {"unit_of_measurement": "µg/m³"})
    await hass.async_block_till_done()

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()

    assert aioclient_mock.call_count == 1
    body = aioclient_mock.mock_calls[0][2]
    assert body["token"] == TOKEN
    assert body["station"] == {
        "id": "test-station",
        "name": "Home",
        "location": {"latitude": 3.1, "longitude": 101.6},
    }
    readings = {r["specie"]: r for r in body["readings"]}
    assert readings["pm2.5"]["value"] == 18.0
    assert readings["pm2.5"]["min"] == 12.0
    assert readings["pm2.5"]["max"] == 24.0
    assert readings["pm2.5"]["averaging"] == 60
    assert readings["pm10"]["value"] == 20.0
    assert readings["temp"]["value"] == 30.0  # 86 °F -> 30 °C
    assert readings["temp"]["unit"] == "C"
    assert readings["humidity"]["value"] == 60.0
    json.dumps(body)  # serialisable

    status = hass.states.get("sensor.waqi_uploader_home_upload_status")
    assert status.state == "ok"
    assert "token" not in json.dumps(dict(status.attributes), default=str)
    assert hass.states.get("sensor.waqi_uploader_home_last_upload").state not in (
        "unknown",
        "unavailable",
    )

    # Next window starts from the latest value only
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=122))
    await hass.async_block_till_done()
    body = aioclient_mock.mock_calls[1][2]
    readings = {r["specie"]: r for r in body["readings"]}
    assert readings["pm2.5"]["value"] == 24.0
    assert "min" not in readings["pm2.5"]


async def test_upload_error_and_button(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(UPLOAD_URL, json={"status": "error", "data": "station not verified"})
    _set_states(hass)
    await _setup(hass)

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.waqi_uploader_home_upload_now"}, blocking=True
    )
    status = hass.states.get("sensor.waqi_uploader_home_upload_status")
    assert status.state == "error"
    assert status.attributes["last_error"] == "station not verified"


async def test_skip_when_no_data(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(UPLOAD_URL, json={"status": "ok"})
    await _setup(hass)  # no states exist
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.waqi_uploader_home_upload_now"}, blocking=True
    )
    assert aioclient_mock.call_count == 0
    assert hass.states.get("sensor.waqi_uploader_home_upload_status").state == "skipped"


async def test_unload(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(UPLOAD_URL, json={"status": "ok"})
    _set_states(hass)
    entry = await _setup(hass)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 0


async def test_options_flow_clears_optional_sensor(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(TOKEN_CHECK_URL, json={"status": "ok", "data": {}})
    aioclient_mock.post(UPLOAD_URL, json={"status": "ok"})
    _set_states(hass)
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    new = {k: v for k, v in OPTIONS.items() if k != CONF_PM10_ENTITY}
    new[CONF_INTERVAL] = 300
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert CONF_PM10_ENTITY not in entry.options
    uploader = entry.runtime_data
    assert uploader.interval == timedelta(seconds=300)
    assert "sensor.station_pm10" not in uploader._sources


async def _setup_with_co2(hass: HomeAssistant, co2: str, **extra) -> MockConfigEntry:
    hass.states.async_set("sensor.station_co2", co2, {"unit_of_measurement": "ppm"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        unique_id="test-station",
        data={CONF_STATION_ID: "test-station"},
        options={**OPTIONS, CONF_CO2_ENTITY: "sensor.station_co2", **extra},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _press_upload(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.waqi_uploader_home_upload_now"}, blocking=True
    )


async def test_co2_uploaded_below_limit(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(UPLOAD_URL, json={"status": "ok"})
    _set_states(hass)
    await _setup_with_co2(hass, "450")  # default limit applies
    await _press_upload(hass)
    assert aioclient_mock.call_count == 1
    readings = {r["specie"]: r for r in aioclient_mock.mock_calls[0][2]["readings"]}
    assert readings["co2"]["value"] == 450.0
    assert readings["co2"]["unit"] == "ppm"


async def test_co2_above_default_limit_inhibits(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(UPLOAD_URL, json={"status": "ok"})
    _set_states(hass)
    await _setup_with_co2(hass, "750")
    await _press_upload(hass)
    assert aioclient_mock.call_count == 0
    status = hass.states.get("sensor.waqi_uploader_home_upload_status")
    assert status.state == "inhibited"
    assert "600" in status.attributes["last_error"]
    assert status.attributes["co2_limit"] == 600


async def test_co2_single_spike_inhibits(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(UPLOAD_URL, json={"status": "ok"})
    _set_states(hass)
    await _setup_with_co2(hass, "420")
    # Average stays under 600, but one sample crosses it
    hass.states.async_set("sensor.station_co2", "650", {"unit_of_measurement": "ppm"})
    hass.states.async_set("sensor.station_co2", "430", {"unit_of_measurement": "ppm"})
    await hass.async_block_till_done()
    await _press_upload(hass)
    assert aioclient_mock.call_count == 0
    assert hass.states.get("sensor.waqi_uploader_home_upload_status").state == "inhibited"


async def test_co2_custom_limit_and_disabled(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.post(UPLOAD_URL, json={"status": "ok"})
    _set_states(hass)
    entry = await _setup_with_co2(hass, "750", **{CONF_CO2_LIMIT: 800})
    await _press_upload(hass)
    assert aioclient_mock.call_count == 1

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_CO2_LIMIT: 0}
    )
    await hass.async_block_till_done()
    hass.states.async_set("sensor.station_co2", "5000", {"unit_of_measurement": "ppm"})
    await _press_upload(hass)
    assert aioclient_mock.call_count == 2
    assert hass.states.get("sensor.waqi_uploader_home_upload_status").state == "ok"


async def test_config_flow_stores_co2_limit(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(TOKEN_CHECK_URL, json={"status": "ok", "data": {}})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_STATION_ID: "s", **OPTIONS, CONF_CO2_LIMIT: 700.0}
    )
    assert result["options"][CONF_CO2_LIMIT] == 700
