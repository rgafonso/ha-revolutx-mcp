"""Standalone aiohttp server bound to a configurable port, for reaching this
integration directly on the local network without going through Home Assistant's
own webhook path (e.g. `http://<ha-ip>:<port>/private_<secret>`).

Runs inside Home Assistant's existing asyncio event loop via aiohttp's low-level
AppRunner/TCPSite API — started in async_setup_entry, stopped in
async_unload_entry. Binding failures (port already in use) are raised to the
caller rather than swallowed, since HACS gives no guarantee the configured port
is free.
"""
from __future__ import annotations

import logging

from aiohttp import web
from homeassistant.core import HomeAssistant

from .revolut_client import RevolutXClient
from .transport import handle_mcp_http

_LOGGER = logging.getLogger(__name__)


class DirectServer:
    """Owns the lifecycle of the standalone aiohttp server."""

    def __init__(self) -> None:
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def async_start(
        self,
        hass: HomeAssistant,
        port: int,
        path_secret: str,
        client: RevolutXClient,
        auth_mode: str,
        signing_key: bytes,
    ) -> None:
        async def _handler(request: web.Request) -> web.Response:
            return await handle_mcp_http(request, client, auth_mode, signing_key)

        app = web.Application()
        app.router.add_post(f"/{path_secret}", _handler)
        app.router.add_get(f"/{path_secret}/health", lambda _r: web.json_response({"status": "ok"}))

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "0.0.0.0", port)
        try:
            await self._site.start()
        except OSError:
            _LOGGER.error("Could not bind Revolut X MCP direct server to port %s", port)
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            raise
        _LOGGER.info("Revolut X MCP direct server listening on port %s at /%s", port, path_secret)

    async def async_stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
