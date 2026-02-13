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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Alula API."""
        try:
            devices = await self.client.async_get_devices()
            zones = await self.client.async_get_zones()

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

            # Group zones by device_id -> zone_index (last wins for duplicates)
            zone_map: dict[str, dict[int, Zone]] = {}
            for zone in zones:
                zone_map.setdefault(zone.device_id, {})[zone.zone_index] = zone

            return {
                "panels": panels,
                "cameras": cameras,
                "zones": zone_map,
            }

        except AlulaAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except (AlulaApiError, AlulaConnectionError) as err:
            raise UpdateFailed(f"API error: {err}") from err
