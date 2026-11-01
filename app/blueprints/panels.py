"""Paneles de contexto sismotectónico por perfil."""

from __future__ import annotations

from flask import Blueprint, abort, jsonify, render_template, request, url_for
from flask_login import login_required

from ..extensions import db
from ..models import Job
from ..services import panels
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


@panels_bp.get("/jobs/<job_id>/paneles")
@login_required
def index(job_id: str):
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)

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

    tipo_titulo = "Todos los tipos" if not tipo else TIPOS_PLURAL.get(tipo, tipo)
    fuente_titulo = (
        "Todas las fuentes"
        if not fuente
        else panels.ETIQUETAS_CATALOGO.get(fuente, fuente)
    )

    volver = _url_panel(job.id, dataset, tipo=tipo, fuente=fuente)
    eventos_vista = []
    for evento in datos["eventos"]:
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
        eventos_vista.append(
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


@panels_bp.get("/jobs/<job_id>/paneles/historico/<perfil_id>")
@login_required
def historico(job_id: str, perfil_id: str):
    """Sismicidad histórica proyectada al perfil, para los mini perfiles."""
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    perfil = panels.perfil_historico(perfil_id)
    if perfil is None:
        abort(404)
    return jsonify(historico_datos(perfil))
