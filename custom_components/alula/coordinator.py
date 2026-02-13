"""DataUpdateCoordinator for the Alula / Cove Security integration."""

from __future__ import annotations

from datetime import timedelta
import json
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
        self._probed = False

    # ──────────────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Alula API."""
        try:
            # One-time API probe to discover available endpoints/structure
            if not self._probed:
                await self._async_probe_api()
                self._probed = True

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
                    "Found %d devices but none are panels. Device types: %s",
                    len(devices),
                    [d.device_type for d in devices],
                )

            # Fetch zones – tries device endpoint, falls back to notifications
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

    async def _async_probe_api(self) -> None:
        """One-time probe to log API structure for debugging."""
        # Access the client's internal _request to make raw API calls
        # without needing a newer alulapy version.
        raw_request = self.client._request  # noqa: SLF001

        _LOGGER.warning("=== ALULA API PROBE (one-time) ===")

        # 1) Fetch a device WITH relationships to see what links exist
        try:
            raw = await raw_request(
                "GET", "/api/v1/devices",
                params={"page[size]": "1"},
            )
            if raw.get("data"):
                first = raw["data"][0] if isinstance(raw["data"], list) else raw["data"]
                _LOGGER.warning(
                    "PROBE device top-level keys: %s", list(first.keys())
                )
                if "relationships" in first:
                    _LOGGER.warning(
                        "PROBE device relationships: %s",
                        json.dumps(first["relationships"], indent=2, default=str),
                    )
                if "attributes" in first:
                    _LOGGER.warning(
                        "PROBE device attribute keys: %s",
                        list(first["attributes"].keys()),
                    )
                device_id = first.get("id", "")
            else:
                _LOGGER.warning("PROBE: /api/v1/devices returned no data")
                return
        except Exception as err:
            _LOGGER.warning("PROBE devices failed: %s", err)
            return

        # 2) Try several zone endpoint patterns
        zone_paths = [
            f"/api/v1/devices/{device_id}/zones",
            f"/api/v1/devices/{device_id}/device-zones",
            f"/api/v1/device-zones",
            f"/api/v1/zones",
        ]
        for path in zone_paths:
            try:
                raw = await raw_request(
                    "GET", path,
                    params={"page[size]": "5"},
                )
                data = raw.get("data", [])
                count = len(data) if isinstance(data, list) else (1 if data else 0)
                _LOGGER.warning("PROBE %s => %d items", path, count)
                if data:
                    first_zone = data[0] if isinstance(data, list) else data
                    _LOGGER.warning(
                        "PROBE %s first item keys: %s", path, list(first_zone.keys())
                    )
                    if "attributes" in first_zone:
                        _LOGGER.warning(
                            "PROBE %s attribute keys: %s",
                            path,
                            list(first_zone["attributes"].keys()),
                        )
                        _LOGGER.warning(
                            "PROBE %s first item attributes: %s",
                            path,
                            json.dumps(first_zone["attributes"], indent=2, default=str),
                        )
                    break  # Found a working endpoint
            except Exception as err:
                _LOGGER.warning("PROBE %s => FAILED: %s", path, err)

        # 3) Log the notification zones endpoint structure too
        try:
            raw = await raw_request(
                "GET", "/api/v1/events/notifications/zones",
                params={"page[size]": "5"},
            )
            data = raw.get("data", [])
            count = len(data) if isinstance(data, list) else 0
            _LOGGER.warning("PROBE /api/v1/events/notifications/zones => %d items", count)
            if data:
                _LOGGER.warning(
                    "PROBE notification zone attribute keys: %s",
                    list(data[0].get("attributes", {}).keys()),
                )
        except Exception as err:
            _LOGGER.warning("PROBE notification zones => FAILED: %s", err)

        _LOGGER.warning("=== END ALULA API PROBE ===")

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
