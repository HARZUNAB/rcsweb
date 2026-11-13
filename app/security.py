"""Roles, permisos y decoradores de autorización."""

from __future__ import annotations

from functools import wraps

from flask import abort
from flask_login import current_user, login_required

# Permisos de la aplicación. Los de alcance («todos») separan al administrador y
# al supervisor del analista, que solo puede operar sobre lo que creó.
PERMISOS = (
    "trabajos.ver",
    "trabajos.crear",
    "trabajos.cancelar",
    "trabajos.eliminar",
    "trabajos.descargar",
    "trabajos.todos",
    "solicitudes.ver",
    "solicitudes.crear",
    "solicitudes.gestionar",
    "solicitudes.todas",
    "paneles.ver",
    "catalogos.ver",
    "resultados.ver",
    "resultados.exportar",
    "revisiones.ver",
    "revisiones.crear",
    "revisiones.responder",
    "auditoria.ver",
    "usuarios.gestionar",
)

_OPERATIVOS = frozenset(
    {
        "trabajos.ver",
        "trabajos.crear",
        "trabajos.cancelar",
        "trabajos.eliminar",
        "trabajos.descargar",
        "solicitudes.ver",
        "solicitudes.crear",
        "solicitudes.gestionar",
        "paneles.ver",
        "catalogos.ver",
        "resultados.ver",
        "resultados.exportar",
        "revisiones.ver",
        "revisiones.responder",
    }
)

ROLES = {
    "admin": frozenset(PERMISOS),
    # El supervisor hace toda la operación y ve la auditoría, pero no administra
    # cuentas ni contraseñas.
    "supervisor": frozenset(PERMISOS) - {"usuarios.gestionar"},
    "analista": _OPERATIVOS,
    # Observador global: ve todo el sistema en modo lectura, sin exportar ni
    # descargar resultados. Sí puede descargar catálogos desde Catálogos.
    "observador": frozenset(
        {
            "trabajos.ver",
            "trabajos.todos",
            "paneles.ver",
            "catalogos.ver",
            "resultados.ver",
        }
    ),
    # Rol de extracción: solicita catálogos y accede solo a la sección de
    # catálogos de los trabajos que generan sus solicitudes.
    "catalogos": frozenset(
        {
            "trabajos.ver",
            "catalogos.ver",
            "solicitudes.ver",
            "solicitudes.crear",
        }
    ),
}

ETIQUETAS_ROL = {
    "admin": "Administrador",
    "supervisor": "Supervisor",
    "analista": "Analista",
    "observador": "Observador",
    "catalogos": "Catálogos",
}

ROLES_VALIDOS = tuple(ROLES)


def etiqueta_rol(rol: str | None) -> str:
    """Nombre legible del rol, o el valor crudo si es desconocido."""
    return ETIQUETAS_ROL.get(rol or "", rol or "")


def tiene_permiso(usuario, permiso: str) -> bool:
    """True si el usuario tiene el permiso; el administrador tiene todos."""
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return False
    rol = getattr(usuario, "role", None)
    if rol == "admin":
        return True
    return permiso in ROLES.get(rol, frozenset())


def alcance_total(usuario) -> bool:
    """True si puede operar sobre trabajos/solicitudes de cualquier usuario."""
    return tiene_permiso(usuario, "trabajos.todos")


def puede_ver_trabajo(job, usuario) -> bool:
    """Admin/supervisor ven todo; el resto solo lo que creó."""
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return False
    return alcance_total(usuario) or job.created_by_id == getattr(usuario, "id", None)


def puede_ver_solicitud(solicitud, usuario) -> bool:
    """Misma regla de propiedad para las solicitudes de catálogos."""
    if usuario is None or not getattr(usuario, "is_authenticated", False):
        return False
    return (
        alcance_total(usuario)
        or solicitud.requested_by_id == getattr(usuario, "id", None)
    )


def permiso_requerido(permiso: str):
    """Exige sesión iniciada y el permiso indicado."""

    def decorador(func):
        @wraps(func)
        @login_required
        def envoltura(*args, **kwargs):
            if not tiene_permiso(current_user, permiso):
                abort(403)
            return func(*args, **kwargs)

        return envoltura

    return decorador


def admin_required(func):
    """Compatibilidad: acceso exclusivo de administradores."""
    return permiso_requerido("usuarios.gestionar")(func)
