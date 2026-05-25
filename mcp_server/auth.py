"""
OAuth 2.1 Authorization Code + PKCE flow cho MCP streamable-HTTP transport.
Google làm identity provider. Email allow-list kiểm soát quyền truy cập.

Flow:
  1. Claude.ai → GET /authorize?response_type=code&client_id=...&redirect_uri=...
                              &state=...&code_challenge=...&code_challenge_method=S256
  2. Server    → redirect sang Google OAuth
  3. Google    → GET /auth/google/callback?code=...&state=...
  4. Server    → xác minh email → tạo auth_code → redirect về Claude.ai
  5. Claude.ai → POST /token  (grant_type=authorization_code, code=..., code_verifier=...)
  6. Server    → verify PKCE → trả Bearer token
  7. Claude.ai → POST/GET /mcp  với  Authorization: Bearer <token>
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp

from database.auth import is_email_allowed

logger = logging.getLogger(__name__)

_PROTECTED_PREFIXES = ("/mcp",)

_GOOGLE_AUTH_URL     = "https://accounts.google.com/o/oauth2/v2/auth"
_GOOGLE_TOKEN_URL    = "https://oauth2.googleapis.com/token"
_GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# ── In-memory stores ────────────────────────────────────────────────────────
_pending_auth:       dict[str, dict] = {}  # google_state  → OAuth request params
_auth_codes:         dict[str, dict] = {}  # our_code      → {email, challenge, ...}
_tokens:             dict[str, dict] = {}  # token         → {email, expires_at}
_registered_clients: dict[str, dict] = {}  # client_id     → {redirect_uris, ...}


def _cleanup() -> None:
    now = time.time()
    for store in (_pending_auth, _auth_codes, _tokens):
        for k in [k for k, v in list(store.items()) if v.get("expires_at", 0) < now]:
            store.pop(k, None)


# ── PKCE ────────────────────────────────────────────────────────────────────

def _verify_pkce(verifier: str, challenge: str, method: str) -> bool:
    if method == "S256":
        digest = hashlib.sha256(verifier.encode()).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == challenge
    return verifier == challenge  # plain


# ── Token validation (shared with middleware) ────────────────────────────────

def validate_token(token: str) -> str | None:
    """Returns email if token is valid and not expired, None otherwise."""
    _cleanup()
    entry = _tokens.get(token)
    if not entry or entry["expires_at"] < time.time():
        _tokens.pop(token, None)
        return None
    return entry["email"]


# ── Middleware ───────────────────────────────────────────────────────────────

class BearerTokenMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, base_url: str = "") -> None:
        super().__init__(app)
        self._resource_metadata = (
            base_url.rstrip("/") + "/.well-known/oauth-protected-resource"
        )

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if not any(path.startswith(p) for p in _PROTECTED_PREFIXES):
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return Response(
                '{"error":"unauthorized","error_description":"Bearer token required"}',
                status_code=401,
                media_type="application/json",
                headers={
                    "WWW-Authenticate": f'Bearer resource_metadata="{self._resource_metadata}"'
                },
            )

        email = validate_token(auth[7:])
        if email is None:
            return Response(
                '{"error":"invalid_token","error_description":"Token invalid or expired"}',
                status_code=401,
                media_type="application/json",
                headers={
                    "WWW-Authenticate": (
                        f'Bearer error="invalid_token",'
                        f' resource_metadata="{self._resource_metadata}"'
                    )
                },
            )

        logger.debug("oauth.authorized email=%s path=%s", email, path)
        return await call_next(request)


# ── App builder ──────────────────────────────────────────────────────────────

def build_auth_app(
    mcp_asgi: ASGIApp,
    base_url: str,
    google_client_id: str,
    google_client_secret: str,
    token_ttl: int = 3600,
) -> Starlette:
    """Wrap MCP ASGI app with OAuth 2.1 + PKCE routes and Bearer middleware."""
    base            = base_url.rstrip("/")
    google_redirect = f"{base}/auth/google/callback"

    # ── Well-known endpoints ─────────────────────────────────────────────

    async def well_known_auth_server(request: Request) -> JSONResponse:
        return JSONResponse({
            "issuer":                                base,
            "authorization_endpoint":                f"{base}/authorize",
            "token_endpoint":                        f"{base}/token",
            "registration_endpoint":                 f"{base}/register",
            "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
            "grant_types_supported":                 ["authorization_code"],
            "response_types_supported":              ["code"],
            "code_challenge_methods_supported":      ["S256", "plain"],
            "scopes_supported":                      ["openid", "email", "mcp"],
        })

    async def well_known_protected_resource(request: Request) -> JSONResponse:
        return JSONResponse({
            "resource":                 base,
            "authorization_servers":    [base],
            "bearer_methods_supported": ["header"],
        })

    # ── Dynamic Client Registration (RFC 7591) ───────────────────────────

    async def register(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            body = {}
        client_id = secrets.token_urlsafe(16)
        _registered_clients[client_id] = {
            "redirect_uris": body.get("redirect_uris", []),
            "client_name":   body.get("client_name", "unknown"),
        }
        logger.info("oauth.dcr.registered client_id=%s name=%s", client_id, body.get("client_name"))
        return JSONResponse({
            "client_id":                  client_id,
            "client_id_issued_at":        int(time.time()),
            "redirect_uris":              body.get("redirect_uris", []),
            "grant_types":                body.get("grant_types", ["authorization_code"]),
            "response_types":             body.get("response_types", ["code"]),
            "token_endpoint_auth_method": "none",
        }, status_code=201)

    # ── /authorize → redirect to Google ─────────────────────────────────

    async def authorize(request: Request) -> Response:
        params    = dict(request.query_params)
        our_state = secrets.token_urlsafe(24)
        _pending_auth[our_state] = {
            "claude_state":          params.get("state", ""),
            "redirect_uri":          params.get("redirect_uri", ""),
            "code_challenge":        params.get("code_challenge", ""),
            "code_challenge_method": params.get("code_challenge_method", "S256"),
            "expires_at":            time.time() + 600,
        }
        google_params = urlencode({
            "client_id":     google_client_id,
            "redirect_uri":  google_redirect,
            "response_type": "code",
            "scope":         "openid email",
            "state":         our_state,
            "access_type":   "online",
            "prompt":        "select_account",
        })
        return RedirectResponse(f"{_GOOGLE_AUTH_URL}?{google_params}", status_code=302)

    # ── /auth/google/callback ────────────────────────────────────────────

    async def google_callback(request: Request) -> Response:
        _cleanup()
        params  = dict(request.query_params)
        code    = params.get("code")
        pending = _pending_auth.pop(params.get("state", ""), None)

        if not pending:
            return Response("State không hợp lệ hoặc đã hết hạn.", status_code=400)
        if not code:
            return Response(
                f"Google OAuth error: {params.get('error', 'access_denied')}", status_code=400
            )

        # Exchange Google code → access token
        async with httpx.AsyncClient() as client:
            tok = await client.post(_GOOGLE_TOKEN_URL, data={
                "code":          code,
                "client_id":     google_client_id,
                "client_secret": google_client_secret,
                "redirect_uri":  google_redirect,
                "grant_type":    "authorization_code",
            })
        if tok.status_code != 200:
            logger.error("google.token.error: %s", tok.text)
            return Response("Không lấy được Google token.", status_code=502)

        # Get user email
        async with httpx.AsyncClient() as client:
            user = await client.get(
                _GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {tok.json().get('access_token', '')}"},
            )
        if user.status_code != 200:
            return Response("Không lấy được thông tin Google user.", status_code=502)

        email = user.json().get("email", "").lower()
        logger.info("oauth.google.login email=%s", email)

        # Email allow-list check
        if not is_email_allowed(email):
            return HTMLResponse(
                f"""<html><body style="font-family:sans-serif;max-width:500px;margin:3rem auto;padding:1rem">
<h2>⛔ Truy cập bị từ chối</h2>
<p>Email <strong>{email}</strong> chưa được cấp quyền.</p>
<p>Liên hệ admin để được thêm vào danh sách.</p>
</body></html>""",
                status_code=403,
            )

        # Issue our own short-lived auth code
        auth_code = secrets.token_urlsafe(32)
        _auth_codes[auth_code] = {
            "email":                 email,
            "redirect_uri":          pending["redirect_uri"],
            "code_challenge":        pending["code_challenge"],
            "code_challenge_method": pending["code_challenge_method"],
            "expires_at":            time.time() + 300,
        }

        redirect = pending["redirect_uri"]
        sep = "&" if "?" in redirect else "?"
        return RedirectResponse(
            f"{redirect}{sep}code={auth_code}&state={pending['claude_state']}",
            status_code=302,
        )

    # ── /token ───────────────────────────────────────────────────────────

    async def token(request: Request) -> JSONResponse:
        _cleanup()
        form = await request.form()

        if str(form.get("grant_type", "")) != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        code          = str(form.get("code", ""))
        code_verifier = str(form.get("code_verifier", ""))
        redirect_uri  = str(form.get("redirect_uri", ""))
        entry         = _auth_codes.pop(code, None)

        if not entry or entry["expires_at"] < time.time():
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "Code invalid or expired"},
                status_code=400,
            )
        if redirect_uri and redirect_uri != entry["redirect_uri"]:
            return JSONResponse(
                {"error": "invalid_grant", "error_description": "redirect_uri mismatch"},
                status_code=400,
            )
        if entry["code_challenge"] and code_verifier:
            if not _verify_pkce(code_verifier, entry["code_challenge"], entry["code_challenge_method"]):
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "PKCE verification failed"},
                    status_code=400,
                )

        access_token = secrets.token_urlsafe(32)
        _tokens[access_token] = {
            "email":      entry["email"],
            "expires_at": time.time() + token_ttl,
        }
        logger.info("oauth.token.issued email=%s ttl=%ds", entry["email"], token_ttl)

        return JSONResponse({
            "access_token": access_token,
            "token_type":   "Bearer",
            "expires_in":   token_ttl,
            "scope":        "mcp",
        })

    # ── Compose app ──────────────────────────────────────────────────────

    routes = [
        Route("/.well-known/oauth-authorization-server", well_known_auth_server),
        Route("/.well-known/oauth-protected-resource",   well_known_protected_resource),
        Route("/register",              register,        methods=["POST"]),
        Route("/authorize",             authorize),
        Route("/auth/google/callback",  google_callback),
        Route("/token",                 token,           methods=["POST"]),
        Mount("/", app=mcp_asgi),
    ]

    return Starlette(
        routes=routes,
        middleware=[Middleware(BearerTokenMiddleware, base_url=base_url)],
    )
