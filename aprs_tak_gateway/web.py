import hashlib
import hmac
import os
import secrets
from datetime import datetime
from typing import Any
from urllib.parse import unquote

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import load_config
from .roster import RosterDB, RosterEntry

app = FastAPI()
site_dir = os.path.join(os.path.dirname(__file__), "templates")
template_env = Environment(
    loader=FileSystemLoader(site_dir),
    autoescape=select_autoescape(["html", "xml"]),
)
roster_db: RosterDB | None = None
config: dict[str, Any] | None = None
secret_key_value: bytes | None = None


def _render_template(name: str, context: dict[str, Any]) -> HTMLResponse:
    template = template_env.get_template(name)
    return HTMLResponse(template.render(context))

SESSION_COOKIE = "aprs_tak_gateway_session"


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        parts = stored.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = bytes.fromhex(parts[2])
        expected = bytes.fromhex(parts[3])
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def _load_app_config() -> dict[str, Any]:
    global config
    if config is not None:
        return config
    path = os.getenv("CONFIG_PATH", "config.yaml")
    config = load_config(path)
    return config


def _get_db() -> RosterDB:
    global roster_db
    if roster_db is None:
        raise RuntimeError("RosterDB not initialized")
    return roster_db


def _get_secret_key() -> bytes:
    global secret_key_value
    if secret_key_value is not None:
        return secret_key_value

    cfg = _load_app_config()
    secret = cfg["web"].get("secret_key")
    if secret:
        secret_key_value = secret.encode("utf-8")
    else:
        env_secret = os.getenv("WEB_SECRET_KEY")
        if env_secret:
            secret_key_value = env_secret.encode("utf-8")
        else:
            raise RuntimeError("web.secret_key or WEB_SECRET_KEY must be configured")
    return secret_key_value


def _sign_value(value: str) -> str:
    signature = hmac.new(_get_secret_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}|{signature}"


def _verify_signed_value(signed_value: str) -> str | None:
    signed_value = unquote(signed_value)
    if "|" not in signed_value:
        return None
    value, signature = signed_value.rsplit("|", 1)
    expected = hmac.new(_get_secret_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, signature):
        return value
    return None


def _get_current_user(session_cookie: str | None = Cookie(None, alias=SESSION_COOKIE)) -> str | None:
    if not session_cookie:
        return None
    payload = _verify_signed_value(session_cookie)
    if not payload:
        return None
    return payload


@app.on_event("startup")
async def startup_event() -> None:
    global roster_db
    cfg = _load_app_config()
    _get_secret_key()
    roster_db = RosterDB(cfg["database"]["path"])
    await roster_db.initialize()
    admin_password = cfg["web"].get("admin_password")
    if admin_password:
        existing = await roster_db.get_setting("web_admin_password_hash")
        if existing is None:
            await roster_db.set_setting("web_admin_password_hash", _hash_password(admin_password))


def _require_auth(request: Request, user: str | None) -> str:
    if user is None:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return user


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return _render_template("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)) -> HTMLResponse:
    db = _get_db()
    stored_hash = await db.get_setting("web_admin_password_hash")
    if not stored_hash or not _verify_password(password, stored_hash):
        return HTMLResponse(
            template_env.get_template("login.html").render({"request": request, "error": "Invalid password."}),
            status_code=401,
        )

    response = RedirectResponse(url="/", status_code=303)
    value = _sign_value("admin")
    response.set_cookie(SESSION_COOKIE, value, httponly=True, secure=False)
    return response


@app.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, user: str | None = Depends(_get_current_user)) -> HTMLResponse:
    _require_auth(request, user)
    db = _get_db()
    entries = await db.get_all_entries()
    current_filter = await db.get_filter()
    return _render_template(
        "index.html",
        {
            "request": request,
            "entries": entries,
            "filter_text": current_filter,
            "user": user,
        },
    )


@app.get("/user/create", response_class=HTMLResponse)
async def create_user_page(request: Request, user: str | None = Depends(_get_current_user)) -> HTMLResponse:
    _require_auth(request, user)
    return _render_template("user_form.html", {"request": request, "entry": None, "action": "Create"})


@app.post("/user/create")
async def create_user_submit(
    request: Request,
    aprs_call: str = Form(...),
    tactical_call: str | None = Form(None),
    enabled: str | None = Form(None),
    match_all_ssids: str | None = Form(None),
    remarks: str | None = Form(None),
    user: str | None = Depends(_get_current_user),
) -> RedirectResponse:
    _require_auth(request, user)
    db = _get_db()
    normalized_call = RosterDB._normalize_call(aprs_call)
    display_name = tactical_call.strip() if tactical_call else normalized_call
    await db._execute(
        "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name, tactical_call, remarks) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            normalized_call,
            1 if enabled else 0,
            1 if match_all_ssids else 0,
            RosterDB.generate_tak_uid(normalized_call),
            display_name,
            tactical_call.strip() if tactical_call else None,
            remarks.strip() if remarks else None,
        ),
    )
    await db._connection.commit()
    return RedirectResponse(url="/", status_code=303)


@app.get("/user/edit/{entry_id}", response_class=HTMLResponse)
async def edit_user_page(request: Request, entry_id: int, user: str | None = Depends(_get_current_user)) -> HTMLResponse:
    _require_auth(request, user)
    db = _get_db()
    row = await db._fetchone("SELECT * FROM roster WHERE id = ?", (entry_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")
    entry = db._row_to_entry(row)
    return _render_template(
        "user_form.html",
        {"request": request, "entry": entry, "action": "Edit"},
    )


@app.post("/user/edit/{entry_id}")
async def edit_user_submit(
    request: Request,
    entry_id: int,
    aprs_call: str = Form(...),
    tactical_call: str | None = Form(None),
    enabled: str | None = Form(None),
    match_all_ssids: str | None = Form(None),
    remarks: str | None = Form(None),
    user: str | None = Depends(_get_current_user),
) -> RedirectResponse:
    _require_auth(request, user)
    db = _get_db()
    normalized_call = RosterDB._normalize_call(aprs_call)
    existing = await db._fetchone("SELECT aprs_call, tak_display_name FROM roster WHERE id = ?", (entry_id,))
    if not existing:
        raise HTTPException(status_code=404, detail="Entry not found")
    existing_display_name = existing["tak_display_name"]
    generated_display_name = RosterDB._normalize_call(existing["aprs_call"])
    if tactical_call:
        display_name = tactical_call.strip()
    elif existing_display_name and existing_display_name != generated_display_name:
        display_name = existing_display_name
    else:
        display_name = normalized_call
    await db._execute(
        "UPDATE roster SET aprs_call = ?, enabled = ?, match_all_ssids = ?, tak_uid = ?, tak_display_name = ?, tactical_call = ?, remarks = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (
            normalized_call,
            1 if enabled else 0,
            1 if match_all_ssids else 0,
            RosterDB.generate_tak_uid(normalized_call),
            display_name,
            tactical_call.strip() if tactical_call else None,
            remarks.strip() if remarks else None,
            entry_id,
        ),
    )
    await db._connection.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/user/toggle/{entry_id}")
async def toggle_user(entry_id: int, request: Request, user: str | None = Depends(_get_current_user)) -> RedirectResponse:
    _require_auth(request, user)
    db = _get_db()
    row = await db._fetchone("SELECT enabled FROM roster WHERE id = ?", (entry_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Entry not found")
    enabled = 0 if row["enabled"] else 1
    await db._execute("UPDATE roster SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (enabled, entry_id))
    await db._connection.commit()
    return RedirectResponse(url="/", status_code=303)


@app.post("/user/delete/{entry_id}")
async def delete_user(entry_id: int, request: Request, user: str | None = Depends(_get_current_user)) -> RedirectResponse:
    _require_auth(request, user)
    db = _get_db()
    await db._execute("DELETE FROM roster WHERE id = ?", (entry_id,))
    await db._connection.commit()
    return RedirectResponse(url="/", status_code=303)


@app.get("/filter", response_class=HTMLResponse)
async def filter_page(request: Request, user: str | None = Depends(_get_current_user)) -> HTMLResponse:
    _require_auth(request, user)
    db = _get_db()
    current_filter = await db.get_filter()
    roster_version = await db.get_roster_version()
    return _render_template(
        "filter.html",
        {
            "request": request,
            "filter_text": current_filter,
            "roster_version": roster_version,
        },
    )


@app.post("/reload")
async def reload_filter(request: Request, user: str | None = Depends(_get_current_user)) -> RedirectResponse:
    _require_auth(request, user)
    db = _get_db()
    token = datetime.utcnow().isoformat()
    await db.set_setting("aprsis_reload_token", token)
    return RedirectResponse(url="/filter", status_code=303)
