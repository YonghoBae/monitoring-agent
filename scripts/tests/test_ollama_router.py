import contextlib
import importlib.util
import json
import http.client
from pathlib import Path
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@contextlib.contextmanager
def backend(actions):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            action = actions[min(len(requests) - 1, len(actions) - 1)]
            if action == "disconnect":
                self.close_connection = True
                return
            if isinstance(action, tuple) and action[0] == "delay":
                time.sleep(action[1])
                action = (200, {"choices": [{"message": {"role": "assistant", "content": "late"}}]})
            status, data = action
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def success(text):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}}]}


@contextlib.contextmanager
def router_server(module, router):
    server = module.make_server(router, ("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class OllamaRouterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1] / "ollama_router.py"
        spec = importlib.util.spec_from_file_location("ollama_router", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def router(self, primary, fallback, **kwargs):
        return self.module.Router(primary, "remote-model", fallback, "local-model", **kwargs)

    def payload(self):
        return {"model": "client-model", "messages": [{"role": "user", "content": "check"}], "stream": False}

    def test_primary_is_used_and_local_is_untouched(self):
        with backend([success("remote")]) as (p, pr), backend([success("local")]) as (f, fr):
            status, data = self.router(p, f).complete(self.payload())
            self.assertEqual((status, data["choices"][0]["message"]["content"]), (200, "remote"))
            self.assertEqual(pr[0]["model"], "remote-model")
            self.assertEqual(fr, [])

    def test_disconnected_primary_uses_local(self):
        with backend(["disconnect"]) as (p, _), backend([success("local")]) as (f, fr):
            status, data = self.router(p, f).complete(self.payload())
            self.assertEqual((status, data["choices"][0]["message"]["content"]), (200, "local"))
            self.assertEqual(fr[0]["model"], "local-model")

    def test_server_failure_cooldown_then_primary_recovery(self):
        clock = [100.0]
        with backend([(503, {"error": "offline"}), success("recovered")]) as (p, pr), backend([success("local")]) as (f, fr):
            router = self.router(p, f, clock=lambda: clock[0], cooldown=15)
            router.complete(self.payload())
            router.complete(self.payload())
            self.assertEqual((len(pr), len(fr)), (1, 2))
            clock[0] += 16
            status, data = router.complete(self.payload())
            self.assertEqual((status, data["choices"][0]["message"]["content"]), (200, "recovered"))
            self.assertEqual((len(pr), len(fr)), (2, 2))

    def test_bad_request_is_returned_without_fallback(self):
        with backend([(400, {"error": "invalid input"})]) as (p, _), backend([success("local")]) as (f, fr):
            status, _ = self.router(p, f).complete(self.payload())
            self.assertEqual(status, 400)
            self.assertEqual(fr, [])

    def test_read_timeout_uses_local(self):
        with backend([("delay", 0.15)]) as (p, _), backend([success("local")]) as (f, _):
            status, data = self.router(p, f, primary_read_timeout=0.03).complete(self.payload())
            self.assertEqual((status, data["choices"][0]["message"]["content"]), (200, "local"))

    def test_both_backends_failed_returns_service_unavailable(self):
        with backend(["disconnect"]) as (p, _), backend([(503, {"error": "secret backend detail"})]) as (f, _):
            status, data = self.router(p, f).complete(self.payload())
            self.assertEqual(status, 503)
            self.assertNotIn("secret", json.dumps(data))

    def test_tool_messages_and_tool_calls_are_preserved_on_fallback(self):
        tool_calls = [{"id": "call_1", "type": "function", "function": {"name": "get_status", "arguments": "{}"}}]
        response = {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": tool_calls}}]}
        payload = self.payload()
        payload["messages"].extend([{"role": "assistant", "tool_calls": tool_calls},
                                    {"role": "tool", "tool_call_id": "call_1", "content": "already executed"}])
        payload["tools"] = [{"type": "function", "function": {"name": "get_status", "parameters": {"type": "object"}}}]
        with backend(["disconnect"]) as (p, _), backend([(200, response)]) as (f, fr):
            _, data = self.router(p, f).complete(payload)
            self.assertEqual(data, response)
            self.assertEqual(fr[0]["messages"], payload["messages"])
            self.assertEqual(fr[0]["tools"], payload["tools"])
            self.assertEqual(payload["model"], "client-model")

    def test_streaming_is_rejected_before_backend_call(self):
        with backend([success("remote")]) as (p, pr), backend([success("local")]) as (f, fr):
            status, _ = self.router(p, f).complete({**self.payload(), "stream": True})
            self.assertEqual(status, 400)
            self.assertEqual((pr, fr), ([], []))

    def test_malformed_success_uses_local(self):
        with backend([(200, {"error": "no completion"})]) as (p, _), backend([success("local")]) as (f, _):
            status, data = self.router(p, f).complete(self.payload())
            self.assertEqual((status, data["choices"][0]["message"]["content"]), (200, "local"))

    def test_malformed_content_and_tool_types_use_local(self):
        for message in [{"content": {"unexpected": True}}, {"content": None, "tool_calls": "broken"},
                        {"content": None, "tool_calls": [{"type": "function", "function": {"name": "check", "arguments": {}}}]}]:
            with self.subTest(message=message), backend([(200, {"choices": [{"message": message}]})]) as (p, _), backend([success("local")]) as (f, _):
                status, data = self.router(p, f).complete(self.payload())
                self.assertEqual(status, 200)
                self.assertEqual(data["choices"][0]["message"]["content"], "local")

    def test_chunked_http_request_without_content_length_is_accepted(self):
        payload = self.payload()
        payload["messages"][0]["content"] = "청크 전송 테스트"
        raw = json.dumps(payload, ensure_ascii=False).encode()
        with backend([success("remote")]) as (p, pr), backend([success("local")]) as (f, _), \
                router_server(self.module, self.router(p, f)) as port:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                conn.request("POST", "/v1/chat/completions", iter([raw[:17], raw[17:]]),
                             {"Content-Type": "application/json"}, encode_chunked=True)
                response = conn.getresponse()
                body = json.loads(response.read())
                self.assertEqual(response.status, 200, body)
                self.assertEqual(pr[0]["messages"], payload["messages"])
            finally:
                conn.close()

    def test_oversized_chunk_is_rejected_without_forwarding(self):
        with backend([success("remote")]) as (p, pr), backend([success("local")]) as (f, fr), \
                router_server(self.module, self.router(p, f)) as port:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                conn.request("POST", "/v1/chat/completions", b"400001\r\n", {"Transfer-Encoding": "chunked"})
                response = conn.getresponse()
                response.read()
                self.assertEqual(response.status, 413)
                self.assertEqual((pr, fr), ([], []))
            finally:
                conn.close()

    def test_ambiguous_content_length_and_chunked_is_rejected(self):
        with backend([success("remote")]) as (p, pr), backend([success("local")]) as (f, _), \
                router_server(self.module, self.router(p, f)) as port:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                conn.request("POST", "/v1/chat/completions", b"0\r\n\r\n",
                             {"Transfer-Encoding": "chunked", "Content-Length": "5"})
                response = conn.getresponse()
                response.read()
                self.assertEqual(response.status, 400)
                self.assertEqual(pr, [])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
