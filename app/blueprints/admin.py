"""Administración: auditoría y usuarios."""

from __future__ import annotations

import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import login_required
from sqlalchemy import func

from ..extensions import db
from ..forms import ResetPasswordForm, RolUsuarioForm, UsuarioForm
from ..models import AuditLog, User
from ..security import ETIQUETAS_ROL, permiso_requerido
from ..services.audit import registrar
from ..services.users import (
    UsuarioError,
    actualizar_usuario,
    crear_usuario,
    reset_password,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

PER_PAGE = 50


def _fecha(texto: str, fin: bool = False):
    try:
        valor = datetime.datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    hora = datetime.time(23, 59, 59) if fin else datetime.time.min
    return datetime.datetime.combine(valor, hora, tzinfo=datetime.UTC)


@admin_bp.get("/auditoria")
@login_required
@permiso_requerido("auditoria.ver")
def auditoria():
    accion = request.args.get("accion", "").strip()
    usuario = request.args.get("usuario", "").strip()
    desde = request.args.get("desde", "").strip()
    hasta = request.args.get("hasta", "").strip()
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1

    consulta = db.select(AuditLog)
    if accion:
        consulta = consulta.where(AuditLog.action == accion)
    if usuario:
        encontrado = db.session.execute(
            db.select(User).filter_by(username=usuario)
        ).scalar_one_or_none()
        consulta = consulta.where(AuditLog.user_id == (encontrado.id if encontrado else -1))
    fecha_desde = _fecha(desde)
    fecha_hasta = _fecha(hasta, fin=True)
    if fecha_desde is not None:
        consulta = consulta.where(AuditLog.created_at >= fecha_desde)
    if fecha_hasta is not None:
        consulta = consulta.where(AuditLog.created_at <= fecha_hasta)

    consulta = consulta.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    paginacion = db.paginate(consulta, page=page, per_page=PER_PAGE, error_out=False)

    acciones = (
        db.session.execute(db.select(AuditLog.action).distinct().order_by(AuditLog.action))
        .scalars()
        .all()
    )
    total = db.session.execute(db.select(func.count()).select_from(AuditLog)).scalar_one()

    return render_template(
        "admin/audit.html",
        paginacion=paginacion,
        acciones=acciones,
        total=total,
        accion=accion,
        usuario=usuario,
        desde=desde,
        hasta=hasta,
    )


def _usuario(user_id: int) -> User:
    usuario = db.session.get(User, user_id)
    if usuario is None:
        abort(404)
    return usuario


def _lista_usuarios() -> list[User]:
    return (
        db.session.execute(db.select(User).order_by(User.username))
        .scalars()
        .all()
    )


@admin_bp.get("/usuarios")
@login_required
@permiso_requerido("usuarios.gestionar")
def usuarios():
    return render_template(
        "admin/users.html",
        usuarios=_lista_usuarios(),
        form=UsuarioForm(),
        etiquetas=ETIQUETAS_ROL,
    )


@admin_bp.post("/usuarios/crear")
@login_required
@permiso_requerido("usuarios.gestionar")
def crear_usuario_web():
    form = UsuarioForm()
    if form.validate_on_submit():
        try:
            usuario = crear_usuario(
                form.username.data,
                form.password.data,
                form.role.data,
                active=form.active.data,
                analyst_code=form.analyst_code.data or "",
                analyst_aliases=form.analyst_aliases.data or "",
            )
        except UsuarioError as exc:
            flash(str(exc), "danger")
        else:
            registrar(
                "user.create",
                entity=usuario.username,
                meta={
                    "rol": usuario.role,
                    "activo": usuario.active,
                    "codigo_analista": usuario.analyst_code,
                },
            )
            flash(f"Usuario '{usuario.username}' creado.", "success")
            return redirect(url_for("admin.usuarios"))
    else:
        flash("Revise los datos del usuario.", "warning")

    return render_template(
        "admin/users.html",
        usuarios=_lista_usuarios(),
        form=form,
        etiquetas=ETIQUETAS_ROL,
    )


@admin_bp.get("/usuarios/<int:user_id>")
@login_required
@permiso_requerido("usuarios.gestionar")
def usuario(user_id: int):
    objetivo = _usuario(user_id)
    return render_template(
        "admin/user_detail.html",
        usuario=objetivo,
        rol_form=RolUsuarioForm(obj=objetivo),
        pass_form=ResetPasswordForm(),
        etiquetas=ETIQUETAS_ROL,
    )


@admin_bp.post("/usuarios/<int:user_id>/rol")
@login_required
@permiso_requerido("usuarios.gestionar")
def actualizar_usuario_web(user_id: int):
    objetivo = _usuario(user_id)
    form = RolUsuarioForm()
    if not form.validate_on_submit():
        flash("Revise el rol y el estado del usuario.", "warning")
        return redirect(url_for("admin.usuario", user_id=objetivo.id))

    try:
        actualizar_usuario(
            objetivo,
            form.role.data,
            form.active.data,
            analyst_code=form.analyst_code.data or "",
            analyst_aliases=form.analyst_aliases.data or "",
        )
    except UsuarioError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.usuario", user_id=objetivo.id))

    registrar(
        "user.update",
        entity=objetivo.username,
        meta={
            "rol": objetivo.role,
            "activo": objetivo.active,
            "codigo_analista": objetivo.analyst_code,
        },
    )
    flash(f"Usuario '{objetivo.username}' actualizado.", "success")
    return redirect(url_for("admin.usuario", user_id=objetivo.id))


@admin_bp.post("/usuarios/<int:user_id>/password")
@login_required
@permiso_requerido("usuarios.gestionar")
def reset_password_web(user_id: int):
    objetivo = _usuario(user_id)
    form = ResetPasswordForm()
    if not form.validate_on_submit():
        flash("Revise la nueva contraseña.", "warning")
        return redirect(url_for("admin.usuario", user_id=objetivo.id))

    try:
        reset_password(objetivo, form.new_password.data)
    except UsuarioError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.usuario", user_id=objetivo.id))

    registrar("user.password_reset", entity=objetivo.username)
    flash(
        f"Contraseña de '{objetivo.username}' restablecida.",
        "success",
    )
    return redirect(url_for("admin.usuario", user_id=objetivo.id))
