# Efergy Hub Local Data Logger

This project provides a local emulation server for legacy Efergy Engage hubs (v2 and v3). 
It allows you to intercept and log your home's energy data to a local SQLite database, completely bypassing the 
decommissioned Efergy cloud servers.

This is designed for anyone who wants to keep their devices from becoming e-waste.

## How it Works

The Efergy Hub is hard-coded to send its data to `sensornet.info` over HTTPS. 
Unfortunately, these old devices use the deprecated SSLv3 protocol, which modern web servers and Python libraries will 
not accept.

This project solves the problem with a two-service system managed by Docker Compose:

1. **`legacy-nginx` Service**: A custom-built Nginx server acts as a reverse proxy. It uses an old version of OpenSSL (1.0.2u) specifically compiled to accept the hub's SSLv3 connection. It then terminates the SSL and forwards the decrypted HTTP traffic to the Python application.
2. **`hub-server` Service**: A lightweight Python 3 server (`hub_server.py`) that listens for the forwarded requests. It receives the plain HTTP request from the Nginx proxy, emulates the Efergy API, and logs the data to a SQLite database (`readings.db`) using the `db.py` script.

## Efergy Data Format

The hub sends data via `POST` requests to the `/h2` or `/h3` endpoint. The body of this request contains a pipe-delimited string with the sensor data.

**Example Packet:** `741459|1|EFCT|P1,2479.98`

Here is a breakdown of the data structure:

| Index | Value      | Purpose                                                                                                                      |
|-------|------------|------------------------------------------------------------------------------------------------------------------------------|
| [0]   | 741459     | **Sensor ID** (`sid`): This is the unique ID for your transmitter. This is the **primary value** used by the logger.         |
| [1]   | 1          | **(Guessed) Transmitter Port**: The Efergy transmitter has 3-5 ports. This `1` likely indicates the data is from **Port 1**. |
| [2]   | EFCT       | **(Guessed) Data Type ID**: A "Channel ID" that likely stands for **EF** (Efergy) + **CT** (Current Transformer).            |
| [3]   | P1,2479.98 | **Port 1 Value**: Contains the port identifier (`P1`) and the actual power reading in Watts (`2479.98`).                     |

The Python server parses this string to extract the **Sensor ID** (`741459`) and the **Value** (`2479.98`).
It then logs this value to the database under a label like `efergy_h2_741459`.

## Setup with Docker Compose

### 1. Generate SSL Certificates

The `legacy-nginx` service requires SSL certificates to run. A helper script is provided to generate self-signed certificates.

1. Open generate_cert.sh in a text editor.
2. Run the script from the project's root directory:

```shell
./generate-certs.sh
```
This will create `server.key` and `server.crt` inside the `legacy-nginx` directory, where the `docker-compose.yml` file 
expects to find them.

### 2. Run the Services

With the certificates in place, you can start both services using Docker Compose.

```shell
# Build and start the containers in detached mode
docker-compose up --build -d
```

This will:
* Build the `hub-server` image from its Dockerfile.
* Build the `legacy-nginx` image from its Dockerfile.
* Start both containers. The `legacy-nginx` service is exposed on port `443`.
* Mount the `readings.db` file from the project root into the `hub-server` container.

### 3. Redirect the Efergy Hub

Finally, you must trick your Efergy Hub into sending data to your new server instead of `sensornet.info`.
The easiest way to do this is with DNS spoofing on your router (e.g., using `dnsmasq`, `Pi-hole`, or similar):

Create a DNS entry that maps `sensornet.info` to the local IP address of the machine running your Docker container 
(e.g., `192.168.1.100`).

Once the hub is rebooted, it will contact `sensornet.info`, be directed to your `legacy-nginx` proxy, and your 
`hub-server` should start logging data to `readings.db`.


## Home Assistant Integration

You can integrate your local energy data into Home Assistant using the [SQL Sensor](https://www.home-assistant.io/integrations/sql/) 
integration. 
This allows Home Assistant to directly query the `readings.db` file.

The provided `sensors.yaml` file is a configuration snippet you can add to your Home Assistant setup.

1. **Ensure Home Assistant can access the database.** Make sure your `readings.db` file is located somewhere [Home Assistant](https://www.home-assistant.io/) can read it (e.g., in your /config directory).
2. **Add the SQL integration** to your `configuration.yaml` if you haven't already.
3. **Add the sensor configuration.** You can copy the contents of `sensors.yaml` into your Home Assistant's `configuration.yaml` (under a sql: key) or, if you have a split configuration, !include it.

`configuration.yaml` example:
```yaml

# Loads default set of integrations. Do not remove.
default_config:

# Load frontend themes from the themes folder
frontend:
  themes: !include_dir_merge_named themes

automation: !include automations.yaml
script: !include scripts.yaml
scene: !include scenes.yaml
sql: !include sensors.yaml
```

4. **Update the** `db_url` in `sensors.yaml`.
5. **Restart Home Assistant**.

You will now have two sensors:
* `sensor.efergy_power_usage`: The instantaneous power reading in kW.
* `sensor.efergy_energy_consumption`: A running total of energy consumed in kWh, which can be added directly to your Home Assistant Energy Dashboard.