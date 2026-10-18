"""Collects sensor samples from Home Assistant and uploads them to WAQI."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import statistics
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .api import WaqiError, async_upload
from .const import (
    CONF_CO2_ENTITY,
    CONF_CO2_LIMIT,
    CONF_INTERVAL,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    CONF_TEMPERATURE_ENTITY,
    CONF_TOKEN,
    DEFAULT_CO2_LIMIT,
    DEFAULT_INTERVAL,
    SPECIES,
    STATUS_ERROR,
    STATUS_INHIBITED,
    STATUS_OK,
    STATUS_PENDING,
    STATUS_SKIPPED,
)

_LOGGER = logging.getLogger(__name__)

type WaqiConfigEntry = ConfigEntry[WaqiUploader]


def merged_config(entry: ConfigEntry) -> dict[str, Any]:
    """Return entry data overlaid with options."""
    return {**entry.data, **entry.options}


class WaqiUploader:
    """Averages readings over each interval and pushes them to WAQI."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        conf = merged_config(entry)
        self.hass = hass
        self.entry = entry
        self._token: str = conf[CONF_TOKEN]
        self.station_id: str = conf[CONF_STATION_ID]
        self.station_name: str = conf.get(CONF_STATION_NAME) or self.station_id
        self.latitude: float | None = conf.get(CONF_LATITUDE)
        self.longitude: float | None = conf.get(CONF_LONGITUDE)
        self.interval = timedelta(seconds=int(conf.get(CONF_INTERVAL, DEFAULT_INTERVAL)))
        self.co2_limit: int = int(conf.get(CONF_CO2_LIMIT, DEFAULT_CO2_LIMIT))

        # entity_id -> (config key, specie, unit)
        self._sources: dict[str, tuple[str, str, str]] = {}
        for key, (specie, unit) in SPECIES.items():
            if entity_id := conf.get(key):
                self._sources[entity_id] = (key, specie, unit)

        self._samples: dict[str, list[float]] = {eid: [] for eid in self._sources}
        self._lock = asyncio.Lock()
        self._unsubs: list[CALLBACK_TYPE] = []
        self._listeners: list[Callable[[], None]] = []

        self.last_attempt: datetime | None = None
        self.last_success: datetime | None = None
        self.last_status: str = STATUS_PENDING
        self.last_error: str | None = None
        self.last_readings: dict[str, float] = {}

    # ------------------------------------------------------------------ setup
    async def async_start(self) -> None:
        """Seed samples from current states and start tracking."""
        for entity_id in self._sources:
            self._add_sample(entity_id, self.hass.states.get(entity_id))
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, list(self._sources), self._handle_state_change
            )
        )
        self._unsubs.append(
            async_track_time_interval(
                self.hass,
                self._handle_interval,
                self.interval,
                name=f"WAQI upload {self.station_id}",
                cancel_on_shutdown=True,
            )
        )

    @callback
    def async_stop(self) -> None:
        """Stop all tracking."""
        while self._unsubs:
            self._unsubs.pop()()

    # -------------------------------------------------------------- listeners
    @callback
    def async_add_listener(self, update_callback: Callable[[], None]) -> CALLBACK_TYPE:
        """Register an entity callback fired after every upload attempt."""
        self._listeners.append(update_callback)

        @callback
        def remove() -> None:
            self._listeners.remove(update_callback)

        return remove

    @callback
    def _notify(self) -> None:
        for update_callback in list(self._listeners):
            update_callback()

    # ---------------------------------------------------------------- samples
    def _parse_state(self, entity_id: str, state: State | None) -> float | None:
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, ""):
            return None
        try:
            value = float(state.state)
        except ValueError:
            return None
        key = self._sources[entity_id][0]
        if key == CONF_TEMPERATURE_ENTITY:
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            if unit in (UnitOfTemperature.FAHRENHEIT, UnitOfTemperature.KELVIN):
                value = TemperatureConverter.convert(
                    value, unit, UnitOfTemperature.CELSIUS
                )
        return value

    def _add_sample(self, entity_id: str, state: State | None) -> None:
        value = self._parse_state(entity_id, state)
        if value is not None:
            self._samples[entity_id].append(value)

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        entity_id = event.data["entity_id"]
        if entity_id in self._samples:
            self._add_sample(entity_id, event.data["new_state"])

    # ----------------------------------------------------------------- upload
    async def _handle_interval(self, _now: datetime) -> None:
        await self.async_upload()

    def build_readings(self, now: datetime) -> list[dict[str, Any]]:
        """Summarise collected samples and start a new averaging window."""
        readings: list[dict[str, Any]] = []
        for entity_id, (_key, specie, unit) in self._sources.items():
            samples = self._samples[entity_id]
            # Many sensors (e.g. Matter) only report on change, so the current state is
            # still valid for this window if nothing changed.
            if not samples:
                current = self._parse_state(entity_id, self.hass.states.get(entity_id))
                samples = [current] if current is not None else []
            # New window starts with the latest known value.
            current = self._parse_state(entity_id, self.hass.states.get(entity_id))
            self._samples[entity_id] = [current] if current is not None else []
            if not samples:
                continue

            reading: dict[str, Any] = {
                "specie": specie,
                "value": round(statistics.fmean(samples), 2),
                "unit": unit,
                "time": now.isoformat(),
                "averaging": int(self.interval.total_seconds()),
            }
            if len(samples) > 1:
                reading["min"] = round(min(samples), 2)
                reading["max"] = round(max(samples), 2)
                reading["median"] = round(statistics.median(samples), 2)
                reading["stddev"] = round(statistics.pstdev(samples), 2)
            readings.append(reading)
        return readings

    def build_payload(self, readings: list[dict[str, Any]]) -> dict[str, Any]:
        """Build the WAQI upload body."""
        station: dict[str, Any] = {"id": self.station_id, "name": self.station_name}
        if self.latitude is not None and self.longitude is not None:
            station["location"] = {
                "latitude": self.latitude,
                "longitude": self.longitude,
            }
        return {"token": self._token, "station": station, "readings": readings}

    async def async_upload(self) -> None:
        """Upload the current averaging window to WAQI."""
        async with self._lock:
            now = dt_util.now()
            self.last_attempt = now
            readings = self.build_readings(now)
            if not readings:
                self.last_status = STATUS_SKIPPED
                self.last_error = "No valid readings from the selected sensors"
                _LOGGER.debug("Skipping WAQI upload for %s: no readings", self.station_id)
                self._notify()
                return

            co2_specie = SPECIES[CONF_CO2_ENTITY][0]
            # Any single sample over the limit stops the upload; the sensor's own
            # response already smooths out momentary noise.
            co2 = next(
                (r.get("max", r["value"]) for r in readings if r["specie"] == co2_specie),
                None,
            )
            if self.co2_limit and co2 is not None and co2 > self.co2_limit:
                self.last_status = STATUS_INHIBITED
                self.last_error = (
                    f"CO2 reached {co2} ppm, above the {self.co2_limit} ppm limit"
                )
                _LOGGER.debug(
                    "Skipping WAQI upload for %s: CO2 %s ppm above limit %s ppm",
                    self.station_id,
                    co2,
                    self.co2_limit,
                )
                self._notify()
                return

            session = async_get_clientsession(self.hass)
            try:
                await async_upload(session, self.build_payload(readings))
            except WaqiError as err:
                if self.last_status != STATUS_ERROR:
                    _LOGGER.warning("WAQI upload for %s failed: %s", self.station_id, err)
                else:
                    _LOGGER.debug("WAQI upload for %s failed again: %s", self.station_id, err)
                self.last_status = STATUS_ERROR
                self.last_error = str(err)
            else:
                if self.last_status == STATUS_ERROR:
                    _LOGGER.info("WAQI upload for %s recovered", self.station_id)
                self.last_status = STATUS_OK
                self.last_error = None
                self.last_success = now
                self.last_readings = {r["specie"]: r["value"] for r in readings}
                _LOGGER.debug("Uploaded to WAQI: %s", self.last_readings)
            self._notify()
