"""DataUpdateCoordinator for the Alula / Cove Security integration."""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from alulapy import AlulaClient, AlulaApiError, AlulaAuthError, AlulaConnectionError
from alulapy.models import Zone, ZoneStatus

from .const import CONF_REFRESH_TOKEN, DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)

# Zone types from the event log that represent physical sensors.
# "User" type entries are user codes (e.g., "Joshua", "Entry Way") not sensors.
_SENSOR_ZONE_TYPES = {"Zone", "Fire", ""}

# How often (in polls) to do a deep event log scan for new zones.
# At 30s poll interval, 20 polls = ~10 minutes.
_DEEP_SCAN_INTERVAL = 20


def _filter_sensor_zones(
    raw_zones: dict[int, dict[str, str | None]],
) -> dict[int, dict[str, str | None]]:
    """Filter out non-sensor zones (e.g., user codes)."""
    return {
        idx: info
        for idx, info in raw_zones.items()
        if (info.get("zone_type") or "") in _SENSOR_ZONE_TYPES
    }


class AlulaDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the Alula API.

    The Alula API has no standalone zone configuration endpoint. Zones are
    discovered from event log entries as sensors trigger over time.  On each
    poll we check for newly-seen zones and automatically create notification
    subscriptions and HA entities for them.
    """

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
        self._zones_initialized = False
        self._poll_count = 0
        # zone_index -> {zone_name, zone_type} per panel
        self._zone_metadata: dict[str, dict[int, dict[str, str | None]]] = {}

    # ──────────────────────────────────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Alula API."""
        try:
            devices = await self.client.async_get_devices()
            _LOGGER.debug("API returned %d devices", len(devices))

            if not devices:
                _LOGGER.warning(
                    "Alula API returned 0 devices — verify the account at "
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

            # First run: deep scan event log and create subscriptions
            if not self._zones_initialized:
                await self._async_initialize_zones(panels)
                self._zones_initialized = True

            # Poll zone state from event log (also discovers new zones)
            zone_map = await self._async_poll_zone_states(panels)

            self._poll_count += 1

            _LOGGER.debug(
                "Poll #%d: %d panels, %d cameras, %d zone groups (%d zones)",
                self._poll_count,
                len(panels),
                len(cameras),
                len(zone_map),
                sum(len(zs) for zs in zone_map.values()),
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

    async def _async_initialize_zones(self, panels: dict[str, Any]) -> None:
        """Deep-scan event log for zones and create notification subscriptions."""
        for panel_id in panels:
            raw_zones = await self.client.async_discover_zones(panel_id)
            zone_info = _filter_sensor_zones(raw_zones)
            self._zone_metadata[panel_id] = zone_info
            _LOGGER.info(
                "Discovered %d sensor zones for panel %s: %s",
                len(zone_info),
                panel_id,
                {idx: info.get("zone_name") for idx, info in zone_info.items()},
            )

            if zone_info:
                created = await self.client.async_ensure_zone_subscriptions(
                    panel_id, list(zone_info.keys())
                )
                if created:
                    _LOGGER.info("Created %d new zone subscriptions", created)

                try:
                    await self.client.async_renew_notifications()
                except (AlulaApiError, AlulaConnectionError) as err:
                    _LOGGER.warning("Failed to renew notifications: %s", err)

    # ──────────────────────────────────────────────────────────────────

    async def _async_poll_zone_states(
        self, panels: dict[str, Any]
    ) -> dict[str, dict[int, Zone]]:
        """Determine current zone states from event log entries.

        Also discovers new zones from every batch of events.  Periodically
        does a deeper scan (500 events) to catch zones with infrequent
        activity.
        """
        # Periodically do a deep scan to discover zones with rare events
        deep_scan = (self._poll_count % _DEEP_SCAN_INTERVAL == 0)
        event_limit = 500 if deep_scan else 100

        zone_map: dict[str, dict[int, Zone]] = {}

        for panel_id in panels:
            metadata = self._zone_metadata.setdefault(panel_id, {})

            events = await self.client.async_get_event_log(
                panel_id, limit=event_limit
            )

            # Discover new zones from events
            new_zones = self._discover_new_zones(panel_id, events)
            if new_zones:
                _LOGGER.info(
                    "Discovered %d new zone(s) from event log: %s",
                    len(new_zones),
                    {idx: info.get("zone_name") for idx, info in new_zones.items()},
                )
                # Create subscriptions for new zones
                try:
                    created = await self.client.async_ensure_zone_subscriptions(
                        panel_id, list(new_zones.keys())
                    )
                    if created:
                        _LOGGER.info(
                            "Created %d subscriptions for new zones", created
                        )
                except (AlulaApiError, AlulaConnectionError) as err:
                    _LOGGER.warning(
                        "Failed to create subscriptions for new zones: %s", err
                    )

            # Build zone states from most recent event per zone
            zone_states: dict[int, Zone] = {}
            for event in events:  # sorted newest-first
                if not event.user_zone or not event.user_zone.isdigit():
                    continue
                zone_idx = int(event.user_zone)
                if zone_idx == 0 or zone_idx in zone_states:
                    continue
                # Only process zones we've accepted as sensors
                if zone_idx not in metadata:
                    continue

                # Contact ID qualifier: "1" = new event/open, "3" = restore/close
                is_open = event.event_qualifier == "1"

                meta = metadata.get(zone_idx, {})
                zone_name = meta.get("zone_name") or event.user_zone_alias
                zone_type = meta.get("zone_type") or event.user_zone_type

                zone_states[zone_idx] = Zone(
                    id=f"{panel_id}_zone_{zone_idx}",
                    device_id=panel_id,
                    zone_index=zone_idx,
                    status=ZoneStatus(name="open", is_active=is_open),
                    push_enabled=True,
                    zone_name=zone_name,
                    device_type_hint=zone_type,
                    raw={},
                )

            # Include all known zones, defaulting to closed if no recent event
            for zone_idx, meta in metadata.items():
                if zone_idx not in zone_states:
                    zone_states[zone_idx] = Zone(
                        id=f"{panel_id}_zone_{zone_idx}",
                        device_id=panel_id,
                        zone_index=zone_idx,
                        status=ZoneStatus(name="open", is_active=False),
                        push_enabled=True,
                        zone_name=meta.get("zone_name"),
                        device_type_hint=meta.get("zone_type"),
                        raw={},
                    )

            zone_map[panel_id] = zone_states

        return zone_map

    # ──────────────────────────────────────────────────────────────────

    def _discover_new_zones(
        self, panel_id: str, events: list
    ) -> dict[int, dict[str, str | None]]:
        """Check events for zones not yet in our metadata. Returns new ones."""
        metadata = self._zone_metadata.setdefault(panel_id, {})
        new_zones: dict[int, dict[str, str | None]] = {}

        for event in events:
            if not event.user_zone or not event.user_zone.isdigit():
                continue
            zone_idx = int(event.user_zone)
            if zone_idx == 0 or zone_idx in metadata or zone_idx in new_zones:
                continue

            zone_type = event.user_zone_type or ""
            if zone_type not in _SENSOR_ZONE_TYPES:
                continue

            new_zones[zone_idx] = {
                "zone_name": event.user_zone_alias,
                "zone_type": zone_type,
            }

        # Merge into metadata
        if new_zones:
            metadata.update(new_zones)

        return new_zones
