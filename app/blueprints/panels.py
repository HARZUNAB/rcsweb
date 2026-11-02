"""Paneles de contexto sismotectónico por perfil."""

from __future__ import annotations

from io import BytesIO

from flask import (
    Blueprint,
    abort,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Job
from ..security import permiso_requerido, puede_ver_trabajo
from ..services import panels, plots
from ..services.history import datos as historico_datos
from ..services.workspace import ruta_workspace

panels_bp = Blueprint("panels", __name__)

TIPOS_VALIDOS = {"", "no_publicado", "no_actualizado", "repetido"}
FUENTES_VALIDAS = {"", "seiscomp", "seisan", "eventquery"}
FUENTES_ORDEN = ("seiscomp", "seisan", "eventquery")
TIPOS_PLURAL = {
    "no_publicado": "No publicados",
    "no_actualizado": "No actualizados",
    "repetido": "Repetidos",
}


def _url_panel(job_id: str, dataset: str, tipo: str = "", fuente: str = "") -> str:
    parametros = {"job_id": job_id, "dataset": dataset}
    if tipo:
        parametros["tipo"] = tipo
    if fuente:
        parametros["fuente"] = fuente
    return url_for("panels.index", **parametros)


def _job_panel(job_id: str) -> Job:
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    if not puede_ver_trabajo(job, current_user):
        abort(403)
    return job


def _titulo_tipo(tipo: str) -> str:
    return "Todos los tipos" if not tipo else TIPOS_PLURAL.get(tipo, tipo)


def _titulo_fuente(fuente: str) -> str:
    return (
        "Todas las fuentes"
        if not fuente
        else panels.ETIQUETAS_CATALOGO.get(fuente, fuente)
    )


def _leer_panel(job: Job, dataset: str | None = None) -> dict:
    """Dataset y filtros del panel, validados para las vistas de detalle."""
    workspace = ruta_workspace(job.id)
    opciones = panels.datasets_disponibles(workspace)
    if not opciones:
        abort(404)
    claves = [opcion["clave"] for opcion in opciones]
    dataset = dataset or request.args.get("dataset") or claves[0]
    if dataset not in claves:
        abort(404)
    tipo = request.args.get("tipo", "")
    fuente = request.args.get("fuente", "")
    if dataset != "observaciones":
        tipo = ""
        fuente = ""
    if tipo not in TIPOS_VALIDOS:
        tipo = ""
    if fuente not in FUENTES_VALIDAS:
        fuente = ""
    datos = panels.filtrar(
        panels.cargar(workspace, dataset), tipo or None, fuente or None
    )
    titulo = next(
        (opcion["titulo"] for opcion in opciones if opcion["clave"] == dataset),
        dataset,
    )
    return {
        "workspace": workspace,
        "opciones": opciones,
        "dataset": dataset,
        "dataset_titulo": titulo,
        "tipo": tipo,
        "fuente": fuente,
        "datos": datos,
    }


def _eventos_vista(
    job: Job, eventos: list[dict], volver: str
) -> list[dict]:
    vista = []
    for evento in eventos:
        origen = evento.get("origen") or {}
        tabla = origen.get("tabla")
        fila = origen.get("fila")
        url = None
        if tabla and fila is not None:
            url = url_for(
                "results.detalle",
                job_id=job.id,
                tabla=tabla,
                opcion=origen.get("opcion"),
                fila=fila,
                volver=volver,
            )
        vista.append(
            {
                "id": evento["id"],
                "fecha": evento["fecha"],
                "lat": evento["lat"],
                "lon": evento["lon"],
                "perfil": evento["perfil"],
                "analista": evento.get("analista", ""),
                "along_km": evento["along_km"],
                "tipo_observacion": evento["tipo_observacion"],
                "fuente": evento["fuente"],
                "percibido": evento.get("percibido", ""),
                "color": evento.get("color", ""),
                "mag": evento["mag"],
                "prof": evento["prof"],
                "revision": evento["revision"],
                "sospechoso": evento["sospechoso"],
                "territorio": evento["territorio"],
                "url": url,
            }
        )
    return vista


def _evento_core(evento: dict) -> dict:
    return {
        "latitud": evento["lat"],
        "longitud": evento["lon"],
        "prof": evento["prof"],
        "magnitud": evento.get("mag", ""),
        "fecha hora": evento.get("fecha", ""),
        "analista": evento.get("analista", ""),
        "percibido": evento.get("percibido", ""),
        "sospechoso": bool(evento.get("sospechoso")),
        "perfil": evento.get("perfil"),
    }


def _fuente_png(ctx: dict) -> str:
    if ctx["dataset"].startswith("catalogo_"):
        return ctx["dataset"].split("_", 1)[1]
    # Fuente mixta: se identifica como observaciones para no atribuir el grupo
    # completo a una sola fuente en el título del core.
    return "observaciones"


def _fuente_titulo_png(ctx: dict) -> str:
    if ctx["dataset"].startswith("catalogo_"):
        clave = ctx["dataset"].split("_", 1)[1]
        return panels.ETIQUETAS_CATALOGO.get(clave, clave)
    return _titulo_fuente(ctx["fuente"])


def _parametros_grupo(
    job: Job, ctx: dict, grupo: str, ident: str
) -> dict:
    parametros = {
        "job_id": job.id,
        "dataset": ctx["dataset"],
        "grupo": grupo,
        "ident": ident,
    }
    if ctx["tipo"]:
        parametros["tipo"] = ctx["tipo"]
    if ctx["fuente"]:
        parametros["fuente"] = ctx["fuente"]
    return parametros


@panels_bp.get("/jobs/<job_id>/paneles")
@login_required
@permiso_requerido("paneles.ver")
def index(job_id: str):
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    if not puede_ver_trabajo(job, current_user):
        abort(403)

    workspace = ruta_workspace(job.id)
    opciones = panels.datasets_disponibles(workspace)
    if not opciones:
        abort(404)

    claves = [opcion["clave"] for opcion in opciones]
    dataset = request.args.get("dataset") or claves[0]
    if dataset not in claves:
        abort(404)

    datos_completos = panels.cargar(workspace, dataset)
    tipo = request.args.get("tipo", "")
    fuente = request.args.get("fuente", "")
    if dataset != "observaciones":
        tipo = ""
        fuente = ""
    if tipo not in TIPOS_VALIDOS:
        tipo = ""
    if fuente not in FUENTES_VALIDAS:
        fuente = ""

    resumen_conteos = panels.conteos(datos_completos)
    fuentes_tipo = (
        resumen_conteos["fuentes_por_tipo"].get(tipo, {})
        if tipo
        else resumen_conteos["fuentes_todos"]
    )
    # Una fuente o un tipo válidos se conservan aunque no tengan coincidencias:
    # el usuario debe poder abrir la pestaña vacía y ver el aviso, en lugar de
    # volver silenciosamente a "Todas".

    datos = panels.filtrar(datos_completos, tipo or None, fuente or None)

    total_todos = sum(resumen_conteos["tipos"].values())
    if fuente:
        total_todos_fuente = resumen_conteos["fuentes_todos"].get(fuente, 0)
    else:
        total_todos_fuente = total_todos

    tipos_tabs = [
        {
            "clave": "",
            "titulo": "Todos",
            "total": total_todos_fuente,
            "activo": not tipo,
            "url": _url_panel(job.id, dataset, fuente=fuente),
        }
    ]
    for clave, _titulo in panels.TIPOS.items():
        if fuente:
            total = resumen_conteos["fuentes_por_tipo"][clave].get(fuente, 0)
        else:
            total = resumen_conteos["tipos"][clave]
        tipos_tabs.append(
            {
                "clave": clave,
                "titulo": TIPOS_PLURAL.get(clave, clave),
                "total": total,
                "activo": tipo == clave,
                # Siempre clickeable: con 0 se muestra el estado vacío.
                "url": _url_panel(
                    job.id, dataset, tipo=clave, fuente=fuente
                ),
            }
        )

    fuentes_tabs = []
    if dataset == "observaciones":
        fuentes_tabs.append(
            {
                "clave": "",
                "titulo": "Todas",
                "total": sum(fuentes_tipo.values()),
                "activo": not fuente,
                "url": _url_panel(job.id, dataset, tipo=tipo),
            }
        )
        for clave in FUENTES_ORDEN:
            total = fuentes_tipo.get(clave, 0)
            fuentes_tabs.append(
                {
                    "clave": clave,
                    "titulo": panels.ETIQUETAS_CATALOGO.get(clave, clave),
                    "total": total,
                    "activo": fuente == clave,
                    # Eventquery puede tener 0 eventos y aun así debe abrirse.
                    "url": _url_panel(
                        job.id, dataset, tipo=tipo, fuente=clave
                    ),
                }
            )

    tipo_titulo = _titulo_tipo(tipo)
    fuente_titulo = _titulo_fuente(fuente)

    volver = _url_panel(job.id, dataset, tipo=tipo, fuente=fuente)
    eventos_vista = _eventos_vista(job, datos["eventos"], volver)
    datos_vista = {clave: valor for clave, valor in datos.items() if clave != "eventos"}
    datos_vista["eventos"] = eventos_vista

    return render_template(
        "panels/index.html",
        job=job,
        datos=datos_vista,
        opciones=opciones,
        dataset=dataset,
        perfiles_grafico=panels.perfiles_grafico(
            [perfil["id"] for perfil in datos["perfiles"]]
        ),
        tipo_actual=tipo,
        fuente_actual=fuente,
        tipo_titulo=tipo_titulo,
        fuente_titulo=fuente_titulo,
        tipos_tabs=tipos_tabs,
        fuentes_tabs=fuentes_tabs,
        mostrar_filtros=(dataset == "observaciones"),
        # Con 0 eventos no conviene saltar al listado vacío: así el aviso de
        # "No hay eventos" queda a la vista junto al filtro seleccionado.
        scroll_listado=bool((tipo or fuente) and datos["total"]),
        volver=volver,
    )


@panels_bp.get(
    "/jobs/<job_id>/paneles/<dataset>/<grupo>/<ident>/mapa.png"
)
@login_required
@permiso_requerido("paneles.ver")
def grupo_mapa(job_id: str, dataset: str, grupo: str, ident: str):
    """PNG del grupo, con fuente, filtros y conteos, sin listado de eventos."""
    job = _job_panel(job_id)
    if grupo not in ("perfil", "territorio"):
        abort(404)
    ctx = _leer_panel(job, dataset)
    detalle = panels.grupo_eventos(ctx["datos"], grupo, ident)
    if detalle is None:
        abort(404)
    eventos = [_evento_core(evento) for evento in detalle["eventos"]]
    resumen = panels.resumen_grupo_png(
        detalle,
        dataset=ctx["dataset"],
        dataset_titulo=ctx["dataset_titulo"],
        tipo_titulo=_titulo_tipo(ctx["tipo"]),
        fuente_titulo=_fuente_titulo_png(ctx),
        job_id=job.id,
    )
    cache_key = "|".join(
        [
            "v2",
            ctx["dataset"],
            grupo,
            ident,
            ctx["tipo"],
            ctx["fuente"],
            _fuente_png(ctx),
            ",".join(
                f"{evento.get('id', '')}:{evento.get('lat')}:{evento.get('lon')}:"
                f"{evento.get('prof')}"
                for evento in detalle["eventos"]
            ),
        ]
    )
    png = plots.generar_mapa_grupo(
        ctx["workspace"],
        eventos,
        _fuente_png(ctx),
        resumen,
        cache_key,
        modo="auto" if grupo == "perfil" else "planta",
    )
    return send_file(BytesIO(png), mimetype="image/png", max_age=86400)


@panels_bp.get("/jobs/<job_id>/paneles/<dataset>/<grupo>/<ident>")
@login_required
@permiso_requerido("paneles.ver")
def grupo(job_id: str, dataset: str, grupo: str, ident: str):
    """Detalle interactivo de un perfil o de un territorio sin perfil."""
    job = _job_panel(job_id)
    if grupo not in ("perfil", "territorio"):
        abort(404)
    ctx = _leer_panel(job, dataset)
    detalle = panels.grupo_eventos(ctx["datos"], grupo, ident)
    if detalle is None:
        abort(404)

    volver = _url_panel(job.id, ctx["dataset"], ctx["tipo"], ctx["fuente"])
    eventos_vista = _eventos_vista(job, detalle["eventos"], volver)
    datos_vista = {
        "total": len(detalle["eventos"]),
        "con_perfil": sum(1 for e in detalle["eventos"] if e.get("perfil")),
        "sin_perfil": sum(1 for e in detalle["eventos"] if not e.get("perfil")),
        "sospechosos": detalle["resumen"].get("sospechosos", 0),
        "eventos": eventos_vista,
        "perfiles": [detalle["resumen"]] if grupo == "perfil" else [],
        "territorios": [detalle["resumen"]] if grupo == "territorio" else [],
    }
    url_mapa = url_for(
        "panels.grupo_mapa", **_parametros_grupo(job, ctx, grupo, ident)
    )
    return render_template(
        "panels/grupo.html",
        job=job,
        detalle=detalle,
        datos=datos_vista,
        dataset=ctx["dataset"],
        dataset_titulo=ctx["dataset_titulo"],
        tipo_actual=ctx["tipo"],
        fuente_actual=ctx["fuente"],
        tipo_titulo=_titulo_tipo(ctx["tipo"]),
        fuente_titulo=_fuente_titulo_png(ctx),
        mostrar_filtros=(ctx["dataset"] == "observaciones"),
        perfiles_grafico=(
            panels.perfiles_grafico([ident]) if grupo == "perfil" else {}
        ),
        url_mapa=url_mapa,
        volver=volver,
    )


@panels_bp.get("/jobs/<job_id>/paneles/historico/<perfil_id>")
@login_required
@permiso_requerido("paneles.ver")
def historico(job_id: str, perfil_id: str):
    """Sismicidad histórica proyectada al perfil, para los mini perfiles."""
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    if not puede_ver_trabajo(job, current_user):
        abort(403)
    perfil = panels.perfil_historico(perfil_id)
    if perfil is None:
        abort(404)
    return jsonify(historico_datos(perfil))
