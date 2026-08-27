"""Shared HTTP and cryptographic helpers for ZiderVision adapters."""
import base64
from urllib.parse import urlencode
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0 (Kodi; ZiderVision URL Resolver)"
BASE_URL = "https://napifilm.hu"

def fetch(url, timeout=15):
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    with urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")

def post_bytes(url, form_data, headers=None, timeout=15):
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    req = Request(url, data=urlencode(form_data).encode("utf-8"), headers=request_headers, method="POST")
    with urlopen(req, timeout=timeout) as response:
        return response.read(), dict(response.headers.items())

def fetch_bytes(url, headers=None, timeout=15):
    request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        request_headers.update(headers)
    req = Request(url, headers=request_headers)
    with urlopen(req, timeout=timeout) as response:
        return response.read(), dict(response.headers.items())

def rc4_decrypt(data, key):
    data = base64.b64decode(data)
    key_bytes = key.encode("utf-8")
    state = list(range(256)); j = 0
    for i in range(256):
        j = (j + state[i] + key_bytes[i % len(key_bytes)]) % 256
        state[i], state[j] = state[j], state[i]
    i = j = 0; output = bytearray()
    for value in data:
        i = (i + 1) % 256; j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        output.append(value ^ state[(state[i] + state[j]) % 256])
    return bytes(output)
