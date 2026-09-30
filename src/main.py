import time
from time import sleep_ms

import machine
import network

from src.lib import config_util, ota_util, rtc_memory_util
from src.lib.enum.operation_mode import OPERATION_Mode
from src.lib.enum.operation_state import OPERATION_State
from src.lib.powerpot_handler import PowerPotHandler
from src.lib.rest_api_handler import RestApiHandler
from src.lib.server_handler import ServerHandler

# TODO: implement dns on AP to redirect to config page

reset_cause = machine.reset_cause()

# %% config & operation mode
config = config_util.load_config()
config_changed = False
current_operation_mode = config.get("mode", OPERATION_Mode["Unknown"])

# rtc memory
rtc_memory = rtc_memory_util.load_from_rtc_memory()
ota_duration = 0
if current_operation_mode == OPERATION_Mode["Low_Power"] and rtc_memory:
    ota_duration = max(0, rtc_memory.get("ota_duration", 0) - config.get("checkCycleInterval", 3_600_000))   # minus slept time

# %% network
wlan = None
wifi_config = config.get("wifi", {})
is_wifi_connected = False

ssid = wifi_config.get("ssid")
if ssid and (reset_cause != machine.DEEPSLEEP_RESET or ota_duration <= 0):
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

if not is_wifi_connected and reset_cause != machine.DEEPSLEEP_RESET:
    print("[Setup] WiFi network not connected")
    wlan = network.WLAN(network.AP_IF)
    wlan.active(True)
    sleep_ms(100)
    wlan.config(essid="PowerPot_" + ":".join('%02x' % b for b in wlan.config("mac")))
    print("[Setup] WiFi access point opened")

    if current_operation_mode != OPERATION_Mode["Low_Power"]:
        current_operation_mode = OPERATION_Mode["Standalone"]

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
if current_operation_mode == OPERATION_Mode["Low_Power"]:
    power_pot = PowerPotHandler(config=config, server_handler=server, check_update_ms=ota_duration)
else:
    power_pot = PowerPotHandler(config=config, server_handler=server)
power_pot.start()

# %% RestApi
rest_handler = None
if current_operation_mode != OPERATION_Mode["Low_Power"] or reset_cause != machine.DEEPSLEEP_RESET:
    rest_handler = RestApiHandler(power_pot, server)

tick_timer = None
if current_operation_mode == OPERATION_Mode["Low_Power"] and (
        reset_cause != machine.DEEPSLEEP_RESET or ota_duration <= 0):
    tick_timer = time.ticks_add(time.ticks_ms(), 300_000)   # TODO: Load time from config

# %% main
while True:
    if current_operation_mode == OPERATION_Mode["Low_Power"] and (
            tick_timer and time.ticks_diff(time.ticks_ms(), tick_timer) >= 0):
        tick_timer = None
        is_wifi_connected = False
        if server:
            server.flush(20)
            server = None
        if wlan:
            wlan.active(False)

    power_pot.run()

    updated = False
    if power_pot.should_check_update() and is_wifi_connected:
        if ota_util.check_firmware_version(config, server):
            updated = ota_util.update_firmware(config, server)

    if rest_handler and (current_operation_mode != OPERATION_Mode["Low_Power"] or tick_timer):
        rest_handler.run()

    if is_wifi_connected and server:
        server.flush(20 if updated else 1)

    if updated:
        machine.reset()

    if ((current_operation_mode == OPERATION_Mode["Low_Power"]) and
            tick_timer is None
            and power_pot.get_current_operation_state() == OPERATION_State["Idle"]):
        ota_ticks = power_pot.get_ota_time_ms()
        rtc_memory_util.save_to_rtc_memory({"ota_duration": ota_ticks})
        machine.deepsleep(config.get("checkCycleInterval", 3_600_000))
    else:
        machine.lightsleep(1000)
