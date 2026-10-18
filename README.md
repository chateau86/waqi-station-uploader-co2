# WAQI Station Uploader

Home Assistant custom integration that takes readings from any Home Assistant sensor entities that report PM2.5, PM10, CO2, temperature or humidity, from any device or integration, and uploads them to the [World Air Quality Index data platform](https://aqicn.org/data-feed/upload-api) on a schedule.

## How it works

1. You pick the sensor entities that hold your readings (PM2.5 is required; PM10, CO2, temperature and humidity are optional). They can come from any integration, such as Matter, ESPHome, MQTT or Zigbee.
2. This integration listens to those entities. Each time they change during the upload window, it records the new value.
3. At every interval (60 s by default), it averages the window and `POST`s it to `https://aqicn.org/sensor/upload/`. The upload includes `min`, `max`, `median` and `stddev` when the window has more than one sample, plus `averaging` set to the interval in seconds.

Temperature in °F or K is converted to °C. If a sensor is `unknown` or `unavailable` for the whole window, its reading is left out. If no sensor has data, the upload is skipped. If a CO2 sensor is set and any of its readings in the window is above the CO2 upload limit (600 ppm by default), the whole upload is skipped, because high CO2 usually means a local disturbance such as people or combustion near the sensor.

## Requirements

- Home Assistant 2024.11 or newer.
- At least one PM2.5 sensor entity in Home Assistant. PM10, CO2, temperature and humidity entities are optional.
- A WAQI token from <https://aqicn.org/data-platform/token/>.

## Installation

### HACS (custom repository)

[![Open your Home Assistant instance and open this repository in HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Atsukio&repository=waqi-station-uploader&category=integration)

Or add it manually:

1. In Home Assistant, open **HACS** → the three-dot menu (top right) → **Custom repositories**.
2. Paste `https://github.com/Atsukio/waqi-station-uploader`, set the type to **Integration**, and click **Add**.
3. Find **WAQI Station Uploader** in HACS, click **Download**, then restart Home Assistant.

### Manual

 copy `custom_components/waqi_station_uploader` into your Home Assistant `config/custom_components/` folder and restart.

## Setup

Settings → Devices & services → Add integration → **WAQI Station Uploader**.

| Field | Notes |
|---|---|
| Station ID | Private, unique ID on WAQI. Can't be changed later. |
| WAQI token | Validated against the WAQI API on save. |
| Station name | Public name on the WAQI map. |
| Latitude / Longitude | Defaults to your Home Assistant location. Enter both or neither. |
| PM2.5 sensor | Required. |
| PM10 / CO2 / Temperature / Humidity | Optional. |
| CO2 upload limit | Skip the upload if any CO2 reading in the window is above this (ppm). Default 600; 0 disables. Only applies when a CO2 sensor is set. |
| Upload interval | 60–3600 s. Default 60 s, which WAQI recommends. |

Everything except the station ID can be changed later under **Configure**.

After the first successful upload, verify and publish the station at <https://aqicn.org/data-feed/verification/>.

## Entities

| Entity | Description |
|---|---|
| `sensor.waqi_uploader_<name>_upload_status` | `pending` / `ok` / `error` / `skipped` / `inhibited` (CO2 above limit). Attributes: `last_error`, `last_readings`, `last_attempt`, `interval_seconds`, `co2_limit`. |
| `sensor.waqi_uploader_<name>_last_upload` | Timestamp of the last successful upload. |
| `button.waqi_uploader_<name>_upload_now` | Uploads the current window immediately. |

Example alert:

```yaml
automation:
  - alias: WAQI upload failing
    triggers:
      - trigger: state
        entity_id: sensor.waqi_uploader_my_air_quality_station_upload_status
        to: error
        for: "00:10:00"
    actions:
      - action: notify.notify
        data:
          message: >
            WAQI upload failing: {{ state_attr(trigger.entity_id, 'last_error') }}
```

## Debug logging

```yaml
logger:
  logs:
    custom_components.waqi_station_uploader: debug
```

The token is never logged or exposed in entity attributes.

## Development

```bash
python -m venv venv && ./venv/bin/pip install pytest-homeassistant-custom-component
./venv/bin/python -m pytest
```
