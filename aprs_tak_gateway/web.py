import hashlib
import hmac
import os
import secrets
from datetime import datetime
from typing import Any

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import load_config
from .roster import RosterDB, RosterEntry

app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
roster_db: RosterDB | None = None
config: dict[str, Any] | None = None

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
    cfg = _load_app_config()
    secret = cfg["web"].get("secret_key")
    if not secret:
        secret = os.getenv("WEB_SECRET_KEY") or secrets.token_hex(32)
    return secret.encode("utf-8")


def _sign_value(value: str) -> str:
    signature = hmac.new(_get_secret_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{value}|{signature}"


def _verify_signed_value(signed_value: str) -> str | None:
    if "|" not in signed_value:
        return None
    value, signature = signed_value.rsplit("|", 1)
    expected = hmac.new(_get_secret_key(), value.encode("utf-8"), hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, signature):
        return value
    return None


def _get_current_user(session_cookie: str | None = Cookie(None)) -> str | None:
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
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)) -> HTMLResponse:
    db = _get_db()
    stored_hash = await db.get_setting("web_admin_password_hash")
    if not stored_hash or not _verify_password(password, stored_hash):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid password."},
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
    return templates.TemplateResponse(
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
    return templates.TemplateResponse("user_form.html", {"request": request, "entry": None, "action": "Create"})


@app.post("/user/create")
async def create_user_submit(
    request: Request,
    aprs_call: str = Form(...),
    tak_uid: str = Form(...),
    tak_display_name: str = Form(...),
    tactical_call: str | None = Form(None),
    enabled: str | None = Form(None),
    match_all_ssids: str | None = Form(None),
    team: str | None = Form(None),
    role: str | None = Form(None),
    icon: str | None = Form(None),
    remarks: str | None = Form(None),
    user: str | None = Depends(_get_current_user),
) -> RedirectResponse:
    _require_auth(request, user)
    db = _get_db()
    await db._execute(
        "INSERT INTO roster(aprs_call, enabled, match_all_ssids, tak_uid, tak_display_name, tactical_call, team, role, icon, remarks) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            aprs_call.upper().strip(),
            1 if enabled else 0,
            1 if match_all_ssids else 0,
            tak_uid.strip(),
            tak_display_name.strip(),
            tactical_call.strip() if tactical_call else None,
            team.strip() if team else None,
            role.strip() if role else None,
            icon.strip() if icon else None,
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
    return templates.TemplateResponse(
        "user_form.html",
        {"request": request, "entry": entry, "action": "Edit"},
    )


@app.post("/user/edit/{entry_id}")
async def edit_user_submit(
    request: Request,
    entry_id: int,
    aprs_call: str = Form(...),
    tak_uid: str = Form(...),
    tak_display_name: str = Form(...),
    tactical_call: str | None = Form(None),
    enabled: str | None = Form(None),
    match_all_ssids: str | None = Form(None),
    team: str | None = Form(None),
    role: str | None = Form(None),
    icon: str | None = Form(None),
    remarks: str | None = Form(None),
    user: str | None = Depends(_get_current_user),
) -> RedirectResponse:
    _require_auth(request, user)
    db = _get_db()
    await db._execute(
        "UPDATE roster SET aprs_call = ?, enabled = ?, match_all_ssids = ?, tak_uid = ?, tak_display_name = ?, tactical_call = ?, team = ?, role = ?, icon = ?, remarks = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (
            aprs_call.upper().strip(),
            1 if enabled else 0,
            1 if match_all_ssids else 0,
            tak_uid.strip(),
            tak_display_name.strip(),
            tactical_call.strip() if tactical_call else None,
            team.strip() if team else None,
            role.strip() if role else None,
            icon.strip() if icon else None,
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
    return templates.TemplateResponse(
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
