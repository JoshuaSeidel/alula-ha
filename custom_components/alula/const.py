"""Constants for the Alula / Cove Security HA integration."""

from homeassistant.const import Platform

DOMAIN = "alula"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_REFRESH_TOKEN = "refresh_token"

PLATFORMS: list[Platform] = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
]

UPDATE_INTERVAL = 30  # seconds
