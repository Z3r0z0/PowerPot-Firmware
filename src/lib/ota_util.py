import requests
import ubinascii

from src.lib import config_util
from src.lib.enum.log_type import LOG_Type

UPDATE_MAGIC = b"# PowerPotFirmware"
UPDATE_MAGIC_END = b"# EndPowerPotFirmware"


def check_firmware_version(config, server=None):
    try:
        ota_config = config.get("ota", {})
        base_path = str(ota_config.get("basePath"))
        version_path = str(ota_config.get("versionEndpoint"))

        res = requests.get(base_path + version_path, timeout=2)
        if res.status_code != 200:
            if server:
                server.send_log(LOG_Type["update"],
                                message="Could not retrieve version number from server. Status:" + str(res.status_code))
            print(
                "[CheckFirmwareVersion] Could not retrieve version number from server. Status:" + str(res.status_code))
            return False
        current_version = str(ota_config.get("version")).strip('"')
        version = str(res.text).strip('"')

        if server:
            server.send_log(LOG_Type["update"], "Checking firmware versions", old_version=current_version,
                            new_version=version)
        print(f"[CheckFirmwareVersion] Old Version: {current_version}, New Version: {version}")

        is_version_new = int(version_compare(version, current_version)) > 0
        return is_version_new
    except Exception as e:
        if server:
            server.send_log(LOG_Type["update"], "Error while checking version number:" + str(e), True)
        print("[CheckFirmwareVersion] Error while checking version number:" + str(e))
        return False


def update_firmware(config, server=None):
    try:
        ota_config = config.get("ota", {})
        base_path = str(ota_config.get("basePath"))

        version_res = requests.get(base_path + ota_config.get("versionEndpoint"), timeout=2)
        version = version_res.text.strip('"')

        res = requests.get(base_path + ota_config.get("updateEndpoint"), timeout=2)
        if res.status_code != 200:
            if server:
                server.send_log(LOG_Type["update"], message="Error while retrieving version number:" + str(version),
                                is_error=True)
            print("[FirmwareUpdate] Error while retrieving version number. Status: " + str(res.status_code))
            return False

        res_text = res.content

        current_version = ota_config.get("version")
        if server:
            server.send_log(LOG_Type["update"], "Updating Firmware", old_version=current_version, new_version=version)
        print(f"[FirmwareUpdate] Old Version: {current_version}; New Version: {version}")

        header, separator, payload = res_text.partition(b"\n")
        if not res_text.startswith(UPDATE_MAGIC) or not separator:
            if server:
                server.send_log(LOG_Type["update"], message="Error downloading Firmware: invalid header", is_error=True)
            print("[FirmwareUpdate] Invalid firmware header")
            return False

        try:
            expected_crc = int(header.rsplit(b"crc32=", 1)[1].decode(), 16)
        except (ValueError, IndexError):
            if server:
                server.send_log(LOG_Type["update"], message="Error downloading Firmware: missing CRC", is_error=True)
            print("[FirmwareUpdate] Missing CRC in firmware header")
            return False

        if ubinascii.crc32(payload) != expected_crc or not payload.rstrip().endswith(UPDATE_MAGIC_END):
            if server:
                server.send_log(LOG_Type["update"], message="Error downloading Firmware: integrity check failed",
                                is_error=True)
            print("[FirmwareUpdate] Firmware integrity check failed")
            return False

        with open("main.py", "w") as file:
            file.write(res_text.decode("utf-8"))

        config["ota"]["version"] = str(version)
        config_util.save_config(config)

        if server:
            server.send_log(LOG_Type["update"], message="Firmware updated successfully! Rebooting now!",
                            old_version=current_version,
                            new_version=version)
        print("[FirmwareUpdate] Firmware updated successfully!")

        return True
    except Exception as e:
        if server:
            server.send_log(LOG_Type["update"], message="Update failed: " + str(e), is_error=True)
        print("[FirmwareUpdate] Error while updating Firmware: " + str(e))
    return False


def version_compare(v1, v2):
    arr1 = v1.split(".")
    arr2 = v2.split(".")

    num_arr1 = [int(i) for i in arr1]
    num_arr2 = [int(i) for i in arr2]
    n = len(num_arr1)
    m = len(num_arr2)

    # padding version numbers
    if n > m:
        for i in range(m, n):
            num_arr2.append(0)
    elif m > n:
        for i in range(n, m):
            num_arr1.append(0)

    for i in range(len(num_arr1)):
        if num_arr1[i] > num_arr2[i]:
            return 1
        elif num_arr2[i] > num_arr1[i]:
            return -1
    return 0
