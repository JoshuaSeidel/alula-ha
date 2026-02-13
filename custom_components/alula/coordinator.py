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

            # Fetch zones via the notification endpoint
            try:
                await self.client.async_renew_notifications()
            except (AlulaApiError, AlulaConnectionError) as err:
                _LOGGER.warning("Failed to renew notifications: %s", err)

            zones = await self.client.async_get_zones()

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
        """One-time probe to find zone configuration data."""
        raw_request = self.client._request  # noqa: SLF001
        rpc = self.client._rpc  # noqa: SLF001

        _LOGGER.warning("=== ALULA API PROBE v3 ===")

        # 1) Get ALL devices and find panels
        try:
            raw = await raw_request(
                "GET", "/api/v1/devices",
                params={"page[size]": "10"},
            )
            devices = raw.get("data", [])
            _LOGGER.warning("PROBE: %d total devices", len(devices))
            for d in devices:
                attrs = d.get("attributes", {})
                _LOGGER.warning(
                    "PROBE device id=%s name=%s isPanel=%s isCamera=%s",
                    d.get("id"),
                    attrs.get("friendlyName"),
                    attrs.get("isPanel"),
                    attrs.get("isCamera"),
                )

            # Find the panel device
            panel = None
            for d in devices:
                if d.get("attributes", {}).get("isPanel"):
                    panel = d
                    break
            if not panel:
                _LOGGER.warning("PROBE: no panel device found")
                return
            panel_id = panel["id"]
            panel_attrs = panel.get("attributes", {})

        except Exception as err:
            _LOGGER.warning("PROBE devices failed: %s", err)
            return

        # 2) Check uiSettings for zone configuration
        ui_settings = panel_attrs.get("uiSettings")
        if ui_settings:
            if isinstance(ui_settings, dict):
                _LOGGER.warning(
                    "PROBE uiSettings keys: %s", list(ui_settings.keys())
                )
                # Look for zone config inside uiSettings
                zone_cfg = ui_settings.get("zoneConfiguration") or ui_settings.get("zones")
                if zone_cfg:
                    _LOGGER.warning(
                        "PROBE uiSettings.zoneConfiguration: %s",
                        json.dumps(zone_cfg, indent=2, default=str)[:3000],
                    )
                else:
                    # Dump first 3000 chars of uiSettings
                    _LOGGER.warning(
                        "PROBE uiSettings (no zoneConfiguration key): %s",
                        json.dumps(ui_settings, indent=2, default=str)[:3000],
                    )
            else:
                _LOGGER.warning(
                    "PROBE uiSettings type=%s value=%s",
                    type(ui_settings).__name__,
                    str(ui_settings)[:2000],
                )
        else:
            _LOGGER.warning("PROBE uiSettings: empty/missing")

        # 3) Check capabilities
        capabilities = panel_attrs.get("capabilities")
        if capabilities:
            _LOGGER.warning(
                "PROBE capabilities: %s",
                json.dumps(capabilities, indent=2, default=str)[:3000],
            )
        else:
            _LOGGER.warning("PROBE capabilities: empty/missing")

        # 4) Try RPC methods for zone configuration
        rpc_methods = [
            ("helix.getZoneConfiguration", {"deviceId": panel_id}),
            ("helix.getConfiguration", {"deviceId": panel_id}),
            ("helix.zones", {"deviceId": panel_id}),
            ("device.getZoneConfiguration", {"deviceId": panel_id}),
            ("events.notifications.zones", {"deviceId": panel_id}),
        ]
        for method, params in rpc_methods:
            try:
                result = await rpc(method, params)
                _LOGGER.warning(
                    "PROBE RPC %s => %s",
                    method,
                    json.dumps(result, indent=2, default=str)[:3000],
                )
            except Exception as err:
                _LOGGER.warning("PROBE RPC %s => FAILED: %s", method, err)

        # 5) Try fetching device with include parameter
        try:
            raw = await raw_request(
                "GET", f"/api/v1/devices/{panel_id}",
                params={"include": "notifications"},
            )
            included = raw.get("included", [])
            _LOGGER.warning(
                "PROBE device?include=notifications => %d included items", len(included)
            )
            if included:
                first = included[0]
                _LOGGER.warning(
                    "PROBE included type=%s keys=%s",
                    first.get("type"),
                    list(first.get("attributes", {}).keys()),
                )
        except Exception as err:
            _LOGGER.warning("PROBE include=notifications => FAILED: %s", err)

        _LOGGER.warning("=== END ALULA API PROBE v3 ===")
