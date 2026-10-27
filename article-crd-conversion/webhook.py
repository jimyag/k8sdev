"""把 Widget 的 v1alpha1.label 与 v1beta1.displayName 互相转换。"""

import json
import os
import ssl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit


def convert_object(obj, desired):
    converted = {
        "apiVersion": desired,
        "kind": obj.get("kind", "Widget"),
        "metadata": obj.get("metadata", {}),
    }
    spec = obj.get("spec", {})
    if desired.endswith("/v1beta1"):
        converted["spec"] = {
            "displayName": spec.get("displayName", spec.get("label", "")),
            "replicas": spec.get("replicas", 1),
        }
    else:
        converted["spec"] = {
            "label": spec.get("label", spec.get("displayName", "")),
            "replicas": spec.get("replicas", 1),
        }
    if "status" in obj:
        converted["status"] = obj["status"]
    return converted


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if urlsplit(self.path).path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path != "/convert":
            self.send_error(404)
            return
        length = int(self.headers.get("content-length", "0"))
        review = json.loads(self.rfile.read(length))
        request = review.get("request", {})
        response = {"uid": request.get("uid")}
        try:
            desired = request["desiredAPIVersion"]
            response["convertedObjects"] = [
                convert_object(obj, desired) for obj in request.get("objects", [])
            ]
            response["result"] = {"status": "Success"}
        except Exception as error:
            response["result"] = {"status": "Failure", "message": str(error)}
        body = json.dumps(
            {
                "apiVersion": "apiextensions.k8s.io/v1",
                "kind": "ConversionReview",
                "response": response,
            }
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


server = ThreadingHTTPServer(("0.0.0.0", 8443), Handler)
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.load_cert_chain(
    "/tls/tls.crt",
    "/tls/tls.key",
)
server.socket = context.wrap_socket(server.socket, server_side=True)
server.serve_forever()
