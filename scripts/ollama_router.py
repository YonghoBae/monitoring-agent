"""Internal non-streaming OpenAI chat router. Never executes agent tools itself."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import os
import re
import threading
import time
from urllib.parse import urlsplit

LOG = logging.getLogger("ollama-router")
MAX_BODY = 4 * 1024 * 1024


def error(message, kind="router_error"):
    return {"error": {"message": message, "type": kind}}


class BackendFailure(Exception):
    pass


class RequestBodyError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class Router:
    def __init__(self, primary_url, primary_model, fallback_url, fallback_model,
                 connect_timeout=2, primary_read_timeout=45, fallback_read_timeout=180,
                 cooldown=15, clock=time.monotonic):
        self.primary = (self.endpoint(primary_url), primary_model, primary_read_timeout)
        self.fallback = (self.endpoint(fallback_url), fallback_model, fallback_read_timeout)
        self.connect_timeout = connect_timeout
        self.cooldown = cooldown
        self.clock = clock
        self.primary_retry_at = 0
        self.counts = {"primary_success": 0, "fallback_success": 0, "unavailable": 0}
        self.lock = threading.Lock()

    @staticmethod
    def endpoint(url):
        value = urlsplit(url)
        if value.scheme not in ("http", "https") or not value.hostname or value.username or value.query or value.fragment:
            raise ValueError("Backend must be an HTTP(S) base URL without credentials/query/fragment")
        return value

    def status(self):
        with self.lock:
            return {"status": "ok", "primary_cooldown_seconds": round(max(0, self.primary_retry_at - self.clock()), 2),
                    "primary_model": self.primary[1], "fallback_model": self.fallback[1], **self.counts}

    @staticmethod
    def valid_message(message):
        if not isinstance(message, dict):
            return False
        content, calls = message.get("content"), message.get("tool_calls")
        if content is not None and not isinstance(content, str):
            return False
        if calls is not None:
            if not isinstance(calls, list):
                return False
            for call in calls:
                if not isinstance(call, dict) or call.get("type") != "function" or not isinstance(call.get("id"), str):
                    return False
                function = call.get("function")
                if not isinstance(function, dict) or not isinstance(function.get("name"), str) or not isinstance(function.get("arguments"), str):
                    return False
        return bool(content or calls)

    def request(self, backend, payload):
        endpoint, model, read_timeout = backend
        body = json.dumps({**payload, "model": model}, ensure_ascii=False).encode()
        connection_type = http.client.HTTPSConnection if endpoint.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(endpoint.hostname, endpoint.port, timeout=self.connect_timeout)
        try:
            connection.connect()
            connection.sock.settimeout(read_timeout)
            connection.request("POST", endpoint.path.rstrip("/") + "/v1/chat/completions", body,
                               {"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise BackendFailure("oversized_response")
            try:
                data = json.loads(raw)
            except (ValueError, UnicodeError):
                if response.status >= 400:
                    data = error("Backend HTTP " + str(response.status), "backend_error")
                else:
                    raise BackendFailure("invalid_json")
            if response.status in (404, 408, 429) or response.status >= 500:
                raise BackendFailure("http_" + str(response.status))
            if response.status == 200:
                choices = data.get("choices") if isinstance(data, dict) else None
                if not isinstance(choices, list) or not choices or not all(
                        isinstance(choice, dict) and self.valid_message(choice.get("message")) for choice in choices):
                    raise BackendFailure("invalid_completion")
            elif response.status < 400:
                raise BackendFailure("unexpected_http_" + str(response.status))
            return response.status, data
        finally:
            connection.close()

    def complete(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list) or not payload["messages"]:
            return 400, error("A non-empty messages array is required", "invalid_request_error")
        if payload.get("stream"):
            return 400, error("This internal router accepts non-streaming requests only", "invalid_request_error")
        with self.lock:
            try_primary = self.clock() >= self.primary_retry_at
        if try_primary:
            try:
                result = self.request(self.primary, payload)
                with self.lock:
                    self.primary_retry_at = 0
                    if result[0] == 200:
                        self.counts["primary_success"] += 1
                LOG.info("backend=primary model=%s status=%s", self.primary[1], result[0])
                return result
            except (OSError, http.client.HTTPException, BackendFailure) as exc:
                with self.lock:
                    self.primary_retry_at = self.clock() + self.cooldown
                reason = str(exc) if isinstance(exc, BackendFailure) else type(exc).__name__
                LOG.warning("backend=primary unavailable=%s fallback=local", reason)
        try:
            result = self.request(self.fallback, payload)
            with self.lock:
                if result[0] == 200:
                    self.counts["fallback_success"] += 1
            LOG.info("backend=fallback model=%s status=%s", self.fallback[1], result[0])
            return result
        except (OSError, http.client.HTTPException, BackendFailure) as exc:
            with self.lock:
                self.counts["unavailable"] += 1
            reason = str(exc) if isinstance(exc, BackendFailure) else type(exc).__name__
            LOG.error("backend=fallback unavailable=%s", reason)
            return 503, error("Both Ollama backends are unavailable", "service_unavailable")


def make_server(router, address=("0.0.0.0", 8081)):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_args):
            pass  # Routing logs contain no prompts, tool arguments or credentials.

        def reply(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                LOG.warning("client disconnected before response")

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, router.status())
            else:
                self.reply(404, error("Unknown endpoint"))

        def read_body(self):
            lengths = self.headers.get_all("Content-Length", [])
            encodings = self.headers.get_all("Transfer-Encoding", [])
            if len(lengths) > 1 or len(encodings) > 1 or (lengths and encodings):
                raise RequestBodyError(400, "Ambiguous request framing")
            if encodings:
                if encodings[0].strip().lower() != "chunked":
                    raise RequestBodyError(400, "Unsupported transfer encoding")
                result = bytearray()
                while True:
                    header = self.rfile.readline(128)
                    token = header[:-2].split(b";", 1)[0]
                    if not header.endswith(b"\r\n") or not re.fullmatch(rb"[0-9a-fA-F]+", token):
                        raise RequestBodyError(400, "Invalid chunk framing")
                    size = int(token, 16)
                    if len(result) + size > MAX_BODY:
                        raise RequestBodyError(413, "Request body exceeds 4 MiB")
                    if size == 0:
                        trailer_size = 0
                        while True:
                            trailer = self.rfile.readline(8193)
                            trailer_size += len(trailer)
                            if not trailer.endswith(b"\r\n") or trailer_size > 8192:
                                raise RequestBodyError(400, "Invalid chunk trailers")
                            if trailer == b"\r\n":
                                return bytes(result)
                    chunk = self.rfile.read(size)
                    if len(chunk) != size or self.rfile.read(2) != b"\r\n":
                        raise RequestBodyError(400, "Incomplete chunk")
                    result.extend(chunk)
            if not lengths:
                raise RequestBodyError(411, "Content-Length or chunked encoding required")
            if not re.fullmatch(r"[0-9]+", lengths[0]):
                raise RequestBodyError(400, "Invalid Content-Length")
            size = int(lengths[0])
            if size > MAX_BODY:
                raise RequestBodyError(413, "Request body exceeds 4 MiB")
            if size == 0:
                raise RequestBodyError(400, "Request body is empty")
            body = self.rfile.read(size)
            if len(body) != size:
                raise RequestBodyError(400, "Incomplete request body")
            return body

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.reply(404, error("Unknown endpoint"))
                return
            try:
                payload = json.loads(self.read_body())
            except RequestBodyError as exc:
                self.close_connection = True
                LOG.warning("request_rejected status=%d reason=%s", exc.status, str(exc))
                self.reply(exc.status, error(str(exc), "invalid_request_error"))
                return
            except TimeoutError:
                self.close_connection = True
                LOG.warning("request_rejected status=408 reason=body_read_timeout")
                self.reply(408, error("Request body timed out", "invalid_request_error"))
                return
            except (ValueError, UnicodeError):
                self.reply(400, error("Invalid JSON", "invalid_request_error"))
                return
            self.reply(*router.complete(payload))

    return ThreadingHTTPServer(address, Handler)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    router = Router(
        os.environ.get("PRIMARY_OLLAMA_URL", "http://127.0.0.1:11434"),
        os.environ.get("PRIMARY_OLLAMA_MODEL", "qwen3:8b"),
        os.environ.get("FALLBACK_OLLAMA_URL", "http://ollama:11434"),
        os.environ.get("FALLBACK_OLLAMA_MODEL", "qwen3.5:4b"),
        connect_timeout=float(os.environ.get("CONNECT_TIMEOUT_SECONDS", "2")),
        primary_read_timeout=float(os.environ.get("PRIMARY_READ_TIMEOUT_SECONDS", "45")),
        fallback_read_timeout=float(os.environ.get("FALLBACK_READ_TIMEOUT_SECONDS", "180")),
        cooldown=float(os.environ.get("PRIMARY_COOLDOWN_SECONDS", "15")),
    )
    LOG.info("started primary_model=%s fallback_model=%s", router.primary[1], router.fallback[1])
    make_server(router).serve_forever()
