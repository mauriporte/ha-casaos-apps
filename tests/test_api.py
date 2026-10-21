"""Tests for custom_components/casaos_apps/api.py (no Home Assistant needed). Run: python -m pytest tests"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components", "casaos_apps"))
import api  # noqa: E402

APPS = {
    "linuxserver-jellyfin": {"compose": {"services": {"app": {"container_name": "jellyfin"}}}},
    "big-bear-immich": {"compose": {"services": {"server": {"container_name": "immich-server"}, "db": {"container_name": "immich-db"}}}},
    "jellyseerr": {"compose": {"name": "jellyseerr", "services": {"jellyseerr": {}}}},
    "broken": None,
}


def test_find_app_by_container_or_id():
    assert api.find_app(APPS, "jellyfin") == "linuxserver-jellyfin"
    assert api.find_app(APPS, "immich-db") == "big-bear-immich"  # any service of a multi-container app
    assert api.find_app(APPS, "big-bear-immich") == "big-bear-immich"
    assert api.find_app(APPS, "jellyseerr-jellyseerr-1") == "jellyseerr"  # no container_name: Docker's default name
    assert api.find_app(APPS, "portainer") is None  # not a CasaOS app


def test_expired_token_logs_in_again_once():
    class Resp:
        def __init__(self, status, text):
            self.status, self._text = status, text
        async def text(self):
            return self._text
        async def json(self, content_type=None):
            import json
            return json.loads(self._text)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False

    class Session:
        def __init__(self):
            self.logins, self.auth = 0, []
        def post(self, url, **kw):
            self.logins += 1
            return Resp(200, '{"data": {"token": {"access_token": "t%d"}}}' % self.logins)
        def request(self, method, url, headers=None, **kw):
            self.auth.append(headers["Authorization"])
            return Resp(401 if len(self.auth) == 1 else 200, '{"data": {}}')

    s = Session()
    client = api.CasaOSClient(s, "192.0.2.1", "u", "p")
    assert asyncio.run(client.apps()) == {}
    assert s.logins == 2 and s.auth == ["t1", "t2"]


def test_compose_from_docker_run_container():
    info = {
        "Name": "/stremio-web",
        "Config": {"Image": "stremio/web:latest", "Env": ["PATH=/usr/bin", "TOKEN=x"], "Cmd": ["serve"]},
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}, "NetworkMode": "default",
                       "PortBindings": {"8080/tcp": [{"HostPort": "8082"}]}, "Memory": 0,
                       "Devices": [{"PathOnHost": "/dev/dri", "PathInContainer": "/dev/dri"}]},
        "Mounts": [{"Type": "bind", "Source": "/data/x", "Destination": "/x", "RW": False}],
    }
    image = {"Config": {"Env": ["PATH=/usr/bin"], "Cmd": ["serve"]}}
    svc = api.compose_from_inspect(info, image)["services"]["stremio-web"]
    assert svc == {"container_name": "stremio-web", "image": "stremio/web:latest", "restart": "unless-stopped", "network_mode": "bridge",
                   "ports": [{"target": 8080, "published": "8082", "protocol": "tcp"}],
                   "volumes": [{"type": "bind", "source": "/data/x", "target": "/x", "read_only": True}],
                   "environment": {"TOKEN": "x"}, "devices": ["/dev/dri:/dev/dri"]}  # image defaults (PATH, Cmd) left out
