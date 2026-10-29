"""ServiceChannel HTTP client: OAuth password grant per user, token cache, per-app rate limit, audit logging."""
import base64
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

import certifi

# the packaged desktop app has no system CA bundle, so verify against certifi's
SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

ENVS = {
    "sb2": ("https://sb2login.servicechannel.com/oauth/token", "https://sb2api.servicechannel.com/v3"),
    "prod": ("https://login.servicechannel.com/oauth/token", "https://api.servicechannel.com/v3"),
}


class Park(Exception):
    """The live WO changed in a way the plan cannot follow. The step fails at once (no retries) so the Errors page shows it."""


class Later(Exception):
    """The running step was moved to a later time (the WO's scheduled date changed). It stays pending and is not counted as an attempt."""


class ScError(Exception):
    def __init__(self, status, body, path=""):
        super().__init__(f"{status} {path}: {str(body)[:300]}")
        self.status, self.body = status, body


class RateLimiter:
    """Sliding window: at most `per_min` calls in any 60 s. One instance per integration app."""

    def __init__(self, per_min=15, clock=time.monotonic, sleep=time.sleep):
        self.per_min, self.clock, self.sleep, self.calls = per_min, clock, sleep, []

    def wait(self):
        now = self.clock()
        self.calls = [t for t in self.calls if now - t < 60]
        if len(self.calls) >= self.per_min:
            self.sleep(60 - (now - self.calls[0]) + 0.05)
            now = self.clock()
            self.calls = [t for t in self.calls if now - t < 60]
        self.calls.append(now)


class ScApp:
    """One integration application (client id/secret) with a shared limiter and per-user token cache."""

    def __init__(self, env, client_id, client_secret, per_min=15, transport=None, store=None, role=""):
        self.token_url, self.base = ENVS[env]
        self.client_id, self.client_secret = client_id, client_secret
        self.limiter, self.store, self.role = RateLimiter(per_min), store, role
        self.transport = transport or self._http
        self.tokens = {}  # username -> (token, expires_at)
        self.paused = lambda: False  # engine sets this; writes are refused while true

    @staticmethod
    def _http(method, url, headers, data):
        req = urllib.request.Request(url, method=method, headers=headers, data=data)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None  # bad client id/secret returns a 302 to an HTML login page

        try:
            r = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=SSL_CONTEXT)).open(req, timeout=90)
            return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def token(self, username, password):
        tok = self.tokens.get(username)
        if tok and tok[1] > time.time():
            return tok[0]
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        body = urllib.parse.urlencode({"grant_type": "password", "username": username, "password": password})
        status, text = self.transport("POST", self.token_url, {
            "Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"}, body.encode())
        if status in (301, 302):
            raise ScError(status, "Client ID or secret rejected (redirected to login page)", "token")
        if status == 400:
            raise ScError(status, "Username or password rejected", "token")
        if status != 200:
            raise ScError(status, text, "token")
        j = json.loads(text)
        self.tokens[username] = (j["access_token"], time.time() + j.get("expires_in", 600) - 30)
        return j["access_token"]

    def call(self, user, method, path, params=None, body=None, *, action="", wo=None, write=None):
        """user = (username, password). Returns parsed JSON (or None). Raises ScError on non-2xx."""
        write = method != "GET" if write is None else write
        if write and self.paused():
            raise ScError(0, "paused", path)
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(3):
            self.limiter.wait()
            t0 = time.time()
            headers = {"Authorization": "Bearer " + self.token(*user), "Accept": "application/json",
                       "Content-Type": "application/json"}
            status, text = self.transport(method, url, headers, data)
            if status == 401:
                self.tokens.pop(user[0], None)
                continue
            if status == 429:
                time.sleep(30)
                continue
            break
        if self.store:
            self.store.log(role=self.role, user=user[0], sc_wo=wo, action=action, method=method, path=path,
                           http=status, ms=int((time.time() - t0) * 1000), detail=None if status < 400 else text[:300])
        if status >= 400:
            raise ScError(status, text, path)
        return json.loads(text) if text else None
