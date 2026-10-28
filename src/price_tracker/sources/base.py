import time
from urllib.parse import urlsplit

import httpx


class SourceError(RuntimeError):
    """A watch could not be checked this run (blocked, page changed, network). Other watches go on."""


class Fetcher:
    """HTTP client that waits between requests to the same host, to be polite and avoid bans."""

    def __init__(self, user_agent: str, delay_seconds: float = 1.5, timeout: float = 20.0,
                 client: httpx.Client | None = None):  # fmt: skip
        self.delay = delay_seconds
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "en,es;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
        )
        self._last: dict[str, float] = {}

    def get(self, url: str, **kwargs) -> httpx.Response:
        host = urlsplit(url).netloc
        wait = self.delay - (time.monotonic() - self._last.get(host, -1e9))
        if wait > 0:
            time.sleep(wait)
        try:
            response = self.client.get(url, **kwargs)
        except httpx.HTTPError as exc:
            raise SourceError(f"Could not reach {host}: {exc}") from exc
        finally:
            self._last[host] = time.monotonic()
        if response.status_code in (401, 403, 429):
            raise SourceError(f"{host} blocked the request (HTTP {response.status_code}).")
        if response.status_code >= 400:
            raise SourceError(f"{url} returned HTTP {response.status_code}.")
        return response
