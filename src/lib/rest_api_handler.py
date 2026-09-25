import gc
import select
import socket

import ujson

from src.lib.enum.log_type import LOG_Type


class RestApiHandler:
    def __init__(self, powerpot_handler, server_handler=None):
        self.powerpot = powerpot_handler
        self.server = server_handler

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.bind(socket.getaddrinfo("0.0.0.0", 80)[0][-1])
        self._socket.listen(8)
        self._socket.setblocking(False)

    def run(self):
        ready, _, _ = select.select([self._socket], [], [], 0.001)
        for ready_socket in ready:
            client, remove_data = ready_socket.accept()
            client.setblocking(True)
            client.settimeout(0.1)
            try:
                raw_data = client.recv(1024)
                request = raw_data.decode("utf-8")

                if not request:
                    continue

                lines = request.split("\r\n")
                method, path, _ = lines[0].split()
                print(f"[API] {method}: {path}")

                headers = {}
                body_start = False
                body = None
                for line in lines[1:]:
                    if body_start:
                        body = line
                        break
                    elif line == "":
                        body_start = True
                    elif ": " in line:
                        key, value = line.split(": ", )
                        headers[key] = value

                content_type = headers.get("Content-Type", None)
                if content_type and content_type != "application/json":
                    if self.server:
                        self.server.send_log(LOG_Type["system"], f"{content_type} not supported!", True)
                    print(f"[API] Content-Type not supported: {content_type}")
                    continue

                status, response_body, response_content = self.handle_request(method, path, body)
                response_str = ujson.dumps(response_body) if isinstance(response_body, dict) else str(response_body)

                response = (
                    f"HTTP/1.1 {status if status else 500} {"OK" if status == 200 else "ERROR"}\r\n"
                    f"Content-Type: {response_content}\r\n"
                    "Access-Control-Allow-Origin: *\r\n"
                    "Connection: close\r\n"
                    "\r\n"
                    f"{response_str}"
                )
                client.send(response.encode("utf-8"))
            except Exception as e:
                if self.server:
                    self.server.send_log(LOG_Type["system"], str(e), True)
                print(f"[API] Error: {e}")
            finally:
                client.close()
                gc.collect()

    def handle_request(self, method, path, body):
        try:
            if method == "GET":
                if path == "/api/tankLevel":
                    return 200, {"message": self.powerpot.get_tank_level()}, "application/json"
                if path == "/api/opState":
                    return 200, {"message": self.powerpot.get_current_operation_state()}, "application/json"
            elif method == "PUT":
                if path == "/api/updateConfig":
                    data = ujson.loads(body)
                    print(f"[API] Received body: {data}")
                    return 200, {"message": "TODO!!!"}, "application/json"
            else:
                return 405, {"message": "Method Not Allowed"}, "application/json"
            return 404, {"message": "Not Found"}, "application/json"
        except Exception as e:
            print(f"[API] Error: {e}")
            return 500, {"message": f"An error occurred: {str(e)}"}, "application/json"
