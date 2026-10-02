import logging
import secrets
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware

from .config import settings
from .db import (
    PLAN_STATUSES,
    ROLES,
    delete_plan,
    get_plans,
    get_plan_history,
    get_user,
    initialize,
    list_users,
    save_plan,
    save_user,
)
from .security import hash_password, verify_password
from .sources import get_attention_rows


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("atencion_cliente")
STATIC_DIR = Path(__file__).resolve().parent / "static"
IMAGE_DIR = Path(__file__).resolve().parent.parent / "image"

app = FastAPI(title="Gestión de Atención al Cliente", docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="atencion_session",
    same_site="lax",
    https_only=False,
    max_age=8 * 60 * 60,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/images", StaticFiles(directory=IMAGE_DIR), name="images")


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class PlanBody(BaseModel):
    status: str = Field(pattern="^(abierto|en_proceso|concluido)$")
    plan_text: str = Field(min_length=1, max_length=10000)


class UserBody(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=200)
    role: str
    scope_name: Optional[str] = Field(default=None, max_length=160)


@app.on_event("startup")
def startup() -> None:
    initialize()


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "atencion-cliente"}


def current_user(request: Request):
    username = request.session.get("username")
    if not username:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")
    user = get_user(username)
    if not user:
        request.session.clear()
        raise HTTPException(status_code=401, detail="La sesión ya no está activa.")
    return dict(user)


def require_csrf(request: Request, token: Optional[str]) -> None:
    expected = request.session.get("csrf_token")
    if not expected or not token or not secrets.compare_digest(expected, token):
        raise HTTPException(status_code=403, detail="Token de seguridad inválido.")


def same_name(value, scope) -> bool:
    return bool(value and scope and str(value).strip().casefold() == str(scope).strip().casefold())


def division_for(row: dict) -> str:
    code = str(row.get("CveUnidad") or "").strip().upper()
    if code.startswith("CL"):
        return "Sucursal"
    if code.startswith("F"):
        return "Franquicia"
    return ""


def visible_to_user(row: dict, user: dict) -> bool:
    role = user["role"]
    division = division_for(row)
    if role in {"admin", "gerente_general"}:
        return True
    if role == "gerente_ventas":
        return division == "Sucursal"
    if role == "gerente_franquicias":
        return division == "Franquicia"
    if role == "jefe_comercial_ventas":
        return division == "Sucursal" and same_name(
            row.get("NomJefeComercial"), user.get("scope_name")
        )
    if role == "jefe_comercial_franquicias":
        return division == "Franquicia" and same_name(
            row.get("NomJefeComercial"), user.get("scope_name")
        )
    if role == "supervisor":
        return same_name(row.get("NomSupervisor"), user.get("scope_name"))
    return False


def load_visible_rows(user: dict) -> list[dict]:
    try:
        rows = get_attention_rows()
    except Exception as exc:
        logger.exception("SQL source unavailable (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="No se pudieron leer los datos. Revisa la conexión SQL configurada.",
        ) from exc
    return [row for row in rows if visible_to_user(row, user)]


def category(row: dict) -> str:
    value = str(row.get("TipoEvaluacion") or "").strip().casefold()
    if value in {"mala", "regular", "buena"}:
        return value.title()
    if str(row.get("Fuente") or "").upper() == "MS":
        try:
            score = float(row.get("PuntajeMS"))
        except (TypeError, ValueError):
            return "Sin clasificación"
        if 0 <= score <= 49:
            return "Mala"
        if 50 <= score <= 79:
            return "Regular"
        if 80 <= score <= 100:
            return "Buena"
        return "Sin clasificación"
    try:
        rating = int(row.get("Rating"))
    except (TypeError, ValueError):
        return "Sin clasificación"
    if rating in {1, 2}:
        return "Mala"
    if rating == 3:
        return "Regular"
    if rating in {4, 5}:
        return "Buena"
    return "Sin clasificación"


@app.post("/api/login")
def login(body: LoginBody, request: Request):
    user = get_user(body.username.strip())
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos.")
    request.session.clear()
    request.session["username"] = user["username"]
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return {
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "role_label": ROLES[user["role"]],
        "csrf_token": request.session["csrf_token"],
    }


@app.post("/api/logout")
def logout(
    request: Request,
    user=Depends(current_user),
    x_csrf_token: Optional[str] = Header(default=None),
):
    require_csrf(request, x_csrf_token)
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(request: Request, user=Depends(current_user)):
    return {
        "username": user["username"],
        "full_name": user["full_name"],
        "role": user["role"],
        "role_label": ROLES[user["role"]],
        "scope_name": user["scope_name"],
        "csrf_token": request.session.get("csrf_token"),
    }


@app.get("/api/dashboard")
def dashboard(user=Depends(current_user)):
    rows = load_visible_rows(user)
    plans = get_plans()
    evaluations = []
    for row in rows:
        item = dict(row)
        item["plan"] = plans.get(item["ID"])
        item["plan_status"] = item["plan"]["status"] if item["plan"] else "pendiente"
        item["category"] = category(item)
        item["plan_required"] = item["category"] == "Mala"
        evaluations.append(item)

    summary = {
            "evaluaciones": len(evaluations),
            "malas": sum(item["category"] == "Mala" for item in evaluations),
            "regulares": sum(item["category"] == "Regular" for item in evaluations),
            "buenas": sum(item["category"] == "Buena" for item in evaluations),
            "planes_pendientes": sum(
                item["plan_required"] and not item["plan"] for item in evaluations
            ),
            "franquicias": sum(division_for(item) == "Franquicia" for item in evaluations),
            "sucursales": sum(division_for(item) == "Sucursal" for item in evaluations),
    }
    for key, label in (("malas", "Mala"), ("regulares", "Regular"), ("buenas", "Buena")):
        summary[f"{key}_franquicias"] = sum(
            item["category"] == label and division_for(item) == "Franquicia"
            for item in evaluations
        )
        summary[f"{key}_sucursales"] = sum(
            item["category"] == label and division_for(item) == "Sucursal"
            for item in evaluations
        )
    summary["evaluaciones_franquicias"] = summary["franquicias"]
    summary["evaluaciones_sucursales"] = summary["sucursales"]
    return {"summary": summary, "evaluations": evaluations}


@app.get("/api/attention/{attention_id}/history")
def action_history(attention_id: str, user=Depends(current_user)):
    rows = load_visible_rows(user)
    if not any(row["ID"] == attention_id for row in rows):
        raise HTTPException(status_code=404, detail="Evaluaci\u00f3n no encontrada.")
    return {"transactions": get_plan_history(attention_id)}


@app.put("/api/attention/{attention_id}/plan")
def update_plan(
    attention_id: str,
    body: PlanBody,
    request: Request,
    user=Depends(current_user),
    x_csrf_token: Optional[str] = Header(default=None),
):
    require_csrf(request, x_csrf_token)
    rows = load_visible_rows(user)
    attention = next((row for row in rows if row["ID"] == attention_id), None)
    if not attention:
        raise HTTPException(status_code=404, detail="Evaluación no encontrada.")
    if body.status not in PLAN_STATUSES:
        raise HTTPException(status_code=422, detail="Estado de plan no válido.")
    if not body.plan_text.strip():
        raise HTTPException(status_code=422, detail="Describe el plan de acción.")

    save_plan(
        attention_id=attention_id,
        status=body.status,
        plan_text=body.plan_text.strip(),
        username=user["username"],
    )
    return {"ok": True, "status": body.status}


@app.delete("/api/attention/{attention_id}/plan")
def remove_plan(
    attention_id: str,
    request: Request,
    user=Depends(current_user),
    x_csrf_token: Optional[str] = Header(default=None),
):
    require_csrf(request, x_csrf_token)
    rows = load_visible_rows(user)
    if not any(row["ID"] == attention_id for row in rows):
        raise HTTPException(status_code=404, detail="Evaluaci\u00f3n no encontrada.")
    if not delete_plan(attention_id, user["username"]):
        raise HTTPException(status_code=404, detail="No hay un plan activo para eliminar.")
    return {"ok": True}


@app.get("/api/admin/users")
def admin_users(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Acceso solo para administración.")
    return {
        "roles": [{"value": key, "label": value} for key, value in ROLES.items()],
        "users": [dict(row) for row in list_users()],
    }


@app.post("/api/admin/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserBody,
    request: Request,
    user=Depends(current_user),
    x_csrf_token: Optional[str] = Header(default=None),
):
    require_csrf(request, x_csrf_token)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Acceso solo para administración.")
    if body.role not in ROLES:
        raise HTTPException(status_code=422, detail="Rol no reconocido.")
    scoped_roles = {
        "jefe_comercial_ventas", "jefe_comercial_franquicias", "supervisor"
    }
    if body.role in scoped_roles and not (body.scope_name or "").strip():
        raise HTTPException(status_code=422, detail="Este rol requiere un alcance asignado.")
    try:
        password_hash = hash_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        save_user(
            username=body.username.strip(),
            full_name=body.full_name.strip(),
            password_hash=password_hash,
            role=body.role,
            scope_name=(body.scope_name or "").strip(),
        )
    except Exception as exc:
        logger.info("Could not create user: %s", exc)
        raise HTTPException(status_code=409, detail="Verifica que el usuario no exista.") from exc
    return {"ok": True}
