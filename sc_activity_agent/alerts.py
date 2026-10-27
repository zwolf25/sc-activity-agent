"""Optional Telegram alerts (B-42a) and action buttons (B-42b). Everything is outbound: alerts are sendMessage calls and button
taps are read by long polling getUpdates, so no server or open port is needed. Each instance has its own bot, token and settings.
Nothing here may stop the engine: sending never raises."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from .client import SSL_CONTEXT, ScError

COOLDOWN = 6 * 3600    # the same alert key is sent at most once per this many seconds
CAP, CAP_WINDOW = 10, 3600   # and at most this many messages per hour; one summary message says the rest are held back
EVENTS = {"step_failed": "A step failed after its retries",
          "checkin_blocked": "Check-in is blocked for a Provider (error 804)",
          "connection": "A connection or login failed",
          "offline": "The agent was not running for over an hour"}


class AlertError(Exception):
    pass


def api(token, method, **params):
    """One Telegram Bot API call. Returns `result`; raises AlertError with Telegram's own description."""
    data = urllib.parse.urlencode({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in params.items()}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data),
                                    timeout=40, context=SSL_CONTEXT) as r:
            return json.load(r)["result"]
    except urllib.error.HTTPError as e:
        try:
            raise AlertError(json.load(e).get("description", str(e))) from None
        except ValueError:
            raise AlertError(str(e)) from None
    except (urllib.error.URLError, OSError) as e:
        raise AlertError(f"Could not reach Telegram: {e}") from None


class Alerts:
    def __init__(self, store, call=api):
        self.store, self.call = store, call

    @property
    def cfg(self):
        c = {"enabled": False, "buttons": False, "chat_id": None, "chat_name": "", "bot": "", "events": {}}
        c.update(self.store.get("alerts", {}))
        return c

    def save(self, **kw):
        self.store.put("alerts", {**self.cfg, **kw})

    def token(self):
        t = self.store.get("alerts_token")
        return self.store.dec(t) if t else None

    def ready(self):
        return bool(self.cfg["enabled"] and self.cfg["chat_id"] and self.token())

    def tag(self):
        return "[PROD]" if self.store.get("env") == "prod" else "[SB2]"

    def raw(self, text, buttons=None):
        """Send now, no cooldown. Raises AlertError (used by the Send test message button)."""
        c = self.cfg
        extra = {"reply_markup": {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in buttons]}} \
            if buttons and c["buttons"] else {}
        return self.call(self.token(), "sendMessage", chat_id=c["chat_id"], text=f"{self.tag()} {text}", **extra)

    def send(self, key, text, buttons=None, event=None):
        """Alert with a cooldown per key and an hourly cap. Never raises."""
        try:
            if not self.ready() or (event and not self.cfg["events"].get(event, True)):
                return False
            now = time.time()
            sent = self.store.get("alert_sent", {})
            if now - sent.get(key, 0) < COOLDOWN:
                return False
            times = [t for t in self.store.get("alert_times", []) if now - t < CAP_WINDOW]
            if len(times) >= CAP:
                if not self.store.get("alert_capped"):
                    self.store.put("alert_capped", True)
                    self.raw(f"{CAP} alerts were sent in the last hour. More are held back. Open the console, Errors page.")
                    times.append(now)
                    self.store.put("alert_times", times)
                return False
            self.store.put("alert_capped", False)
            self.raw(text, buttons)
            sent[key] = now
            self.store.put("alert_sent", {k: v for k, v in sent.items() if now - v < COOLDOWN})
            self.store.put("alert_times", times + [now])
            return True
        except Exception as e:  # noqa: BLE001
            self.store.put("alert_error", f"{time.strftime('%b %d %H:%M')} {e}")
            return False

    # --- events -----------------------------------------------------------------------------------------------------
    def step_failed(self, wo, st, err):
        loc, sc_id, n = wo["location"], wo["sc_id"], st["attempts"] + 1
        text = str(err)
        if getattr(err, "status", None) == 403 and "804" in text and st["kind"] in ("check_in", "check_out"):
            return self.send(f"804:{loc}", f"Check-in is blocked at {loc} (error 804). ServiceChannel support must enable check-in/out "
                             f"for this Subscriber and Provider pair. Open the console, Setup page, for the request text.",
                             event="checkin_blocked")
        if isinstance(err, ScError) and (err.status in (401, 302) or "oauth" in text.lower()):
            return self.send(f"login:{loc}", f"Login failed while running {st['kind']} for WO {sc_id} at {loc}: {text[:160]}",
                             [[("Pause agent", "p")]], event="connection")
        return self.send(f"step:{st['id']}", f"WO {sc_id} at {loc}: {st['kind']} failed after {n} tries. {text[:200]}",
                         [[("Retry", f"r:{st['id']}"), ("Skip step", f"s:{st['id']}")],
                          [("Pause agent", "p"), ("Cancel WO", f"c:{wo['id']}")]], event="step_failed")

    def offline(self, start, end):
        if end - start <= 3600:
            return False
        mins = round((end - start) / 60)
        return self.send("offline", f"The agent was not running for {mins // 60} h {mins % 60} min and is back. Steps that came due "
                         f"meanwhile were moved forward.", [[("Dismiss", "d")]], event="offline")

    # --- button taps ------------------------------------------------------------------------------------------------
    def tap(self, cb, engine, rt):
        """Handle one callback_query. Returns the text shown to the user, or None when ignored."""
        if cb["message"]["chat"]["id"] != self.cfg["chat_id"]:
            return None   # only the chat set up in Settings may act
        d, _, arg = cb["data"].partition(":")
        db = self.store.db
        out = None
        if d in ("r", "s"):
            st = db.execute("SELECT * FROM steps WHERE id=?", (int(arg),)).fetchone()
            if not st:
                out = "That step no longer exists."
            elif d == "r" and st["state"] == "failed":
                engine.retry(st["id"])
                out = "Retrying now."
            elif d == "s" and st["state"] in ("failed", "pending"):
                engine.skip(st["id"])
                out = "Step skipped."
            else:
                out = f"Nothing done: the step is already {st['state']}."
        elif d == "p":
            out = "Already paused." if engine.paused else "Paused. Resume it from the console."
            if not engine.paused:
                engine.pause()
        elif d == "u":
            engine.resume(self.store.get("resume_policy", "catch_up"))
            out = "Resumed."
        elif d == "c":
            return ("ask", f"Cancel WO in {self.tag()}? This cancels it in ServiceChannel.", [[("Yes, cancel", f"cy:{arg}"), ("No", "n")]])
        elif d == "cy":
            wo = db.execute("SELECT * FROM work_orders WHERE id=?", (int(arg),)).fetchone()
            if not wo or wo["state"] != "active":
                out = "Nothing done: the WO is not active."
            else:
                from .handlers import cancel_wo
                try:
                    cancel_wo(rt, wo, "Cancelled from a Telegram alert")
                    out = f"WO {wo['sc_id']} cancelled."
                except ScError as e:
                    out = f"Could not cancel: {str(e)[:150]}"
        else:
            out = "Dismissed."
        if d in ("r", "s", "p", "u", "cy"):
            log = self.store.get("changes", [])[-49:]
            log.append({"at": time.time(), "what": f"telegram: {cb['data']} -> {out}"})
            self.store.put("changes", log)
        return ("done", out, None)

    def poll_once(self, engine, rt, timeout=20):
        """Fetch pending taps and act on them. Returns the number handled."""
        offset = self.store.get("alerts_offset", 0)
        n = 0
        for u in self.call(self.token(), "getUpdates", offset=offset, timeout=timeout, allowed_updates=["callback_query"]):
            self.store.put("alerts_offset", u["update_id"] + 1)
            cb = u.get("callback_query")
            if not cb:
                continue
            res = self.tap(cb, engine, rt)
            tok = self.token()
            if res is None:
                self.call(tok, "answerCallbackQuery", callback_query_id=cb["id"], text="Not allowed.")
                continue
            kind, text, buttons = res
            if kind == "ask":   # swap the message for a yes/no question
                self.call(tok, "answerCallbackQuery", callback_query_id=cb["id"])
                self.call(tok, "editMessageText", chat_id=cb["message"]["chat"]["id"], message_id=cb["message"]["message_id"],
                          text=text, reply_markup={"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in r] for r in buttons]})
            else:
                self.call(tok, "answerCallbackQuery", callback_query_id=cb["id"], text=text[:190])
                self.call(tok, "editMessageText", chat_id=cb["message"]["chat"]["id"], message_id=cb["message"]["message_id"],
                          text=f"{cb['message'].get('text', '')}\n→ {text}")
            n += 1
        return n

    def poll_forever(self, engine, rt):
        while True:
            try:
                if self.cfg["enabled"] and self.cfg["buttons"] and self.cfg["chat_id"] and self.token():
                    self.poll_once(engine, rt)
                    continue
            except Exception as e:  # noqa: BLE001
                self.store.put("alert_error", f"{time.strftime('%b %d %H:%M')} {e}")
            time.sleep(15)
