"""Client for the CasaOS / ZimaOS app management API (the one their own web UI uses to edit apps)."""
from __future__ import annotations

import asyncio
import json

import aiohttp

TIMEOUT = aiohttp.ClientTimeout(total=60)


class CasaOSError(Exception):
    """The server refused the request or answered with an error."""


class AuthError(CasaOSError):
    """Wrong username or password."""


def find_app(apps: dict, container: str) -> str | None:
    """The app id whose compose has a service with this container name (or the app id itself).

    Services without container_name get Docker's default name, <project>-<service>-1.
    """
    for app_id, info in apps.items():
        compose = (info or {}).get("compose") or {}
        project = compose.get("name") or app_id
        services = compose.get("services") or {}
        if app_id == container or any(
            container == ((svc or {}).get("container_name") or f"{project}-{name}-1") for name, svc in services.items()
        ):
            return app_id
    return None


class CasaOSClient:
    def __init__(self, session: aiohttp.ClientSession, host: str, username: str, password: str) -> None:
        self._session, self._base = session, f"http://{host}"
        self._username, self._password = username, password
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def login(self) -> None:
        async with self._session.post(f"{self._base}/v1/users/login", json={"username": self._username, "password": self._password},
                                      timeout=TIMEOUT) as resp:
            body = await resp.json(content_type=None)
        token = ((body or {}).get("data") or {}).get("token") or {}
        if resp.status != 200 or not token.get("access_token"):
            raise AuthError((body or {}).get("message") or f"HTTP {resp.status}")
        self._token = token["access_token"]

    async def _request(self, method: str, path: str, *, retry: bool = True, **kw) -> tuple[int, str]:
        async with self._lock:
            if not self._token:
                await self.login()
        headers = {"Authorization": self._token, **kw.pop("headers", {})}
        async with self._session.request(method, self._base + path, headers=headers, timeout=TIMEOUT, **kw) as resp:
            status, text = resp.status, await resp.text()
        if status == 401 and retry:  # token expired: log in again once
            self._token = None
            return await self._request(method, path, retry=False, headers={k: v for k, v in headers.items() if k != "Authorization"}, **kw)
        return status, text

    async def apps(self) -> dict:
        """{app id: compose app with store info} for every installed compose app."""
        status, text = await self._request("GET", "/v2/app_management/compose")
        if status != 200:
            raise CasaOSError(f"app list: HTTP {status} {text[:200]}")
        return json.loads(text).get("data") or {}

    async def compose_yaml(self, app_id: str) -> str:
        status, text = await self._request("GET", f"/v2/app_management/compose/{app_id}", headers={"Accept": "application/yaml"})
        if status != 200:
            raise CasaOSError(f"{app_id}: HTTP {status} {text[:200]}")
        return text

    async def apply(self, app_id: str, yaml_text: str, dry_run: bool) -> str:
        status, text = await self._request(
            "PUT", f"/v2/app_management/compose/{app_id}", data=yaml_text.encode(),
            params={"dry_run": "true" if dry_run else "false", "check_port_conflict": "true"},
            headers={"Content-Type": "application/yaml"},
        )
        if status != 200:
            raise CasaOSError(text.strip()[:1000] or f"HTTP {status}")
        return text
