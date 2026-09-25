import re
import socket
from collections import deque

import requests
import ujson

from src.lib.enum.log_type import LOG_Type


class ServerHandler:
    _LOG_PATHS = {
        0: "/systemLog",
        1: "/updateLog",
        2: "/wateringLog",
        3: "/sensorLog",
    }

    def __init__(self, machine_ip, machine_subnet, machine_mac_address,
                 server_ip=None, server_port=None,
                 max_queue=20, max_send_per_loop=1, timeout_ms=1000, max_retries=3):
        if machine_ip is None:
            raise Exception("[Server-Handler] MachineIp must not be None")
        if machine_subnet is None:
            raise Exception("[Server-Handler] MachineSubnet must not be None")
        if machine_mac_address is None:
            raise Exception("[Server-Handler] MacAddress must not be None")

        self.machine_mac_address = machine_mac_address
        self.machine_ip = machine_ip
        self.machine_subnet = machine_subnet

        self._server_ip = server_ip
        self._server_port = server_port

        self._queue : deque[tuple[str, str, int]] = deque((), max_queue)
        self._queue_max_length = max_queue
        self._max_send_per_loop = max_send_per_loop
        self._timeout = timeout_ms / 1000
        self._max_retries = max_retries

    def ping_server(self):
        if not self._server_ip or not self._server_port:
            print("[Server-Ping] ServerIp or ServerPort not set!")
            return False

        try:
            res = requests.get(f"http://{self._server_ip}:{self._server_port}/ping", timeout=self._timeout)
            return res.status_code == 200
        except Exception as e:
            print("[Server-Ping] Server not reachable: ", str(e))
            return False

    def discover_server(self):
        ip_parts = [int(part) for part in self.machine_ip.split('.')]
        subnet_parts = [int(part) for part in self.machine_subnet.split('.')]
        broadcast_parts = [(ip_parts[i] | (~subnet_parts[i] & 0xFF)) for i in range(4)]
        broadcast_ip = '.'.join(str(part) for part in broadcast_parts)

        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        udp_socket.settimeout(5)

        try:
            udp_socket.sendto("[search]" + self.machine_mac_address, (broadcast_ip, 22550))

            data, address = udp_socket.recvfrom(1024)
            data = data.decode("utf-8")

            regex = re.compile(r"\[(.*?)\](.*)")
            match = regex.search(data)
            if match and match.group(1) == "serverResponse":
                self._server_ip = address[0]
                self._server_port = int(match.group(2))
                print(f"[Discover-Server] Server found at: {self._server_ip}:{self._server_port}")
                return self._server_ip, self._server_port
        except Exception as e:
            print("[Discover-Server] Server not reachable: ", str(e))
        finally:
            udp_socket.close()

        return None

    def send_log(self, log_type, message=None, is_error=False, **appArgs):
        path = self._LOG_PATHS.get(log_type)
        if not path:
            print(f"[Send-Log] LogType unknown: {log_type}")
            return

        body = {
            "isError": is_error,
            "ipAddress": self.machine_ip,
            "mac": self.machine_mac_address
        }

        if log_type == LOG_Type["system"] or log_type == LOG_Type["update"]:
            body["message"] = message
        if log_type == LOG_Type["update"]:
            body["oldVersion"] = appArgs.get("old_version")
            body["newVersion"] = appArgs.get("new_version")
        elif log_type == LOG_Type["watering"]:
            body["moistureLevel"] = appArgs.get("moisture_level")
        elif log_type == LOG_Type["sensor"]:
            body["name"] = appArgs.get("name")
            body["value"] = appArgs.get("value")

        if len(self._queue) >= self._queue_max_length:
            if is_error:
                self._queue.popleft()
            else:
                print("[Send-Log] Queue full! Dropped Log")
                return

        self._queue.append((path, ujson.dumps(body), 0 if is_error else -1))

    def flush(self, max_send=None):
        if not self._server_ip or not self._server_port:
            print("[Flush] ServerIp or ServerPort not set!")
            return

        max_send = self._max_send_per_loop if max_send is None else max_send
        sent = 0
        while self._queue and sent < max_send:
            path, payload, retries = self._queue.popleft()

            try:
                res = requests.post(f"http://{self._server_ip}:{self._server_port}/{path.lstrip('/')}",
                                    data=payload,
                                    timeout=self._timeout,
                                    headers={"Content-Type": "application/json"})

                if res.status_code == 200 or res.status_code == 204:
                    continue
                if 400 <= res.status_code < 500:
                    print("[Flush] Server rejected log:", res.status_code)
                    continue

            except Exception as e:
                print("[Flush] Send failed: ", str(e))
            finally:
                sent += 1

            if 0 <= retries < self._max_retries:
                self._queue.append((path, payload, retries + 1))
