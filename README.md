# PowerPot Firmware

MicroPython firmware for the PowerPot automatic watering system. Runs on ESP32 C3.

**PowerPot** is an automated plant watering system that monitors soil moisture via a capacitive sensor, activates a pump when moisture drops below a configurable threshold and notifies the user when the water tank is near empty. The firmware handles the complete control loop: reading the ADC sensor, driving the pump via PWM, checking water tank level via a inductive switch, and managing WiFi connectivity for remote monitoring and OTA updates.

## Features
- Soil moisture monitoring
- Automatic irrigation
- Water tank level detection
- WiFi connectivity
- UDP server discovery + HTTP log posting
- Local REST API (port 80)
- OTA firmware updates with CRC-32 verification

## Hardware Pin Mapping
| Function          | Pin    | Notes                      |
|-------------------|--------|----------------------------|
| Soil moisture ADC | GPIO 0 | ADC1_CH0, 11dB attenuation |
| Pump PWM forward  | GPIO 3 | PWM 100Hz, duty 0-1023     |
| Tank min level    | GPIO 5 | Input with pull-down       |
| Status LED        | GPIO 8 | Output                     |

## Build
```bash
python build.py
```
- Reads version from `config.json` => `ota.version`
- Merges `src/` modules in `MERGE_ORDER` into `dist/main.py`
- Adds magic header: `# PowerPotFirmware <version> crc32=XXXXXXXX`
- CRC-32 covers everything after header line

Output: `dist/main.py` - single-file firmware for device.

## Configuration
```json
{
  "checkCycleInterval": 3600000,         // Moisture check interval (ms)
  "serverIp": "",                        // Backend IP (auto-discovered if empty)
  "serverPort": "",                      // Backend port (auto-discovered if empty)
  "mode": 0,                             // Operation mode (see below)
  "wifi": { 
    "ssid": "", 
    "password": ""
  },
  "watering": {
    "minLevel": 45,                      // Moisture threshold (%)
    "wateringDuration": 10000,           // Pump run time (ms)
    "pumpPower": 100                     // Pump PWM duty (%)
  },
  "ota": {
    "checkCycleInterval": 43200000,      // OTA check interval (ms)
    "version": "0.2.0",                  // Current firmware version
    "basePath": "",                      // OTA server base URL
    "versionEndpoint": "/embedded/currentVersion/PowerPot",
    "updateEndpoint": "/embedded/firmware/PowerPot"
  }
}
```

## Deploy
Copy `dist/main.py` to device via serial (ampy, rshell, Thonny) or OTA.

## Local REST API (Port 80)
| Endpoint            | Method | Response                                       |
|---------------------|--------|------------------------------------------------|
| `/api/tankLevel`    | GET    | `{"message": 0\|1}`                            |
| `/api/opState`      | GET    | `{"message": 0-3}` (see OperationState)        |
| `/api/updateConfig` | PUT    | `{"message": "TODO!!!"}` - **not implemented** |

CORS enabled (`Access-Control-Allow-Origin: *`).

## Operation Modes
| Value | Name             | Behavior                                            |
|-------|------------------|-----------------------------------------------------|
| 0     | Unknown          | Initial, transitions after WiFi/server check        |
| 1     | Standalone       | defautl operaton, no server connection              |
| 2     | Client           | default operation                                   |
| 3     | Low_Power_Client | Planned - periodic wake, deep sleep with server     |
| 4     | IOT              | Planned - periodic wake, deep sleep, without server |

Mode persists in `config.json` => `mode`.

## State Machine
```
Idle => MoistureCheck => PumpRunning => PumpStopRequested => Idle
```
- **Idle**: Waiting for `checkCycleInterval` timer
- **MoistureCheck**: Reads ADC, decides watering
- **PumpRunning**: Pump on for `wateringDuration`
- **PumpStopRequested**: Pump off, returns to Idle

Driven by `TICK_DURATION = 100ms` timer interrupt.

## Server Discovery (UDP)
1. Device calculates broadcast IP from its IP + subnet
2. Sends `[search]<MAC>` to broadcast:22550
3. Server replies `[serverResponse]<port>` from its IP
4. Device stores `serverIp`/`serverPort` in config

## OTA Update Flow
1. `check_firmware_version()`: GET `basePath + versionEndpoint` → returns version string
2. Compares via semantic version (major.minor.patch)
3. `update_firmware()`: GET `basePath + updateEndpoint` → returns full firmware file
4. Verifies:
   - Header starts with `# PowerPotFirmware`
   - CRC-32 matches `crc32=` in header
   - Ends with `# EndPowerPotFirmware`
5. Writes to `main.py`, updates `config.json` version, reboots

## Development

### Prerequisites
- MicroPython on ESP32 (v1.19+ recommended)
- `micropython-requests` library
- Python 3 on host for build script

### Debugging
- Serial REPL at 115200 baud
- `print()` statements output to serial
- `machine.reset()` on OTA success
- Logs posted to server via HTTP (see `LOG_Type`)

### Project Structure
```
src/
  main.py                 # Entry point, WiFi/server init, main loop
  lib/
    config_util.py        # load_config/save_config (ujson)
    powerpot_handler.py   # Core: ADC, PWM, state machine, timers
    ota_util.py           # Version check, OTA download, CRC verify
    server_handler.py     # UDP discover, HTTP log queue + flush
    rest_api_handler.py   # Non-blocking HTTP server (port 80)
    enum/
      operation_mode.py   # OPERATION_Mode constants
      operation_state.py  # OPERATION_State constants
      log_type.py         # LOG_Type constants
```

## Known TODOs
- [ ] DNS redirect on AP to config page
- [ ] Low power mode (light/deep sleep)
- [ ] Rest-Api Calls
- [ ] Web-Interface for Configuration
- [ ] Test suite

## License:
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details
