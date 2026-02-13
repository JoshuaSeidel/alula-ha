"""Binary sensor entities for Alula / Cove Security zones."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AlulaDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Alula binary sensors for zones."""
    coordinator: AlulaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[AlulaZoneSensor] = []
    for device_id, zones in coordinator.data.get("zones", {}).items():
        for zone_index, zone in zones.items():
            entities.append(AlulaZoneSensor(coordinator, device_id, zone_index))

    async_add_entities(entities)


class AlulaZoneSensor(
    CoordinatorEntity[AlulaDataUpdateCoordinator], BinarySensorEntity
):
    """A zone sensor (door/window/motion)."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(
        self,
        coordinator: AlulaDataUpdateCoordinator,
        device_id: str,
        zone_index: int,
    ) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._zone_index = zone_index
        self._attr_unique_id = f"{device_id}_zone_{zone_index}"

        # Set name and device class from zone data
        zone = self._zone
        if zone:
            self._attr_name = zone.zone_name or f"Zone {zone_index}"
            if zone.device_type_hint:
                dt = zone.device_type_hint.lower()
                if "motion" in dt:
                    self._attr_device_class = BinarySensorDeviceClass.MOTION
                elif "window" in dt:
                    self._attr_device_class = BinarySensorDeviceClass.WINDOW
                elif "smoke" in dt or "fire" in dt:
                    self._attr_device_class = BinarySensorDeviceClass.SMOKE
                elif "water" in dt or "flood" in dt:
                    self._attr_device_class = BinarySensorDeviceClass.MOISTURE
        else:
            self._attr_name = f"Zone {zone_index}"

    @property
    def _zone(self):
        return (
            self.coordinator.data.get("zones", {})
            .get(self._device_id, {})
            .get(self._zone_index)
        )

    @property
    def device_info(self) -> DeviceInfo:
        panel = self.coordinator.data.get("panels", {}).get(self._device_id)
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=panel.name if panel else "Alula Panel",
            manufacturer="Alula / Cove",
        )

    @property
    def is_on(self) -> bool | None:
        zone = self._zone
        return zone.is_open if zone else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        zone = self._zone
        return {
            "zone_index": self._zone_index,
            "zone_name": zone.zone_name if zone else None,
            "device_type_hint": zone.device_type_hint if zone else None,
        }
