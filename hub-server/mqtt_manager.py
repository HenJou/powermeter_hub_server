import json
import logging
import time
import paho.mqtt.client as mqtt
from config import (
    MQTT_ENABLED, MQTT_BROKER, MQTT_PORT, MQTT_USER, MQTT_PASS,
    MQTT_BASE_TOPIC, HA_DISCOVERY, HA_DISCOVERY_PREFIX
)

ENERGY_SENSOR_LABEL = "energy_consumption"

class MQTTManager:
    def __init__(self, max_retries: int = 10, retry_interval: int = 5):
        self.enabled = MQTT_ENABLED
        self.discovery_enabled = HA_DISCOVERY
        self.discovery_sent = set()
        self.max_retries = max_retries
        self.retry_interval = retry_interval
        self.connected = False

        if not self.enabled:
            logging.debug("MQTT disabled via config.")
            return

        logging.debug("Initializing MQTT client...")
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

        if MQTT_USER:
            self.client.username_pw_set(MQTT_USER, MQTT_PASS)

        # Configure auto-reconnect delays
        self.client.reconnect_delay_set(min_delay=1, max_delay=120)

        # Set callback to log connection events
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        # Attempt initial connection with retries
        self._connect_with_retry()

        # Start network loop in background
        self.client.loop_start()


    def _connect_with_retry(self):
        retries = 0
        while retries < self.max_retries:
            try:
                self.client.connect(MQTT_BROKER, MQTT_PORT)
                logging.debug(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
                return
            except Exception as e:
                retries += 1
                logging.warning(f"MQTT connection attempt {retries} failed: {e}")
                time.sleep(self.retry_interval)
        logging.error("Failed to connect to MQTT broker after multiple attempts.")
        self.enabled = False


    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self.connected = True
            logging.debug("MQTT connected successfully.")
        else:
            logging.warning(f"MQTT connection returned code {rc}")


    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        if rc != 0:
            logging.warning(f"Unexpected MQTT disconnect (rc={rc}). Will auto-reconnect.")


    # Generic publishing
    def publish(self, topic: str, payload: dict, retain: bool = False):
        if not self.enabled:
            return

        # Wait until MQTT is connected
        wait_count = 0
        while not self.connected and wait_count < 50:
            logging.debug(f"Waiting for MQTT connection to publish {topic}...")
            time.sleep(0.1)
            wait_count += 1

        if not self.connected:
            logging.warning(f"MQTT not connected, skipping publish: {topic}")
            return

        try:
            self.client.publish(topic, json.dumps(payload), retain=retain)
        except Exception as e:
            logging.error(f"MQTT publish failed: {topic} — {e}")


    def publish_power_discovery(self, label: str, sid: str, topic: str):
        if not self.enabled or not HA_DISCOVERY:
            return

        config_topic = f"{HA_DISCOVERY_PREFIX}/sensor/{label}/config"

        payload = {
            "name": f"Live power usage - {sid}",
            "state_topic": topic,
            "unit_of_measurement": "kW",
            "value_template": "{{ value_json.value }}",
            "unique_id": label,
            "icon": "mdi:flash",
            "device_class": "power",
            "state_class": "measurement",
            "device": {
                "name": "Efergy Hub",
                "identifiers": [f"efergy"],
                "manufacturer": "Efergy",
                "model": f"Hub"
            }
        }

        self.publish(config_topic, payload, retain=True)
        self.discovery_sent.add(label)


    def publish_energy_discovery(self, topic: str):
        """
        Home Assistant discovery for energy sensor.
        """
        if not self.enabled or not HA_DISCOVERY:
            return

        config_topic = f"{HA_DISCOVERY_PREFIX}/sensor/{ENERGY_SENSOR_LABEL}/config"

        payload = {
            "name": "Energy consumption",
            "state_topic": topic,
            "unit_of_measurement": "kWh",
            "value_template": "{{ value_json.value }}",
            "unique_id": ENERGY_SENSOR_LABEL,
            "icon": "mdi:lightning-bolt",
            "device_class": "energy",
            "state_class": "total_increasing",
            "device": {
                "name": "Efergy Hub",
                "identifiers": [f"efergy"],
                "manufacturer": "Efergy",
                "model": f"Hub",
            }
        }

        self.publish(config_topic, payload, retain=True)
        self.discovery_sent.add(ENERGY_SENSOR_LABEL)


    # Publishes reading AND automatically discovery if needed
    def publish_power(self, label: str, sid: str, value_kw: float):
        if not self.enabled:
            return

        logging.debug(f"Publishing power for {label} with value {value_kw}")
        topic = f"{MQTT_BASE_TOPIC}/{label}/power"

        # Publish actual reading
        self.publish(topic, {"value": value_kw})

        # Publish discovery ONLY once
        if self.discovery_enabled and label not in self.discovery_sent:
            self.publish_power_discovery(label, sid, topic)
            self.discovery_sent.add(label)


    def publish_energy(self, value_kwh: float):
        """
        Publish energy consumption (kWh).
        """
        if not self.enabled:
            return

        logging.debug(f"Publishing energy for {ENERGY_SENSOR_LABEL} with value {value_kwh}")
        topic = f"{MQTT_BASE_TOPIC}/{ENERGY_SENSOR_LABEL}/energy"

        # Publish energy consumption
        self.publish(topic, {"value": value_kwh})

        # Publish discovery ONLY once
        if self.discovery_enabled and ENERGY_SENSOR_LABEL not in self.discovery_sent:
            self.publish_energy_discovery(topic)


    def get_topic(self, label, sensor_type="power"):
        if sensor_type == "power":
            return f"{MQTT_BASE_TOPIC}/{label}/power"
        else:
            return f"{MQTT_BASE_TOPIC}/{label}/energy"


    def publish_startup_discovery(self, labels):
        """
        Publish HA discovery for all stored sensors at startup.
        """
        if not self.enabled or not HA_DISCOVERY:
            return

        logging.debug(f"Publishing discovery info for {len(labels)} stored sensors...")

        for label in labels:
            parts = label.split("_")
            if len(parts) < 3:
                continue

            # Power topic
            sid = parts[2]
            power_topic = self.get_topic(label, sensor_type="power")
            self.publish_power_discovery(label, sid, power_topic)

        # Energy topic
        energy_topic = self.get_topic(ENERGY_SENSOR_LABEL, sensor_type="energy")
        self.publish_energy_discovery(energy_topic)
