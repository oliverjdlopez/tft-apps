"""Exercise the real Python launcher with an in-memory, credential-free ASGI app."""

import asyncio
from pathlib import Path
import sys
import threading
from types import ModuleType, SimpleNamespace

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))
from desktop import backend


async def fixture_app(scope, receive, send):
    """Answer readiness and lifespan events without loading ChatTFT services.

    Args:
        scope: ASGI connection information.
        receive: Incoming ASGI event callable.
        send: Outgoing ASGI event callable.
    """
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                if "--stall" in sys.argv:
                    await asyncio.Event().wait()
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    else:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})


def fixture_config():
    """Return only the UI port read by the launcher, without .env or RDS access."""
    return SimpleNamespace(chat=SimpleNamespace(ui_port=int(sys.argv[1])))


config_module = ModuleType("core.config")
config_module.load_config = fixture_config
app_module = ModuleType("api.app")
app_module.app = fixture_app
sys.modules["core.config"] = config_module
sys.modules["api.app"] = app_module

shutdown = threading.Event()
stopped = threading.Event()
threading.Thread(
    target=backend.watch_parent, args=(sys.stdin, shutdown, stopped), daemon=True,
).start()
try:
    asyncio.run(backend.serve(None, shutdown))
finally:
    stopped.set()
