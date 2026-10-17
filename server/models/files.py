"""Temporary Gemini media upload for requests exceeding inline limits."""
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .gemini import ProviderError


def _request(method, url, headers, data=None):
    try:
        with urlopen(Request(url, data=data, headers=headers, method=method), timeout=60) as response:
            body = response.read()
            return {k.lower(): v for k, v in response.headers.items()}, json.loads(body) if body else {}
    except HTTPError as error:
        raise ProviderError(f"Gemini file HTTP {error.code}", error.code == 429 or error.code >= 500) from None
    except (URLError, TimeoutError):
        raise ProviderError("Gemini file connection failed", retryable=True) from None


class GeminiFiles:
    def __init__(self, key, *, transport=_request):
        self.key, self.transport = key, transport

    def upload(self, data, mime_type):
        headers, _ = self.transport("POST", "https://generativelanguage.googleapis.com/upload/v1beta/files", {
            "x-goog-api-key": self.key, "Content-Type": "application/json",
            "X-Goog-Upload-Protocol": "resumable", "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(len(data)),
            "X-Goog-Upload-Header-Content-Type": mime_type,
        }, b'{"file":{"display_name":"private-journal-media"}}')
        upload_url = headers.get("x-goog-upload-url", "")
        parsed = urlparse(upload_url)
        if parsed.scheme != "https" or parsed.hostname != "generativelanguage.googleapis.com":
            raise ValueError("Invalid provider upload URL")
        _, raw = self.transport("POST", upload_url, {
            "Content-Type": mime_type, "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize",
        }, data)
        file = raw.get("file", {})
        self._name(file.get("name"))
        return file

    def _name(self, name):
        if not isinstance(name, str) or not re.fullmatch(r"files/[A-Za-z0-9_-]+", name):
            raise ValueError("Invalid provider file name")
        return name

    def wait(self, file):
        # Bounded provider processing wait. Worker must renew its lease independently.
        for _ in range(20):
            state = file.get("state")
            if state == "ACTIVE":
                if not isinstance(file.get("uri"), str):
                    raise ValueError("Missing provider file URI")
                return file
            if state != "PROCESSING":
                raise ValueError("Provider media processing failed")
            time.sleep(1)
            _, file = self.transport("GET", "https://generativelanguage.googleapis.com/v1beta/" + self._name(file["name"]),
                                     {"x-goog-api-key": self.key})
        raise ProviderError("Provider media processing timed out", retryable=True)

    def delete(self, file):
        self.transport("DELETE", "https://generativelanguage.googleapis.com/v1beta/" + self._name(file["name"]),
                       {"x-goog-api-key": self.key})
