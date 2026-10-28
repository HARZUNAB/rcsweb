"""Tablas de resultados de un trabajo."""

from __future__ import annotations

from flask import Blueprint, abort, render_template, request, url_for
from flask_login import login_required

from ..extensions import db
from ..models import Job
from ..services.results import (
    NO_ACT_COLUMNS,
    TABLAS,
    cargar_indice,
    leer_tabla,
)
from ..services.workspace import ruta_workspace

results_bp = Blueprint("results", __name__)

TITULOS = {
    "Fecha_Hora": "Fecha y hora",
    "Latitud": "Latitud",
    "Longitud": "Longitud",
    "Prof.": "Prof. (km)",
    "Mag.": "Mag.",
    "Tipo_mag.": "Tipo mag.",
    "Analista": "Analista",
    "Publicado_en": "Publicado en",
    "Estado": "Estado",
    "Dt_otra_seg": "Δt otra fuente (s)",
    "Dist_otra_km": "Dist. otra fuente (km)",
    "Analista_otra": "Analista otra fuente",
    "fecha_hora": "Fecha y hora",
    "latitud": "Latitud",
    "longitud": "Longitud",
    "prof": "Prof. (km)",
    "mag": "Mag.",
    "tipomag": "Tipo mag.",
    "referencia": "Referencia",
    "percibido": "Percibido",
}
TITULOS.update(dict(NO_ACT_COLUMNS))


def _job(job_id: str) -> Job:
    job = db.session.get(Job, job_id)
    if job is None:
        abort(404)
    return job


def titulo_columna(clave: str) -> str:
    if clave in TITULOS:
        return TITULOS[clave]
    return clave.replace("_", " ").strip().capitalize()


@results_bp.get("/jobs/<job_id>/resultados")
@login_required
def overview(job_id: str):
    job = _job(job_id)
    indice = cargar_indice(ruta_workspace(job.id))
    return render_template("results/overview.html", job=job, indice=indice, tablas=TABLAS)


def _render_tabla(job_id: str, clave: str, opcion: str):
    job = _job(job_id)
    config = TABLAS[clave]
    opciones = config["opciones"]
    claves = [c for c, _titulo in opciones]
    if opcion not in claves:
        opcion = claves[0]

    archivo = config["archivo"].format(clave=opcion)
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    direccion = request.args.get("dir", "asc")
    if direccion not in ("asc", "desc"):
        direccion = "asc"
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "").strip()

    tabla = leer_tabla(
        ruta_workspace(job.id),
        archivo,
        q=q,
        sort=sort,
        direccion=direccion,
        page=page,
    )
    columnas = [(c, titulo_columna(c)) for c in tabla["columnas"]]
    artefacto = next((a for a in job.artifacts if a.ruta == f"resultados/{archivo}"), None)
    parametro = "clave" if config["tipo"] == "opciones" else "fuente"
    endpoint = request.endpoint

    def url_tab(otra: str) -> str:
        return url_for(endpoint, job_id=job.id, **{parametro: otra})

    def url_orden(columna: str) -> str:
        nueva = "desc" if tabla["sort"] == columna and tabla["direccion"] == "asc" else "asc"
        return url_for(
            endpoint,
            job_id=job.id,
            **{parametro: opcion},
            q=tabla["q"],
            sort=columna,
            dir=nueva,
        )

    def url_pagina(numero: int) -> str:
        return url_for(
            endpoint,
            job_id=job.id,
            **{parametro: opcion},
            q=tabla["q"],
            sort=tabla["sort"],
            dir=tabla["direccion"],
            page=numero,
        )

    titulo_opcion = dict(opciones)[opcion]

    return render_template(
        "results/table.html",
        job=job,
        clave=clave,
        tabla_config=config,
        opcion=opcion,
        titulo_opcion=titulo_opcion,
        opciones=opciones,
        tabla=tabla,
        columnas=columnas,
        artefacto=artefacto,
        parametro=parametro,
        endpoint=endpoint,
        url_tab=url_tab,
        url_orden=url_orden,
        url_pagina=url_pagina,
    )


@results_bp.get("/jobs/<job_id>/resultados/no-publicados")
@login_required
def no_publicados(job_id: str):
    return _render_tabla(job_id, "no_publicados", request.args.get("fuente", "seiscomp"))


@results_bp.get("/jobs/<job_id>/resultados/no-actualizados")
@login_required
def no_actualizados(job_id: str):
    return _render_tabla(job_id, "no_actualizados", request.args.get("fuente", "seiscomp"))


@results_bp.get("/jobs/<job_id>/resultados/repetidos")
@login_required
def repetidos(job_id: str):
    return _render_tabla(job_id, "repetidos", request.args.get("clave", "publica_amplio"))
