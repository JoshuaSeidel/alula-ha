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

            # Fetch zones via the notification endpoint (only source available)
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
        """One-time probe to log API structure for debugging."""
        raw_request = self.client._request  # noqa: SLF001

        _LOGGER.warning("=== ALULA API PROBE (one-time) ===")

        # 1) Fetch device with relationships
        try:
            raw = await raw_request(
                "GET", "/api/v1/devices",
                params={"page[size]": "1"},
            )
            if not raw.get("data"):
                _LOGGER.warning("PROBE: /api/v1/devices returned no data")
                return

            first = raw["data"][0] if isinstance(raw["data"], list) else raw["data"]
            device_id = first.get("id", "")

            # Log each relationship name and its links
            rels = first.get("relationships", {})
            _LOGGER.warning(
                "PROBE device relationship names: %s", list(rels.keys())
            )
            for rel_name, rel_data in rels.items():
                links = rel_data.get("links", {})
                _LOGGER.warning(
                    "PROBE relationship '%s' links: %s", rel_name, links
                )

        except Exception as err:
            _LOGGER.warning("PROBE devices failed: %s", err)
            return

        # 2) Follow each relationship link that might contain zones
        for rel_name, rel_data in rels.items():
            links = rel_data.get("links", {})
            related_url = links.get("related") or links.get("self")
            if not related_url:
                continue
            # Only probe relationships that might be zone-related
            try:
                raw = await raw_request(
                    "GET", related_url,
                    params={"page[size]": "3"},
                )
                data = raw.get("data", [])
                count = len(data) if isinstance(data, list) else (1 if data else 0)
                _LOGGER.warning(
                    "PROBE rel '%s' (%s) => %d items", rel_name, related_url, count
                )
                if data:
                    item = data[0] if isinstance(data, list) else data
                    attr_keys = list(item.get("attributes", {}).keys())
                    _LOGGER.warning(
                        "PROBE rel '%s' type=%s, attribute keys: %s",
                        rel_name,
                        item.get("type", "?"),
                        attr_keys,
                    )
                    # If this looks zone-like, dump the first item
                    if any(k in attr_keys for k in ("zoneIndex", "zoneName", "zoneStatus")):
                        _LOGGER.warning(
                            "PROBE rel '%s' ZONE DATA: %s",
                            rel_name,
                            json.dumps(item, indent=2, default=str),
                        )
            except Exception as err:
                _LOGGER.warning(
                    "PROBE rel '%s' (%s) => FAILED: %s", rel_name, related_url, err
                )

        # 3) Notification zones for comparison
        try:
            raw = await raw_request(
                "GET", "/api/v1/events/notifications/zones",
                params={"page[size]": "5"},
            )
            data = raw.get("data", [])
            _LOGGER.warning(
                "PROBE notification zones => %d items, keys: %s",
                len(data) if isinstance(data, list) else 0,
                list(data[0].get("attributes", {}).keys()) if data else [],
            )
            # Dump the full first notification zone for comparison
            if data:
                _LOGGER.warning(
                    "PROBE notification zone full: %s",
                    json.dumps(data[0], indent=2, default=str),
                )
        except Exception as err:
            _LOGGER.warning("PROBE notification zones => FAILED: %s", err)

        _LOGGER.warning("=== END ALULA API PROBE ===")
