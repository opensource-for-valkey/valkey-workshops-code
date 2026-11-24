"""Flask server-side sessions using native GLIDE and Flask's signed serializer."""

from __future__ import annotations

import re
import secrets

from flask.sessions import SessionInterface, SessionMixin, SecureCookieSessionInterface
from flask.json.tag import TaggedJSONSerializer
from glide_sync import ExpirySet, ExpiryType
from itsdangerous import BadSignature
from werkzeug.datastructures import CallbackDict


class GlideSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid: str | None = None, new: bool = False):
        def on_update(session):
            session.modified = True
            session.accessed = True

        super().__init__(initial, on_update)
        self.sid = sid or secrets.token_urlsafe(32)
        self.new = new
        self.modified = False
        self.accessed = False


class GlideSessionInterface(SessionInterface):
    """Cookies contain only signed IDs; Valkey owns tagged JSON and expiration."""

    serializer = TaggedJSONSerializer()
    session_class = GlideSession

    def __init__(self, cache, key_prefix: str = "flight_session:", ttl: int = 2_678_400):
        self.cache = cache
        self.key_prefix = key_prefix
        self.ttl = ttl
        if ttl < 1:
            raise ValueError("Session TTL must be positive")

    def _key(self, sid: str) -> str:
        return self.cache.key(self.key_prefix + sid)

    @staticmethod
    def _signer(app):
        signer = SecureCookieSessionInterface().get_signing_serializer(app)
        if signer is None:
            raise RuntimeError("Set SECRET_KEY in the private .env before starting Flask")
        return signer

    def open_session(self, app, request):
        cookie = request.cookies.get(self.get_cookie_name(app))
        sid = None
        if cookie:
            try:
                candidate = self._signer(app).loads(cookie, max_age=self.ttl)
                if isinstance(candidate, str) and re.fullmatch(r"[A-Za-z0-9_-]{43}", candidate):
                    sid = candidate
            except BadSignature:
                pass
        if sid:
            stored = self.cache.client.get(self._key(sid))
            if stored is not None:
                data = self.serializer.loads(stored.decode("utf-8"))
                if isinstance(data, dict):
                    return self.session_class(data, sid=sid)
        # Missing, expired, or tampered IDs never revive an old session.
        return self.session_class(new=True)

    def regenerate(self, session) -> None:
        """Delete the old ID and rotate it at login or logout."""
        self.cache.client.delete([self._key(session.sid)])
        session.sid = secrets.token_urlsafe(32)
        session.modified = True
        session.new = True

    def save_session(self, app, session, response):
        name = self.get_cookie_name(app)
        cookie_options = {
            "domain": self.get_cookie_domain(app),
            "path": self.get_cookie_path(app),
            "secure": self.get_cookie_secure(app),
            "httponly": self.get_cookie_httponly(app),
            "samesite": self.get_cookie_samesite(app),
        }
        response.vary.add("Cookie")
        if not session:
            if session.modified:
                self.cache.client.delete([self._key(session.sid)])
                response.delete_cookie(name, **cookie_options)
            return
        if session.modified or session.new or app.config.get("SESSION_REFRESH_EACH_REQUEST", True):
            self.cache.client.set(
                self._key(session.sid),
                self.serializer.dumps(dict(session)),
                expiry=ExpirySet(ExpiryType.SEC, self.ttl),
            )
            response.set_cookie(
                name,
                self._signer(app).dumps(session.sid),
                expires=self.get_expiration_time(app, session),
                **cookie_options,
            )
