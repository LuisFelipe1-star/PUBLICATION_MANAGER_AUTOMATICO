from __future__ import annotations

import html
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import keyring
import requests

from meta_api import MetaError

SERVICE = "Publication Manager Meta"
DEFAULT_REDIRECT_URI = "http://localhost:8765/meta/oauth/callback"
SCOPES = (
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
)


class TokenStore:
    """Keeps OAuth credentials in the OS credential vault, never in .env/config.json."""

    def _set(self, name: str, value: str) -> None:
        try:
            keyring.set_password(SERVICE, name, value)
        except Exception as exc:
            raise MetaError(f"Não foi possível salvar o token no cofre de credenciais do Windows: {exc}") from exc

    def _get(self, name: str) -> str:
        try:
            return keyring.get_password(SERVICE, name) or ""
        except Exception as exc:
            raise MetaError(f"Não foi possível acessar o cofre de credenciais do Windows: {exc}") from exc

    def user_token(self) -> str:
        return self._get("user_access_token")

    def page_token(self, page_id: str) -> str:
        return self._get(f"page_access_token:{page_id}") if page_id else ""

    def save_user(self, token: str) -> None:
        self._set("user_access_token", token)

    def save_page(self, page_id: str, token: str) -> None:
        if page_id and token:
            self._set(f"page_access_token:{page_id}", token)

    def clear(self, page_ids=()) -> None:
        names = ["user_access_token", *(f"page_access_token:{page_id}" for page_id in page_ids)]
        for name in names:
            try:
                keyring.delete_password(SERVICE, name)
            except keyring.errors.PasswordDeleteError:
                pass
            except Exception as exc:
                raise MetaError(f"Não foi possível remover a credencial {name}: {exc}") from exc


class _OAuthCallback:
    def __init__(self, expected_state: str):
        self.expected_state = expected_state
        self.event = threading.Event()
        self.code = ""
        self.error = ""

    def handler(self):
        result = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path != "/meta/oauth/callback":
                    self.send_error(404)
                    return
                params = parse_qs(parsed.query)
                state = params.get("state", [""])[0]
                if not secrets.compare_digest(state, result.expected_state):
                    result.error = "Resposta OAuth inválida (state não confere)."
                elif params.get("error"):
                    result.error = params.get("error_description", params["error"])[0]
                else:
                    result.code = params.get("code", [""])[0]
                    if not result.code:
                        result.error = "A Meta não retornou o código de autorização."
                ok = bool(result.code) and not result.error
                title = "Meta conectada" if ok else "Não foi possível conectar"
                body = "Autorização recebida. Você já pode fechar esta janela." if ok else result.error
                title, body = html.escape(title), html.escape(body)
                payload = f"""<!doctype html><html lang=\"pt-BR\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>{title}</title><style>body{{font:16px system-ui;background:#f5f3f7;color:#252129;display:grid;place-items:center;min-height:100vh;margin:0}}main{{max-width:34rem;padding:3rem}}h1{{font-size:2rem}}p{{line-height:1.6}}</style><main><h1>{title}</h1><p>{body}</p></main></html>"""
                raw = payload.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                result.event.set()

            def log_message(self, *_):
                return

        return Handler


class MetaOAuth:
    def __init__(self, cfg, store=None, session=None):
        self.cfg = cfg
        self.store = store or TokenStore()
        self.s = session or requests.Session()
        self.v = cfg.data["meta"]["graph_version"]
        self.app_id = os.getenv("META_APP_ID", "").strip()
        self.app_secret = os.getenv("META_APP_SECRET", "").strip()
        self.config_id = os.getenv("META_LOGIN_CONFIG_ID", "").strip()
        self.redirect_uri = os.getenv("META_REDIRECT_URI", DEFAULT_REDIRECT_URI).strip()

    def _require_app(self):
        if not self.app_id or not self.app_secret or not self.config_id:
            raise MetaError("Configure META_APP_ID, META_APP_SECRET e META_LOGIN_CONFIG_ID no .env antes de conectar.")
        parsed = urlparse(self.redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"} or parsed.port != 8765 or parsed.path != "/meta/oauth/callback":
            raise MetaError("Este aplicativo desktop exige META_REDIRECT_URI=http://localhost:8765/meta/oauth/callback.")

    def verify_app(self):
        app = self._json(
            "GET",
            f"https://graph.facebook.com/{self.v}/app",
            params={"fields": "id,name", "access_token": f"{self.app_id}|{self.app_secret}"},
        )
        if str(app.get("id")) != self.app_id:
            raise MetaError("O META_APP_ID não corresponde ao aplicativo validado pelo App Secret.")
        return app

    def _json(self, method, url, **kwargs):
        try:
            response = self.s.request(method, url, timeout=(20, 90), **kwargs)
        except requests.RequestException as exc:
            raise MetaError(f"Falha ao falar com a Meta: {exc}", transient=True) from exc
        try:
            data = response.json()
        except ValueError:
            data = {"raw": response.text[:500]}
        if not response.ok or "error" in data:
            err = data.get("error", {})
            raise MetaError(err.get("message") or f"HTTP {response.status_code}: {data}")
        return data

    def authorization_url(self, state: str):
        return "https://www.facebook.com/{}/dialog/oauth?{}".format(
            self.v,
            urlencode(
                {
                    "client_id": self.app_id,
                    "redirect_uri": self.redirect_uri,
                    "state": state,
                    "response_type": "code",
                    "config_id": self.config_id,
                }
            ),
        )

    def connect(self, timeout=300):
        self._require_app()
        self.verify_app()
        state = secrets.token_urlsafe(32)
        callback = _OAuthCallback(state)
        try:
            server = ThreadingHTTPServer(("127.0.0.1", 8765), callback.handler())
        except OSError as exc:
            raise MetaError("A porta local 8765 está ocupada. Feche a outra instância e tente novamente.") from exc
        server.timeout = 1
        auth_url = self.authorization_url(state)
        webbrowser.open(auth_url, new=1, autoraise=True)
        deadline = time.monotonic() + timeout
        try:
            while not callback.event.is_set() and time.monotonic() < deadline:
                server.handle_request()
        finally:
            server.server_close()
        if not callback.event.is_set():
            raise MetaError("Tempo esgotado aguardando a autorização da Meta.")
        if callback.error:
            raise MetaError(f"Autorização cancelada ou recusada: {callback.error}")

        short = self._json(
            "GET",
            f"https://graph.facebook.com/{self.v}/oauth/access_token",
            params={
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "redirect_uri": self.redirect_uri,
                "code": callback.code,
            },
        )
        long_lived = self._json(
            "GET",
            f"https://graph.facebook.com/{self.v}/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": self.app_id,
                "client_secret": self.app_secret,
                "fb_exchange_token": short["access_token"],
            },
        )
        user_token = long_lived["access_token"]
        profile = self._json(
            "GET",
            f"https://graph.facebook.com/{self.v}/me",
            params={"fields": "id,name", "access_token": user_token},
        )
        pages = self.discover_pages(user_token)
        if not pages:
            raise MetaError("Nenhuma Página administrável foi liberada. Confira a função da conta e a permissão pages_show_list.")

        self.store.save_user(user_token)
        for page in pages:
            self.store.save_page(page["id"], page.pop("access_token", ""))

        preferred = next((p for p in pages if p.get("instagram")), pages[0])
        expires_in = int(long_lived.get("expires_in") or 0)
        meta = self.cfg.data["meta"]
        meta.update(
            {
                "connected_user_id": profile.get("id", ""),
                "connected_user_name": profile.get("name", ""),
                "token_expires_at": int(time.time()) + expires_in if expires_in else 0,
                "available_pages": pages,
                "facebook_page_id": preferred["id"],
                "facebook_page_name": preferred["name"],
                "instagram_user_id": preferred.get("instagram", {}).get("id", ""),
                "instagram_username": preferred.get("instagram", {}).get("username", ""),
            }
        )
        self.cfg.save()
        return self.summary()

    def discover_pages(self, user_token: str):
        url = f"https://graph.facebook.com/{self.v}/me/accounts"
        params = {
            "fields": "id,name,access_token,tasks,instagram_business_account{id,username}",
            "limit": 100,
            "access_token": user_token,
        }
        pages = []
        while url:
            data = self._json("GET", url, params=params)
            params = None
            for raw in data.get("data", []):
                page = {
                    "id": raw["id"],
                    "name": raw.get("name", raw["id"]),
                    "tasks": raw.get("tasks", []),
                    "access_token": raw.get("access_token", ""),
                }
                ig = raw.get("instagram_business_account")
                if ig:
                    page["instagram"] = {"id": ig["id"], "username": ig.get("username", "")}
                pages.append(page)
            url = data.get("paging", {}).get("next")
        return pages

    def select_page(self, page_id: str):
        pages = self.cfg.data["meta"].get("available_pages", [])
        page = next((p for p in pages if p["id"] == page_id), None)
        if not page:
            raise MetaError("Página selecionada não está entre os ativos autorizados.")
        meta = self.cfg.data["meta"]
        meta.update(
            {
                "facebook_page_id": page["id"],
                "facebook_page_name": page["name"],
                "instagram_user_id": page.get("instagram", {}).get("id", ""),
                "instagram_username": page.get("instagram", {}).get("username", ""),
            }
        )
        self.cfg.save()

    def disconnect(self):
        pages = self.cfg.data["meta"].get("available_pages", [])
        self.store.clear([p["id"] for p in pages])
        meta = self.cfg.data["meta"]
        for key, empty in {
            "connected_user_id": "",
            "connected_user_name": "",
            "token_expires_at": 0,
            "available_pages": [],
            "facebook_page_id": "",
            "facebook_page_name": "",
            "instagram_user_id": "",
            "instagram_username": "",
        }.items():
            meta[key] = empty
        self.cfg.save()

    def summary(self):
        meta = self.cfg.data["meta"]
        return {
            "user": meta.get("connected_user_name", ""),
            "page": meta.get("facebook_page_name", ""),
            "instagram": meta.get("instagram_username", ""),
            "pages": len(meta.get("available_pages", [])),
            "expires_at": meta.get("token_expires_at", 0),
        }
