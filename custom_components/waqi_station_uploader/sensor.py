"""Status sensors for the WAQI uploader."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    STATUS_ERROR,
    STATUS_INHIBITED,
    STATUS_OK,
    STATUS_PENDING,
    STATUS_SKIPPED,
)
from .entity import WaqiUploaderEntity
from .uploader import WaqiConfigEntry


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaqiConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors."""
    uploader = entry.runtime_data
    async_add_entities(
        [
            UploadStatusSensor(uploader, "upload_status"),
            LastUploadSensor(uploader, "last_upload"),
        ]
    )


class UploadStatusSensor(WaqiUploaderEntity, SensorEntity):
    """Result of the most recent upload attempt."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [
        STATUS_PENDING,
        STATUS_OK,
        STATUS_ERROR,
        STATUS_SKIPPED,
        STATUS_INHIBITED,
    ]
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str:
        return self.uploader.last_status

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "station_id": self.uploader.station_id,
            "last_attempt": self.uploader.last_attempt,
            "last_error": self.uploader.last_error,
            "last_readings": self.uploader.last_readings,
            "interval_seconds": int(self.uploader.interval.total_seconds()),
            "co2_limit": self.uploader.co2_limit,
        }


class LastUploadSensor(WaqiUploaderEntity, SensorEntity):
    """Time of the last successful upload."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> datetime | None:
        return self.uploader.last_success
