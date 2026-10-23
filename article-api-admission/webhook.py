"""Minimal isolated AdmissionReview fixture, not a production webhook implementation."""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import ssl
import threading


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"]))) ["request"]
        obj = req["object"]
        path = self.path.split("?", 1)[0]
        print(json.dumps({"path": path, "name": obj["metadata"]["name"], "uid": req["uid"]}), flush=True)
        response = {"uid": req["uid"], "allowed": True}
        if path == "/mutate":
            annotations = dict(obj["metadata"].get("annotations", {}))
            annotations["article.example/mutated"] = "yes"
            patch = [{"op": "add", "path": "/metadata/annotations", "value": annotations}]
            response.update(patchType="JSONPatch", patch=base64.b64encode(json.dumps(patch).encode()).decode())
        elif obj.get("data", {}).get("deny") == "true":
            response.update(allowed=False, status={"code": 403, "message": "article policy denied this ConfigMap"})
        elif obj["metadata"]["name"].startswith("timeout"):
            # Simulate a dependency slower than the configured one-second deadline.
            threading.Event().wait(3)
        body = json.dumps({"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview", "response": response}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ssl.SSLError, ConnectionResetError):
            pass  # A timed-out API server request closes its connection.


server = ThreadingHTTPServer(("0.0.0.0", 19443), Handler)
server.daemon_threads = True
tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
tls.load_cert_chain("/tls/server.crt", "/tls/server.key")
server.socket = tls.wrap_socket(server.socket, server_side=True)
server.serve_forever()
