"""Sensor entities for Alula / Cove Security."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
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
    """Set up Alula sensor entities."""
    coordinator: AlulaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []

    for device_id in coordinator.data.get("panels", {}):
        entities.append(AlulaTroubleSensor(coordinator, device_id))
        entities.append(AlulaLastEventSensor(coordinator, device_id))

    async_add_entities(entities)


class AlulaTroubleSensor(
    CoordinatorEntity[AlulaDataUpdateCoordinator], SensorEntity
):
    """Overall trouble status with per-flag attributes."""

    _attr_has_entity_name = True
    _attr_name = "Trouble Status"

    def __init__(self, coordinator: AlulaDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_trouble"

    @property
    def _device(self):
        return self.coordinator.data.get("panels", {}).get(self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        d = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=d.name if d else "Alula Panel",
            manufacturer="Alula / Cove",
        )

    @property
    def native_value(self) -> str:
        d = self._device
        return "Trouble" if d and d.any_trouble else "OK"

    @property
    def icon(self) -> str:
        d = self._device
        return "mdi:shield-alert" if d and d.any_trouble else "mdi:shield-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._device
        if not d:
            return {}
        return {
            "any_trouble": d.any_trouble,
            "ac_failure": d.ac_failure,
            "low_battery": d.low_battery,
            "server_comm_fail": d.server_comm_fail,
            "cs_comm_fail": d.cs_comm_fail,
            "low_battery_zones": d.low_battery_zones,
            "tamper_zones": d.tamper_zones,
            "alarm_zones": d.alarm_zones,
            "trouble_zones": d.trouble_zones,
            "fire_trouble": d.fire_trouble,
            "arming_protest": d.arming_protest,
        }


class AlulaLastEventSensor(
    CoordinatorEntity[AlulaDataUpdateCoordinator], SensorEntity
):
    """Last arming event."""

    _attr_has_entity_name = True
    _attr_name = "Last Event"
    _attr_icon = "mdi:history"

    def __init__(self, coordinator: AlulaDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_last_event"

    @property
    def _device(self):
        return self.coordinator.data.get("panels", {}).get(self._device_id)

    @property
    def device_info(self) -> DeviceInfo:
        d = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=d.name if d else "Alula Panel",
            manufacturer="Alula / Cove",
        )

    @property
    def native_value(self) -> str | None:
        d = self._device
        if not d:
            return None
        if d.last_armed_at and d.last_disarmed_at:
            if d.last_armed_at > d.last_disarmed_at:
                return f"Armed ({d.arming_state.value})"
            return "Disarmed"
        if d.last_armed_at:
            return f"Armed ({d.arming_state.value})"
        if d.last_disarmed_at:
            return "Disarmed"
        return d.arming_state.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._device
        if not d:
            return {}
        return {
            "last_armed_at": d.last_armed_at,
            "last_disarmed_at": d.last_disarmed_at,
            "arming_state": d.arming_state.value,
        }
