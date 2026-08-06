"""Small HTTP boundary shared by Graph calls and OAuth token calls."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class HttpResponseTooLarge(Exception):
    """The response exceeded the transport's configured byte limit."""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    """HTTP response with bytes kept out of normalized error objects."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes = b""


class HttpTransport(Protocol):
    """Injectable HTTP transport for deterministic Graph and auth tests."""

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        """Execute one request without applying Graph retry policy."""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent authenticated Graph requests from leaving the approved host."""

    def redirect_request(self, *args, **kwargs):
        return None


class UrllibHttpTransport:
    """Standard-library HTTPS transport; retries remain in ``GraphClient``."""

    def __init__(
        self,
        max_response_bytes: int = 8 * 1024 * 1024,
        *,
        opener=None,
    ) -> None:
        if not isinstance(max_response_bytes, int) or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be positive")
        self._max_response_bytes = max_response_bytes
        self._opener = opener or urllib.request.build_opener(_NoRedirectHandler())

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None = None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        request = urllib.request.Request(
            url,
            data=body,
            headers=dict(headers),
            method=method.upper(),
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is not None:
                    try:
                        if int(content_length) > self._max_response_bytes:
                            raise HttpResponseTooLarge
                    except ValueError:
                        pass
                body = response.read(self._max_response_bytes + 1)
                if len(body) > self._max_response_bytes:
                    raise HttpResponseTooLarge
                return HttpResponse(
                    response.status,
                    dict(response.headers.items()),
                    body,
                )
        except urllib.error.HTTPError as error:
            # HTTPError is a response, not a transport failure.  The client
            # normalizes its status and discards the provider body from errors.
            body = error.read(self._max_response_bytes + 1)
            if len(body) > self._max_response_bytes:
                raise HttpResponseTooLarge
            return HttpResponse(
                error.code,
                dict(error.headers.items()) if error.headers else {},
                body,
            )
        except HttpResponseTooLarge:
            raise
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as error:
            raise ConnectionError("Graph HTTP transport unavailable") from error
