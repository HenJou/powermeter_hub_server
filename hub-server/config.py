import os

# Hub server config
SERVER_PORT = int(os.getenv("SERVER_PORT", "5000"))

# Logging level, values are DEBUG, INFO, WARN, ERROR, CRITICAL
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# SQL timeout in seconds
SQLITE_TIMEOUT = float(os.getenv("SQLITE_TIMEOUT", "5.0"))

# Enable or disable MQTT
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "false").lower() in ("true", "1", "yes", "on")

# MQTT configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "10.0.0.220")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USER = os.getenv("MQTT_USER", None)
MQTT_PASS = os.getenv("MQTT_PASS", None)
MQTT_BASE_TOPIC = os.getenv("MQTT_BASE_TOPIC", "home/efergy")

# Home Assistant MQTT Discovery
HA_DISCOVERY = os.getenv("HA_DISCOVERY", "false").lower() in ("true", "1", "yes", "on")
HA_DISCOVERY_PREFIX = os.getenv("HA_DISCOVERY_PREFIX", "homeassistant")
