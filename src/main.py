from time import sleep_ms

import machine
import network

from src.lib import config_util, ota_util
from src.lib.enum.operation_mode import OPERATION_Mode
from src.lib.powerpot_handler import PowerPotHandler
from src.lib.rest_api_handler import RestApiHandler
from src.lib.server_handler import ServerHandler

# TODO: implement dns on AP to redirect to config page
# TODO: implement low power mode / iot


# %% base
config = config_util.load_config()
config_changed = False
current_operation_mode = config.get("mode", OPERATION_Mode["Unknown"])

# %% network
wlan = None
wifi_config = config.get("wifi", {})
is_wifi_connected = False

ssid = wifi_config.get("ssid")
if ssid and current_operation_mode != OPERATION_Mode["IOT"]:
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    sleep_ms(100)
    wlan.config(txpower=8.5)
    wlan.connect(ssid, wifi_config.get("password", ""))

    timeout_counter = 0
    while not wlan.isconnected() and timeout_counter < 200:
        sleep_ms(100)
        timeout_counter += 1

    if wlan.isconnected():
        is_wifi_connected = True
        print("[Setup] WiFi network connected")
    else:
        print(f"[Setup] Can not connect to WiFi network {ssid}, Timeout! Status: {wlan.status()}")

if not is_wifi_connected:
    print("[Setup] WiFi network not connected")
    wlan = network.WLAN(network.AP_IF)
    wlan.active(True)
    sleep_ms(100)
    wlan.config(essid="PowerPot_" + ":".join('%02x' % b for b in wlan.config("mac")))
    print("[Setup] WiFi access point opened")

    if current_operation_mode != OPERATION_Mode["IOT"]:
        current_operation_mode = OPERATION_Mode["Standalone"]
    else:
        # TODO: implement timer for AccessPoint deactivation
        dummy = 0

# %% Server
server = None
if is_wifi_connected and current_operation_mode != OPERATION_Mode["Standalone"]:
    print("[Setup] Server connection")
    ifconfig = wlan.ifconfig()
    ip = ifconfig[0]
    subnet = ifconfig[1]
    mac_address = ":".join('%02x' % b for b in wlan.config("mac"))

    server = ServerHandler(
        ip,
        subnet,
        mac_address,
        config.get("serverIp", None),
        config.get("serverPort", None)
    )

    if server.ping_server():
        print("[Setup] Server ping success")
    else:
        result = server.discover_server()
        if result:
            server_ip = result[0]
            server_port = result[1]
            print(f"[Setup] Server found: {server_ip}:{server_port}")
            if server_ip != config.get("serverIp", None):
                config_changed = True
                config["serverIp"] = server_ip
            if server_port != config.get("serverPort", None):
                config_changed = True
                config["serverPort"] = server_port

            if current_operation_mode == OPERATION_Mode["Unknown"]:
                print("[Setup] OperationMode set to Client")
                current_operation_mode = OPERATION_Mode["Client"]
                config_changed = True
                config["mode"] = current_operation_mode
        else:
            server = None
            print("[Setup] No server found!")
            if current_operation_mode == OPERATION_Mode["Unknown"]:
                print("[Setup] OperationMode set to Standalone")
                current_operation_mode = OPERATION_Mode["Standalone"]
                config_changed = True
                config["mode"] = current_operation_mode

if config_changed:
    config_util.save_config(config)

# %% PowerPot
power_pot = PowerPotHandler(config, server)
power_pot.start()

# %% RestApi
rest_handler = RestApiHandler(power_pot, server)
# TODO: OperationMode IOT and LowPowerClient => kill api after x time (simular to AccessPoint)

# %% main
while True:
    # TODO: implement low power mode (light sleep and deep sleep)
    power_pot.run()

    updated = False
    if power_pot.should_check_update():
        if ota_util.check_firmware_version(config, server):
            updated = ota_util.update_firmware(config, server)

    # check on rest_handler is needed for future update
    if rest_handler and not updated:
        rest_handler.run()

    if server:
        server.flush(20 if updated else 1)

    if updated:
        machine.reset()

    sleep_ms(1)
