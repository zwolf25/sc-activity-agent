"""First run of the desktop app: the data folder has no environment yet. Serve one page that asks Production or SB2,
then step aside so the real console can take the same port. The choice is locked afterwards, as with `agent init`."""
import os
import threading
import time

import uvicorn
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SC Activity Agent</title><style>
body{font:15px system-ui,sans-serif;max-width:560px;margin:12vh auto;padding:0 20px;color:#1b2230}
h1{font-size:22px}button{font:inherit;padding:10px 16px;border-radius:6px;border:1px solid #1f5fd6;background:#1f5fd6;color:#fff;cursor:pointer;margin-right:8px}
button.alt{background:#fff;color:#1f5fd6}p{color:#5d6678}
@media(prefers-color-scheme:dark){body{background:#12161e;color:#e6eaf2}p{color:#9aa5ba}button.alt{background:#12161e;color:#6b9bff;border-color:#6b9bff}}
</style></head><body><div id="welcome">%s</div>%s</body></html>"""

CHOOSE = """<h1>Welcome to SC Activity Agent</h1>
<p>Which ServiceChannel environment will this copy work in? You cannot change it later. To use the other environment, install a second copy with its own data folder.</p>
<form method="post" action="/choose"><button name="env" value="prod">Production</button><button class="alt" name="env" value="sb2">SB2 (test)</button></form>"""

WAIT = """<h1>Starting…</h1><p>The console opens in a moment.</p>"""
POLL = """<script>setInterval(()=>fetch('/').then(r=>r.text()).then(t=>{if(!t.includes('id="welcome"'))location.href='/'}).catch(()=>{}),1000)</script>"""


def wait_for_env(store, port=8080):
    """Block until the user picks an environment on the welcome page. Returns the chosen env."""
    app = FastAPI()

    @app.get("/")
    def home():
        return HTMLResponse(PAGE % ((WAIT, POLL) if store.get("env") else (CHOOSE, "")))

    @app.post("/shutdown")
    def shutdown():
        threading.Timer(0.3, os._exit, args=(0,)).start()
        return {"ok": True}

    @app.post("/choose")
    def choose(env: str = Form(...)):
        if env in ("prod", "sb2") and not store.get("env"):
            store.put("port", port)
            store.put("env", env)
        return HTMLResponse(PAGE % (WAIT, POLL))

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not store.get("env"):
        time.sleep(0.5)
    time.sleep(1.5)  # let the browser see "Starting"
    server.should_exit = True
    t.join(10)
    return store.get("env")
