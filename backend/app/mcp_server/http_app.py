"""HTTP entry point for hosting (Render, Azure, or any container host).

Serves the same MCP tools as the local stdio server, plus:
  GET /health  -> {"status": "ok"}   (no authentication; used by the host to check the service is alive)
  /mcp         -> MCP over Streamable HTTP, requires  Authorization: Bearer <shop key>

Shop keys come from the VARAVU_SHOP_KEYS environment variable, as "shopname:key" pairs separated by commas.
Keys are compared in constant time and are never logged.
"""
import hmac
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
from starlette.requests import Request  # noqa: E402
from starlette.responses import JSONResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

load_dotenv(ROOT / ".env")

from backend.app.mcp_server.context import current_shop  # noqa: E402
from backend.app.mcp_server.server import server  # noqa: E402

SHOP_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")  # also used as a file name, so no paths or spaces


def load_shop_keys(raw: str | None = None) -> dict[str, str]:
    """Parse 'shop1:key1,shop2:key2' into {shop: key}. Empty or malformed input is an error."""
    raw = os.getenv("VARAVU_SHOP_KEYS", "") if raw is None else raw
    keys = {}
    for pair in filter(None, (p.strip() for p in raw.split(","))):
        shop, sep, key = pair.partition(":")
        if not sep or not SHOP_NAME.match(shop) or shop == "local" or len(key) < 24:
            raise ValueError("VARAVU_SHOP_KEYS must look like 'shop1:<key of 24+ chars>,shop2:<key>'. "
                             "Shop names: lowercase letters, digits, - and _ only.")
        keys[shop] = key
    return keys


def shop_for_key(presented: str, keys: dict[str, str]) -> str | None:
    """Find the shop for a presented key, comparing every key so timing doesn't reveal which one matched."""
    match = None
    for shop, key in keys.items():
        if hmac.compare_digest(presented.encode(), key.encode()):
            match = shop
    return match


class ShopKeyMiddleware:
    """Pure ASGI middleware: rejects /mcp requests without a valid shop key, and records the shop."""

    def __init__(self, app, keys: dict[str, str]):
        self.app, self.keys = app, keys

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] == "/health":
            return await self.app(scope, receive, send)
        request = Request(scope)
        header = request.headers.get("authorization", "")
        shop = shop_for_key(header[7:], self.keys) if header.lower().startswith("bearer ") else None
        if shop is None:
            response = JSONResponse({"error": "missing or invalid API key"}, status_code=401)
            return await response(scope, receive, send)
        token = current_shop.set(shop)
        try:
            await self.app(scope, receive, send)
        finally:
            current_shop.reset(token)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


def allowed_hosts() -> list[str]:
    """Host names the server accepts (protects against DNS rebinding). Local names are always allowed.
    On Render, set VARAVU_ALLOWED_HOSTS=your-service.onrender.com"""
    extra = [h.strip() for h in os.getenv("VARAVU_ALLOWED_HOSTS", "").split(",") if h.strip()]
    return ["localhost:*", "127.0.0.1:*"] + extra


def create_app(keys: dict[str, str] | None = None, hosts: list[str] | None = None):
    keys = load_shop_keys() if keys is None else keys
    if not keys:
        raise RuntimeError("No shop keys configured. Set VARAVU_SHOP_KEYS before starting the HTTP server.")
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                         allowed_hosts=allowed_hosts() if hosts is None else hosts)
    app = server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True,
                                     transport_security=security)
    app.router.routes.append(Route("/health", health))
    app.add_middleware(ShopKeyMiddleware, keys=keys)
    return app


app = None  # created lazily by run() or by tests, so importing this module never needs keys


def run() -> None:
    import uvicorn
    from backend.app.mcp_server.server import startup
    global app
    startup()  # resume interrupted scans and make sure the search index is complete
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    run()
