"""The Alula / Cove Security integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from alulapy import AlulaClient, AlulaAuthError, AlulaConnectionError

from .const import CONF_PASSWORD, CONF_REFRESH_TOKEN, CONF_USERNAME, DOMAIN, PLATFORMS
from .coordinator import AlulaDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alula / Cove Security from a config entry."""
    session = async_get_clientsession(hass)
    client = AlulaClient(session)

    refresh_token = entry.data.get(CONF_REFRESH_TOKEN)

    try:
        if refresh_token:
            client.restore_tokens(
                access_token="",
                refresh_token=refresh_token,
                expires_in=0,
            )
            try:
                await client.async_refresh()
            except Exception:
                _LOGGER.debug("Token refresh failed, re-authenticating")
                await client.async_login(
                    entry.data[CONF_USERNAME],
                    entry.data[CONF_PASSWORD],
                )
        else:
            await client.async_login(
                entry.data[CONF_USERNAME],
                entry.data[CONF_PASSWORD],
            )
    except AlulaAuthError as err:
        _LOGGER.error("Authentication failed: %s", err)
        return False
    except (AlulaConnectionError, Exception) as err:
        raise ConfigEntryNotReady(
            f"Unable to connect to Alula API: {err}"
        ) from err

    coordinator = AlulaDataUpdateCoordinator(hass, client, entry)
    await coordinator.async_config_entry_first_refresh()

    data = coordinator.data or {}
    _LOGGER.debug(
        "First refresh complete — panels: %d, cameras: %d, zone groups: %d",
        len(data.get("panels", {})),
        len(data.get("cameras", {})),
        len(data.get("zones", {})),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
