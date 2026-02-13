"""Alarm control panel entity for Alula / Cove Security."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from alulapy.const import ArmingState

from .const import DOMAIN
from .coordinator import AlulaDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

_STATE_MAP: dict[ArmingState, AlarmControlPanelState] = {
    ArmingState.DISARMED: AlarmControlPanelState.DISARMED,
    ArmingState.ARMED_STAY: AlarmControlPanelState.ARMED_HOME,
    ArmingState.ARMED_AWAY: AlarmControlPanelState.ARMED_AWAY,
    ArmingState.ARMED_NIGHT: AlarmControlPanelState.ARMED_NIGHT,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Alula alarm control panels."""
    coordinator: AlulaDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        AlulaAlarmPanel(coordinator, device_id)
        for device_id in coordinator.data.get("panels", {})
    )


class AlulaAlarmPanel(
    CoordinatorEntity[AlulaDataUpdateCoordinator], AlarmControlPanelEntity
):
    """An Alula/Cove alarm panel."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = (
        AlarmControlPanelEntityFeature.ARM_HOME
        | AlarmControlPanelEntityFeature.ARM_AWAY
        | AlarmControlPanelEntityFeature.ARM_NIGHT
    )
    _attr_code_arm_required = False

    def __init__(self, coordinator: AlulaDataUpdateCoordinator, device_id: str) -> None:
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"{device_id}_alarm"

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
            model=d.connected_panel_type if d else None,
            sw_version=d.raw.get("attributes", {}).get("firmwarePartNumber") if d else None,
            serial_number=d.serial_number if d else None,
        )

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        d = self._device
        if not d:
            return None
        return _STATE_MAP.get(d.arming_state, AlarmControlPanelState.DISARMED)

    @property
    def available(self) -> bool:
        d = self._device
        return super().available and d is not None and d.online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self._device
        if not d:
            return {}
        return {
            "last_armed_at": d.last_armed_at,
            "last_disarmed_at": d.last_disarmed_at,
            "online_status_timestamp": d.online_timestamp,
            "any_trouble": d.any_trouble,
            "ac_failure": d.ac_failure,
            "low_battery": d.low_battery,
            "arming_level_raw": d.arming_state.value,
        }

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        try:
            await self.coordinator.client.async_disarm(self._device_id)
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Disarm failed: %s", err)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        try:
            await self.coordinator.client.async_arm_stay(self._device_id)
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Arm Stay failed: %s", err)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        try:
            await self.coordinator.client.async_arm_away(self._device_id)
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Arm Away failed: %s", err)

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        try:
            await self.coordinator.client.async_arm_night(self._device_id)
            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.error("Arm Night failed: %s", err)
