"""Binary sensor entities for Alula / Cove Security zones."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AlulaDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


def _guess_device_class(
    zone_name: str | None, zone_type: str | None
) -> BinarySensorDeviceClass:
    """Infer binary sensor device class from zone name and type hint."""
    combined = " ".join(filter(None, [zone_name, zone_type])).lower()
    if "motion" in combined:
        return BinarySensorDeviceClass.MOTION
    if "window" in combined:
        return BinarySensorDeviceClass.WINDOW
    if "smoke" in combined or "fire" in combined:
        return BinarySensorDeviceClass.SMOKE
    if "water" in combined or "flood" in combined:
        return BinarySensorDeviceClass.MOISTURE
    return BinarySensorDeviceClass.DOOR


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Alula binary sensors for zones.

    Creates entities for currently-known zones and registers a listener
    to auto-add new zones as they are discovered from the event log.
    """
    coordinator: AlulaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Track which zones already have entities
    known_keys: set[tuple[str, int]] = set()

    entities: list[AlulaZoneSensor] = []
    for device_id, zones in coordinator.data.get("zones", {}).items():
        for zone_index in zones:
            known_keys.add((device_id, zone_index))
            entities.append(AlulaZoneSensor(coordinator, device_id, zone_index))

    async_add_entities(entities)

    @callback
    def _async_check_new_zones() -> None:
        """Check for newly discovered zones and add entities for them."""
        new_entities: list[AlulaZoneSensor] = []
        for device_id, zones in coordinator.data.get("zones", {}).items():
            for zone_index in zones:
                key = (device_id, zone_index)
                if key not in known_keys:
                    known_keys.add(key)
                    new_entities.append(
                        AlulaZoneSensor(coordinator, device_id, zone_index)
                    )
        if new_entities:
            _LOGGER.info(
                "Adding %d new zone entity/entities: %s",
                len(new_entities),
                [e._attr_name for e in new_entities],
            )
            async_add_entities(new_entities)

    # Listen for coordinator updates to detect new zones
    entry.async_on_unload(coordinator.async_add_listener(_async_check_new_zones))


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
            self._attr_device_class = _guess_device_class(
                zone.zone_name, zone.device_type_hint
            )
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
