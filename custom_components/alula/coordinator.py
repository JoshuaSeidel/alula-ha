"""DataUpdateCoordinator for the Alula / Cove Security integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from alulapy import AlulaClient, AlulaApiError, AlulaAuthError, AlulaConnectionError
from alulapy.models import Device, Zone

from .const import CONF_REFRESH_TOKEN, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class AlulaDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the Alula API."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        client: AlulaClient,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.client = client
        self.config_entry = config_entry

    # ──────────────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Alula API."""
        try:
            devices = await self.client.async_get_devices()

            _LOGGER.debug("API returned %d devices", len(devices))

            if not devices:
                _LOGGER.warning(
                    "Alula API returned 0 devices — no entities will be "
                    "created. Verify the account has devices at "
                    "https://app.cove.com"
                )

            # Persist refresh token if it changed
            if self.client.refresh_token:
                new_data = {**self.config_entry.data}
                if new_data.get(CONF_REFRESH_TOKEN) != self.client.refresh_token:
                    new_data[CONF_REFRESH_TOKEN] = self.client.refresh_token
                    self.hass.config_entries.async_update_entry(
                        self.config_entry, data=new_data
                    )

            panels = {d.id: d for d in devices if d.is_panel}
            cameras = {d.id: d for d in devices if d.is_camera}

            if devices and not panels:
                _LOGGER.warning(
                    "Found %d devices but none are panels. "
                    "Device types: %s",
                    len(devices),
                    [d.device_type for d in devices],
                )

            # Fetch zones per panel via the device relationship endpoint
            # which returns ALL zones (not just notification-enabled ones).
            # Falls back to the notification zones endpoint if it fails.
            zones = await self._async_fetch_zones(list(panels.keys()))

            # Group zones by device_id -> zone_index
            zone_map: dict[str, dict[int, Zone]] = {}
            for zone in zones:
                zone_map.setdefault(zone.device_id, {})[zone.zone_index] = zone

            _LOGGER.debug(
                "Processed: %d panels, %d cameras, %d zone groups (%d total zones)",
                len(panels),
                len(cameras),
                len(zone_map),
                len(zones),
            )

            return {
                "panels": panels,
                "cameras": cameras,
                "zones": zone_map,
            }

        except AlulaAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except (AlulaApiError, AlulaConnectionError) as err:
            raise UpdateFailed(f"API error: {err}") from err

    # ──────────────────────────────────────────────────────────────────

    async def _async_fetch_zones(self, panel_ids: list[str]) -> list[Zone]:
        """Fetch zones, preferring per-device endpoint, falling back to notifications."""
        all_zones: list[Zone] = []

        # Try the per-device zones endpoint first (returns all zones).
        for panel_id in panel_ids:
            try:
                device_zones = await self.client.async_get_device_zones(panel_id)
                all_zones.extend(device_zones)
                _LOGGER.debug(
                    "Got %d zones from device endpoint for %s",
                    len(device_zones),
                    panel_id,
                )
            except (AlulaApiError, AlulaConnectionError) as err:
                _LOGGER.debug(
                    "Device zones endpoint failed for %s (%s), "
                    "will fall back to notification zones",
                    panel_id,
                    err,
                )
                all_zones = []
                break

        if all_zones:
            return all_zones

        # Fallback: notification zones (only returns push-enabled zones).
        _LOGGER.debug("Using notification zones endpoint as fallback")
        try:
            await self.client.async_renew_notifications()
        except (AlulaApiError, AlulaConnectionError) as err:
            _LOGGER.warning("Failed to renew notifications: %s", err)

        return await self.client.async_get_zones()
