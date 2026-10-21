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


def compose_from_inspect(info: dict, image_info: dict | None = None) -> dict:
    """A compose file equivalent to a container made with `docker run` (settings the image already sets are left out)."""
    cfg, host = info.get("Config") or {}, info.get("HostConfig") or {}
    img = (image_info or {}).get("Config") or {}
    name = (info.get("Name") or "").lstrip("/")
    svc: dict = {"container_name": name, "image": cfg.get("Image")}
    restart = (host.get("RestartPolicy") or {}).get("Name") or "no"
    svc["restart"] = restart
    mode = host.get("NetworkMode") or "bridge"
    svc["network_mode"] = "bridge" if mode == "default" else mode
    ports = []
    for spec, binds in (host.get("PortBindings") or {}).items():
        target, _, proto = spec.partition("/")
        for b in binds or [{}]:
            ports.append({"target": int(target), "published": str(b.get("HostPort") or ""), "protocol": proto or "tcp"})
    if ports:
        svc["ports"] = ports
    mounts = [{"type": m.get("Type", "bind"), "source": m.get("Name") if m.get("Type") == "volume" else m.get("Source"),
               "target": m.get("Destination"), **({} if m.get("RW", True) else {"read_only": True})} for m in info.get("Mounts") or []]
    if mounts:
        svc["volumes"] = mounts
    base = set(img.get("Env") or [])
    env = dict(e.split("=", 1) if "=" in e else (e, "") for e in cfg.get("Env") or [] if e not in base)
    if env:
        svc["environment"] = env
    devices = [f"{d['PathOnHost']}:{d['PathInContainer']}" for d in host.get("Devices") or []]
    if devices:
        svc["devices"] = devices
    if host.get("CpuShares"):
        svc["cpu_shares"] = host["CpuShares"]
    if host.get("Memory"):
        svc["deploy"] = {"resources": {"limits": {"memory": str(host["Memory"])}}}
    if host.get("Privileged"):
        svc["privileged"] = True
    if host.get("CapAdd"):
        svc["cap_add"] = host["CapAdd"]
    if cfg.get("Cmd") and cfg.get("Cmd") != img.get("Cmd"):
        svc["command"] = cfg["Cmd"]
    if cfg.get("Entrypoint") and cfg.get("Entrypoint") != img.get("Entrypoint"):
        svc["entrypoint"] = cfg["Entrypoint"]
    if cfg.get("User") and cfg.get("User") != img.get("User"):
        svc["user"] = cfg["User"]
    if host.get("PidMode"):
        svc["pid"] = host["PidMode"]
    if host.get("IpcMode") not in (None, "", "private", "shareable"):
        svc["ipc"] = host["IpcMode"]
    for key, out in (("SecurityOpt", "security_opt"), ("ExtraHosts", "extra_hosts"), ("CapDrop", "cap_drop"), ("DNS", "dns")):
        if host.get(key):
            svc[out] = host[key]
    if host.get("Tmpfs"):
        svc["tmpfs"] = [f"{k}:{v}" if v else k for k, v in host["Tmpfs"].items()]
    if host.get("Sysctls"):
        svc["sysctls"] = host["Sysctls"]
    if host.get("Init"):
        svc["init"] = True
    labels = {k: v for k, v in (cfg.get("Labels") or {}).items() if (img.get("Labels") or {}).get(k) != v}
    if labels:
        svc["labels"] = labels
    out: dict = {"name": name, "services": {name: svc}}
    volumes = {m["source"]: {"external": True} for m in mounts if m["type"] == "volume"}
    if volumes:  # existing Docker volumes (named or anonymous) are reused as they are, data included
        out["volumes"] = volumes
    if mode not in ("default", "bridge", "host", "none") and not mode.startswith(("container:", "service:")):
        svc.pop("network_mode")  # a user-defined network: join it as an existing (external) network
        svc["networks"] = [mode]
        out["networks"] = {mode: {"external": True}}
    return out


class PortainerClient:
    """Read-only container settings through Portainer (for containers CasaOS doesn't manage)."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self._session, self._url, self._headers = session, url.rstrip("/"), {"X-API-Key": token}

    async def _get(self, path: str):
        async with self._session.get(self._url + path, headers=self._headers, timeout=TIMEOUT, ssl=False) as resp:
            if resp.status != 200:
                raise CasaOSError(f"Portainer {path}: HTTP {resp.status}")
            return await resp.json(content_type=None)

    async def compose(self, container: str) -> dict:
        endpoints = await self._get("/api/endpoints")
        if not endpoints:
            raise CasaOSError("Portainer has no Docker environment")
        base = f"/api/endpoints/{endpoints[0]['Id']}/docker"
        info = await self._get(f"{base}/containers/{container}/json")
        try:
            image = await self._get(f"{base}/images/{info['Image']}/json")
        except CasaOSError:
            image = None
        return compose_from_inspect(info, image)
