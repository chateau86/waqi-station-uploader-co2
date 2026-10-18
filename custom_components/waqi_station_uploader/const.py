"""Constants for the WAQI Station Uploader."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "waqi_station_uploader"

UPLOAD_URL: Final = "https://aqicn.org/sensor/upload/"
TOKEN_CHECK_URL: Final = "https://api.waqi.info/feed/here/"
TOKEN_PAGE_URL: Final = "https://aqicn.org/data-platform/token/"

CONF_TOKEN: Final = "token"
CONF_STATION_ID: Final = "station_id"
CONF_STATION_NAME: Final = "station_name"
CONF_LATITUDE: Final = "latitude"
CONF_LONGITUDE: Final = "longitude"
CONF_INTERVAL: Final = "interval"

CONF_CO2_ENTITY: Final = "co2_entity"
CONF_PM25_ENTITY: Final = "pm25_entity"
CONF_PM10_ENTITY: Final = "pm10_entity"
CONF_TEMPERATURE_ENTITY: Final = "temperature_entity"
CONF_HUMIDITY_ENTITY: Final = "humidity_entity"

DEFAULT_STATION_ID: Final = "my-waqi-station"
DEFAULT_STATION_NAME: Final = "My Air Quality Station"
DEFAULT_INTERVAL: Final = 60  # seconds; WAQI recommends 1-minute averages
MIN_INTERVAL: Final = 60
MAX_INTERVAL: Final = 3600

# config key -> (WAQI specie name, WAQI unit)
SPECIES: Final[dict[str, tuple[str, str]]] = {
    CONF_CO2_ENTITY: ("co2", "ppm"),
    CONF_PM25_ENTITY: ("pm2.5", "µg/m3"),
    CONF_PM10_ENTITY: ("pm10", "µg/m3"),
    CONF_TEMPERATURE_ENTITY: ("temp", "C"),
    CONF_HUMIDITY_ENTITY: ("humidity", "%"),
}

STATUS_OK: Final = "ok"
STATUS_ERROR: Final = "error"
STATUS_SKIPPED: Final = "skipped"
STATUS_PENDING: Final = "pending"
