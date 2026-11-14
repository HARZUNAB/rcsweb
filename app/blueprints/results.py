"""Tablas de resultados, detalle y exportación."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import zipfile
from datetime import datetime
from io import BytesIO, StringIO
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from tasks.amplification import ampliar_sin_arribos
from tasks.availability import consultar_disponibilidad
from tasks.celery_app import celery

from ..domain.catalogs import canonical
from ..domain.catalogs import manifest as fuentes_manifest
from ..extensions import db
from ..models import Job, utcnow
from ..security import permiso_requerido, puede_ver_trabajo, tiene_permiso
from ..services import (
    amplification,
    availability,
    catalog_export,
    colores,
    formatting,
    indicios,
    panels,
    review,
    review_reports,
)
from ..services.analysts import (
    campos_analista,
    codigos_usuario,
    evento_visible,
    usuario_de_fila,
    usuario_restringido,
)
from ..services.attribution import indices_atribucion, texto_analista_probable
from ..services.audit import registrar
from ..services.borders import mapa_fila, texto_frontera_coords
from ..services.detail import (
    clave_evento,
    construir_detalle,
    leer_filas,
    leyenda_detalle,
    puntos_mapa,
    superpuestos,
)
from ..services.history import datos as historico_datos
from ..services.maps import modo_mapa
from ..services.plots import (
    clasificar_eventos,
    generar_mapa,
    generar_miniatura,
    marcar_sospechosos,
    perfil_desde_eventos,
    resumen_mapa,
)
from ..services.results import (
    NO_ACT_COLUMNS,
    TABLAS,
    cargar_indice,
    claves_frontera,
    exportar_csv,
    leer_tabla,
    rep_files,
    rep_grupos,
)
from ..services.results import (
    exportar_seleccionados as exportar_seleccionados_csv,
)
from ..services.station_review import (
    filas_para_csv,
    filas_visibles,
    fuente_de_fila,
    resolver_evento,
    revisar_fila,
    seleccionar_disponibilidad,
)
from ..services.ubicacion import clasificar as clasificar_ubicacion
from ..services.workspace import ruta_workspace

results_bp = Blueprint("results", __name__)

ENDPOINTS = {
    "no_publicados": "results.no_publicados",
    "no_actualizados": "results.no_actualizados",
    "repetidos": "results.repetidos",
    "catalogos": "results.catalogos",
}

PARAMETROS = {
    "no_publicados": "fuente",
    "no_actualizados": "fuente",
    "repetidos": "clave",
    "catalogos": "catalogo",
}

TITULOS = {
    "Fecha_Hora": "Fecha y hora",
    "Latitud": "Latitud",
    "Longitud": "Longitud",
    "Prof.": "Prof. (km)",
    "Mag.": "Mag.",
    "Tipo_mag.": "Tipo mag.",
    "Analista": "Analista",
    "Publicado_en": "Publicado en otra fuente",
    "Estado": "Estado",
    "Dt_otra_seg": "Δt otra fuente (s)",
    "Dist_otra_km": "Dist. otra fuente (km)",
    "Analista_otra": "Analista otra fuente",
    "Frontera": "Frontera más cercana",
    "Referencia": "Referencia",
    "Percep.": "Percibido",
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
    if not puede_ver_trabajo(job, current_user):
        abort(403)
    return job


def _fuentes_job(job: Job) -> list[str]:
    """Fuentes locales del trabajo, principal primero."""
    locales = {definicion.id: definicion for definicion in fuentes_manifest.locales()}
    pares: list[tuple[str, str]] = []
    for source in job.sources:
        if source.kind in locales:
            pares.append((source.role, source.kind))
    if not pares:
        vistos = set()
        for archivo in job.files:
            if archivo.kind not in locales or archivo.kind in vistos:
                continue
            vistos.add(archivo.kind)
            rol = (
                "local_principal"
                if archivo.kind == fuentes_manifest.default_primary()
                else "local_secundaria"
            )
            pares.append((rol, archivo.kind))
    if not pares:
        # Compatibilidad con trabajos viejos sin job_sources: inferir desde los
        # archivos de resultados ya generados.
        base = ruta_workspace(job.id) / "resultados"
        codigos = set()
        for patron in ("no_publicados_*.csv", "no_actualizados_*.csv"):
            for ruta in base.glob(patron):
                codigo = ruta.stem.split("_", 2)[-1]
                if codigo in locales:
                    codigos.add(codigo)
        for ruta in base.glob("repetidos_*.csv"):
            partes = ruta.stem.split("_")
            if len(partes) > 1 and partes[1] != "publica":
                codigo = partes[1]
                if codigo in locales:
                    codigos.add(codigo)
        predeterminada = fuentes_manifest.default_primary()
        pares = [
            (
                "local_principal" if codigo == predeterminada else "local_secundaria",
                codigo,
            )
            for codigo in codigos
        ]
    if not pares:
        # Último recurso: índice de resultados.
        indice = cargar_indice(ruta_workspace(job.id))
        codigos = set(indice.get("no_publicados", {})) | set(indice.get("no_actualizados", {}))
        referencia = fuentes_manifest.referencia().id
        for clave in indice.get("repetidos", {}):
            if clave.startswith(referencia) or clave.startswith("publica"):
                continue
            codigo = clave.split("_", 1)[0]
            if codigo in locales:
                codigos.add(codigo)
        predeterminada = fuentes_manifest.default_primary()
        pares = [
            (
                "local_principal" if codigo == predeterminada else "local_secundaria",
                codigo,
            )
            for codigo in codigos
        ]
    pares.sort(key=lambda item: 0 if item[0] == "local_principal" else 1)
    return [kind for _rol, kind in pares]


def _alias(job: Job, codigo: str) -> str:
    for source in job.sources:
        if source.kind == codigo:
            return source.alias_mostrado
    return fuentes_manifest.etiqueta(codigo)


def _opciones(tabla: str, job: Job) -> list[tuple[str, str]]:
    if tabla == "catalogos":
        indice = cargar_indice(ruta_workspace(job.id))
        disponibles = indice.get("catalogos") or {}
        orden = [
            definicion.id
            for definicion in fuentes_manifest.fuentes()
            if definicion.id in disponibles
        ]
        return [(clave, fuentes_manifest.etiqueta(clave)) for clave in orden]
    fuentes = _fuentes_job(job)
    if tabla == "repetidos":
        labels = {codigo: _alias(job, codigo) for codigo in fuentes}
        return [(clave, titulo) for clave, _archivo, titulo in rep_files(fuentes, labels)]
    return [(codigo, _alias(job, codigo)) for codigo in fuentes]


def _archivo_tabla(tabla: str, opcion: str, job: Job) -> str | None:
    """Ruta del CSV de la tabla, relativa al workspace.

    Los catálogos viven en ``datos/`` y se resuelven por el índice; las tablas
    derivadas usan el nombre declarado en ``TABLAS``.
    """
    if tabla == "catalogos":
        indice = cargar_indice(ruta_workspace(job.id))
        info = (indice.get("catalogos") or {}).get(opcion)
        return info.get("archivo") if info else None
    return TABLAS[tabla]["archivo"].format(clave=opcion)


def _orden_numerico(valor) -> float:
    """Convierte un valor formateado (``<0.01``, ``+7.27``) en número."""
    texto = str(valor or "").strip().lstrip("<>=+ ")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _fecha_orden(valor) -> float:
    try:
        return datetime.fromisoformat(
            str(valor or "").replace("Z", "")
        ).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _clasificacion_sospechoso(workspace, fuente: str, fila_catalogo) -> dict | None:
    """Reutiliza la clasificación de localización de los módulos existentes."""
    info = (cargar_indice(workspace).get("catalogos") or {}).get(fuente)
    if not info:
        return None
    archivo = info.get("archivo")
    leido = leer_filas(workspace, archivo)
    if leido is None:
        return None
    _columnas, filas = leido
    try:
        indice_fila = int(fila_catalogo)
    except (TypeError, ValueError):
        return None
    if indice_fila < 0 or indice_fila >= len(filas):
        return None
    eventos, perfil = clasificar_eventos(
        "catalogos",
        archivo,
        filas,
        indice_fila,
        opcion=fuente,
    )
    if not eventos:
        return None
    evento = eventos[0]
    return {
        "sospechoso": bool(evento.get("sospechoso")),
        "residuo_km": evento.get("residuo_km"),
        "perp_km": evento.get("perp_km"),
        "along_km": evento.get("along_km"),
        "perfil": (perfil or {}).get("id", "") if perfil else "",
    }


def _bool_desde_texto(valor) -> bool | None:
    if valor == "Sí":
        return True
    if valor == "No":
        return False
    return None


def _fila_sospechosa(
    evento: dict,
    fuente: str,
    fila_catalogo,
    publicado,
    evaluacion: dict | None = None,
) -> dict:
    """Fila de revisión para un evento sospechoso sin indicios de fase."""
    evaluacion = evaluacion or {}
    n_usadas = evaluacion.get("n_usadas")
    n_disponibles = evaluacion.get("n_disponibles")
    contexto = evaluacion.get("contexto") or ""
    max_residual = evaluacion.get("max_residual_usado")
    if not n_usadas and not n_disponibles:
        n_usadas = ""
        n_disponibles = ""
        contexto = ""
        max_residual = ""
    return {
        "fuente": fuente,
        "evento": evento.get("event_id") or "",
        "id_evento_fuente": evento.get("source_event_id") or "",
        "fecha_hora": evento.get("event_time") or "",
        "magnitud": formatting.numero(evento.get("magnitude"), 1),
        "region": (evento.get("raw") or {}).get("region", ""),
        "analista": evento.get("analyst") or "",
        "fila_catalogo": fila_catalogo,
        "publicado": "Sí" if publicado else ("No" if publicado is False else ""),
        "sospechoso": "Sí",
        "sospechoso_residuo_km": None,
        "anomalia": False,
        "fuerza": "",
        "patron": "sin_fase",
        "contexto": contexto,
        "extremo": "",
        "n_disponibles": n_disponibles or "",
        "inventario_disponible": evaluacion.get(
            "inventario_disponible", ""
        ),
        "n_usadas": n_usadas or "",
        "azimutal_gap": evaluacion.get("azimutal_gap", ""),
        "max_residual_usado": max_residual or "",
        "n_outliers": 0,
        "n_fuera_de_orden": 0,
        "n_fuera_de_orden_debiles": 0,
        "n_picks_antes_origen": 0,
        "tipos_indicio": "solución_sospechosa",
        "resumen": "Solución sospechosa",
        "motivo": "sospechosa",
        "revision_prioritaria": "No",
        "prioridad": "Informativa",
        "prioridad_orden": 2,
    }


def _registros_por_evento(registros: list[dict]) -> dict[str, list[dict]]:
    """Agrupa arribos o estaciones por identificador de evento."""
    agrupados: dict[str, list[dict]] = {}
    for registro in registros:
        clave = str(
            registro.get("event_id")
            or registro.get("source_event_id")
            or ""
        ).strip()
        if clave:
            agrupados.setdefault(clave, []).append(registro)
    return agrupados


def _filas_sospechosas_sin_fase(
    workspace,
    fuente: str,
    filas_fase: list[dict],
) -> list[dict]:
    """Eventos publicados con solución sospechosa y sin indicio de fase.

    Se leen de la caché de paneles, que ya tiene la clasificación de todo el
    catálogo. Solo se agregan los publicados: los sospechosos no publicados sin
    fase son calidad de catálogo y quedan en los paneles.
    """
    if not fuente:
        return []
    try:
        datos = panels.cargar(workspace, f"catalogo_{fuente}")
    except Exception:
        current_app.logger.exception(
            "No se pudo leer la clasificación de solución para %s", fuente
        )
        return []
    ya_en_fase = {
        str(fila.get("fila_catalogo"))
        for fila in filas_fase
        if fila.get("fila_catalogo") not in (None, "")
    }
    eventos = {
        str(evento.get("raw_index")): evento
        for evento in canonical.leer_canonico(workspace, fuente)
    }
    arribos = None
    sin_arribos = None
    indice = indicios.indice_publicados(workspace, fuente)
    filas = []
    for evento_panel in datos.get("eventos", []):
        origen = evento_panel.get("origen") or {}
        if origen.get("tabla") != "catalogos" or origen.get("opcion") != fuente:
            continue
        if not evento_panel.get("sospechoso"):
            continue
        fila_catalogo = origen.get("fila")
        if fila_catalogo is None or str(fila_catalogo) in ya_en_fase:
            continue
        evento = eventos.get(str(fila_catalogo))
        if not evento:
            continue
        publicado = indicios.estado_publicado(
            workspace, fuente, evento, indice=indice
        )
        if publicado is not True:
            continue
        if arribos is None or sin_arribos is None:
            arribos = _registros_por_evento(
                canonical.leer_arribos(workspace, fuente)
            )
            sin_arribos = _registros_por_evento(
                canonical.leer_estaciones_sin_arribos(workspace, fuente)
            )
        event_id = str(evento.get("event_id") or "")
        evaluacion = indicios.evaluar_evento(
            evento,
            arribos.get(event_id, []),
            sin_arribos.get(event_id, []),
            source_id=fuente,
            publicado=True,
            sospechoso=True,
            perfil_disponible=bool(evento_panel.get("perfil")),
        )
        filas.append(
            _fila_sospechosa(
                evento,
                fuente,
                fila_catalogo,
                publicado,
                evaluacion=evaluacion,
            )
        )
    return filas


def _filtros() -> dict[str, str]:
    """Filtros activos, incluidos rangos compactos y la compatibilidad min/max."""
    textos: dict[str, str] = {}
    rangos: dict[str, dict[str, str]] = {}
    for clave, valor in request.args.items():
        if not clave.startswith("f_"):
            continue
        limpio = valor.strip()
        if not limpio:
            continue
        nombre = clave[2:]
        if nombre.endswith("_min"):
            rangos.setdefault(nombre[:-4], {})["min"] = limpio
        elif nombre.endswith("_max"):
            rangos.setdefault(nombre[:-4], {})["max"] = limpio
        else:
            textos[nombre] = limpio
    for columna, rango in rangos.items():
        minimo = rango.get("min", "").strip()
        maximo = rango.get("max", "").strip()
        if minimo and maximo:
            textos[columna] = f"{minimo}..{maximo}"
        elif minimo:
            textos[columna] = (
                minimo
                if minimo.startswith((">=", "<=", ">", "<", "="))
                else f">={minimo}"
            )
        elif maximo:
            textos[columna] = (
                maximo
                if maximo.startswith((">=", "<=", ">", "<", "="))
                else f"<={maximo}"
            )
    return textos


def _rangos_de_filtros(filtros: dict[str, str]) -> dict[str, dict[str, str]]:
    """Separa los filtros combinados en mínimo y máximo para la plantilla."""
    rangos: dict[str, dict[str, str]] = {}
    for clave, patron in filtros.items():
        if ".." in patron:
            minimo, maximo = patron.split("..", 1)
            rangos[clave] = {"min": minimo.strip(), "max": maximo.strip()}
        elif patron.startswith(">="):
            rangos[clave] = {"min": patron[2:].strip(), "max": ""}
        elif patron.startswith("<="):
            rangos[clave] = {"min": "", "max": patron[2:].strip()}
        elif patron.startswith(">"):
            rangos[clave] = {"min": patron, "max": ""}
        elif patron.startswith("<"):
            rangos[clave] = {"min": "", "max": patron}
        elif patron.startswith("="):
            valor = patron[1:].strip()
            rangos[clave] = {"min": valor, "max": valor}
        else:
            rangos[clave] = {"min": patron, "max": patron}
    return rangos


def _opcion_valida(tabla: str, job: Job) -> tuple[dict, list[tuple[str, str]], str]:
    if tabla not in TABLAS:
        abort(404)
    config = TABLAS[tabla]
    opciones = _opciones(tabla, job)
    if not opciones:
        abort(404)
    claves = [clave for clave, _titulo in opciones]
    parametro = PARAMETROS[tabla]
    opcion = request.args.get(parametro) or (
        request.args.get("clave") or request.args.get("fuente") or claves[0]
    )
    if opcion not in claves:
        abort(404)
    return config, opciones, opcion


def titulo_columna(clave: str) -> str:
    if clave in TITULOS:
        return TITULOS[clave]
    if clave.startswith("analista_"):
        codigo = clave[len("analista_") :]
        etiqueta = fuentes_manifest.etiqueta(codigo)
        if etiqueta != codigo:
            return f"Analista probable ({etiqueta})"
    return clave.replace("_", " ").strip().capitalize()


@results_bp.get("/jobs/<job_id>/resultados")
@login_required
@permiso_requerido("resultados.ver")
def overview(job_id: str):
    job = _job(job_id)
    return redirect(url_for("jobs.detalle", job_id=job.id) + "#resultados")


def _filas_revision(workspace, fuente, usuario) -> list[dict]:
    """Filas de revisión: fase, solución, prioridad y visibilidad."""
    filas = indicios.leer_indicios(workspace, fuente) if fuente else []
    for fila in filas:
        clasificacion = _clasificacion_sospechoso(
            workspace, fuente, fila.get("fila_catalogo")
        )
        if clasificacion:
            fila["sospechoso"] = "Sí" if clasificacion["sospechoso"] else "No"
            fila["sospechoso_residuo_km"] = clasificacion["residuo_km"]
            fila["sospechoso_perp_km"] = clasificacion["perp_km"]
        fila["motivo"] = "ambas" if fila.get("sospechoso") == "Sí" else "fase"

    filas.extend(_filas_sospechosas_sin_fase(workspace, fuente, filas))

    for fila in filas:
        publicado = _bool_desde_texto(fila.get("publicado"))
        sospechoso = _bool_desde_texto(fila.get("sospechoso"))
        prioridad = indicios.prioridad_evento(
            publicado, fila.get("fuerza") or "", sospechoso
        )
        fila["prioridad"] = prioridad
        fila["prioridad_orden"] = indicios.ORDEN_PRIORIDAD[prioridad]
        fila["revision_prioritaria"] = (
            "Sí" if prioridad in ("Alta", "Media") else "No"
        )
        fila["_sospechoso_orden"] = {
            "Sí": 2,
            "No": 1,
        }.get(fila.get("sospechoso"), 0)
        fila["_fecha_orden"] = _fecha_orden(fila.get("fecha_hora"))

    if usuario_restringido(usuario):
        filas = [fila for fila in filas if evento_visible(fila, usuario)]
    return filas


@results_bp.get("/jobs/<job_id>/indicios")
@login_required
@permiso_requerido("resultados.ver")
def indicios_eventos(job_id: str):
    """Listado de eventos con indicios de anomalías en las fases."""
    job = _job(job_id)
    workspace = ruta_workspace(job.id)
    fuentes = _fuentes_job(job)
    resumen = indicios.asegurar_indicios(workspace, fuentes, job_id=job.id)

    fuente = request.args.get("fuente", "").strip()
    if fuente not in fuentes:
        fuente = fuentes[0] if fuentes else ""
    alcance = request.args.get("alcance", "prioritarios").strip()
    if alcance not in ("prioritarios", "publicados", "todos"):
        alcance = "prioritarios"

    puede_crear_revision = tiene_permiso(current_user, "revisiones.crear")
    analistas = review.usuarios_analistas() if puede_crear_revision else []
    analista_sel = request.args.get("analista", "").strip()
    analista_id: int | str | None = None
    analista_fuente = ""
    if analista_sel == "sin":
        analista_id = "sin"
    elif analista_sel.startswith("fuente:"):
        analista_fuente = analista_sel[len("fuente:") :].strip()
    elif analista_sel:
        try:
            analista_id = int(analista_sel)
        except ValueError:
            analista_id = None
    max_eventos = int(
        current_app.config.get("RCS_INFORME_MAX_EVENTOS", 50) or 50
    )
    analista_nombre = next(
        (a.username for a in analistas if a.id == analista_id), ""
    )

    filas = _filas_revision(workspace, fuente, current_user)

    if analistas:
        for fila in filas:
            usuario = usuario_de_fila(fila, analistas)
            fila["analista_usuario_id"] = (
                usuario.id if usuario is not None else None
            )
    analistas_fuente = sorted(
        {
            str(fila.get("analista")).strip()
            for fila in filas
            if str(fila.get("analista") or "").strip()
            and not fila.get("analista_usuario_id")
        }
    )
    if analista_fuente:
        analista_nombre = analista_fuente
        filas = [
            fila
            for fila in filas
            if str(fila.get("analista") or "").strip() == analista_fuente
        ]
    elif analista_id == "sin":
        filas = [
            fila
            for fila in filas
            if fila.get("analista_usuario_id") is None
        ]
    elif analista_id is not None:
        filas = [
            fila
            for fila in filas
            if fila.get("analista_usuario_id") == analista_id
        ]

    solicitudes_evento = (
        review.mapa_solicitudes(job.id, fuente) if fuente else {}
    )
    for fila in filas:
        fila["solicitud_info"] = solicitudes_evento.get(fila.get("evento"))

    info_fuente = dict((resumen or {}).get("fuentes", {}).get(fuente, {}))
    info_fuente["con_anomalia_fuerte"] = sum(
        1 for fila in filas if fila.get("fuerza") == "fuerte"
    )
    info_fuente["con_anomalia_debil"] = sum(
        1 for fila in filas if fila.get("fuerza") == "débil"
    )
    info_fuente["con_anomalia"] = (
        info_fuente["con_anomalia_fuerte"]
        + info_fuente["con_anomalia_debil"]
    )
    info_fuente["revision_prioritaria"] = sum(
        1 for fila in filas if fila["revision_prioritaria"] == "Sí"
    )
    info_fuente["publicados"] = sum(
        1 for fila in filas if fila.get("publicado") == "Sí"
    )

    if alcance == "prioritarios":
        filas = [
            fila for fila in filas if fila["revision_prioritaria"] == "Sí"
        ]
    elif alcance == "publicados":
        filas = [fila for fila in filas if fila.get("publicado") == "Sí"]

    filas.sort(
        key=lambda fila: (
            -fila["prioridad_orden"],
            -fila["_sospechoso_orden"],
            -_orden_numerico(fila.get("max_residual_usado")),
            -fila["_fecha_orden"],
        )
    )

    volver = request.full_path.rstrip("?")
    archivo_catalogo = _archivo_tabla("catalogos", fuente, job) if fuente else None
    catalogo_disponible = bool(
        archivo_catalogo and (workspace / archivo_catalogo).is_file()
    )
    for fila in filas:
        try:
            indice_fila = int(fila.get("fila_catalogo") or "")
        except (TypeError, ValueError):
            indice_fila = None
        fila["url_detalle"] = (
            url_for(
                "results.detalle",
                job_id=job.id,
                tabla="catalogos",
                opcion=fuente,
                fila=indice_fila,
                volver=volver,
                volver_etiqueta="Volver a la revisión",
            )
            + "#indicios-fases"
            if catalogo_disponible and indice_fila is not None
            else ""
        )

    etiquetas = {codigo: _alias(job, codigo) for codigo in fuentes}
    return render_template(
        "results/indicios.html",
        job=job,
        resumen=resumen or {},
        fuentes=fuentes,
        etiquetas=etiquetas,
        fuente=fuente,
        alcance=alcance,
        filas=filas,
        analistas=analistas,
        analista_id=analista_id,
        analista_fuente=analista_fuente,
        analistas_fuente=analistas_fuente,
        analista_nombre=analista_nombre,
        puede_crear_revision=puede_crear_revision,
        puede_ver_revisiones=tiene_permiso(current_user, "revisiones.ver"),
        max_eventos=max_eventos,
        info_fuente=info_fuente,
        volver=volver,
    )


@results_bp.post("/jobs/<job_id>/indicios/revision")
@login_required
@permiso_requerido("revisiones.crear")
def solicitar_revision(job_id: str):
    """Encola la generación del PDF y la creación de la solicitud."""
    job = _job(job_id)
    workspace = ruta_workspace(job.id)
    fuente = request.form.get("fuente", "").strip()
    formato = request.form.get("formato", "pdf").strip().lower()
    nota = request.form.get("nota", "").strip()
    if fuente not in _fuentes_job(job) or formato not in ("pdf", "docx"):
        return jsonify({"error": "Datos de la solicitud inválidos."}), 400

    try:
        ids = sorted(
            {
                int(valor)
                for valor in request.form.getlist("eventos")
                if str(valor).strip()
            }
        )
    except ValueError:
        return jsonify({"error": "Selección de eventos inválida."}), 400

    max_eventos = int(
        current_app.config.get("RCS_INFORME_MAX_EVENTOS", 50) or 50
    )
    if not ids:
        return jsonify({"error": "Seleccione al menos un evento."}), 400
    if len(ids) > max_eventos:
        return (
            jsonify(
                {
                    "error": (
                        f"Máximo {max_eventos} eventos por solicitud."
                    )
                }
            ),
            400,
        )

    filas = _filas_revision(workspace, fuente, current_user)
    por_fila = {
        int(fila["fila_catalogo"]): fila
        for fila in filas
        if fila.get("fila_catalogo") not in (None, "")
    }
    seleccionadas = [por_fila[indice] for indice in ids if indice in por_fila]
    if len(seleccionadas) != len(ids):
        return (
            jsonify(
                {
                    "error": (
                        "Alguno de los eventos seleccionados ya no está "
                        "en la revisión."
                    )
                }
            ),
            400,
        )

    analistas = review.usuarios_analistas()
    asignados = {
        usuario_de_fila(fila, analistas).id
        if usuario_de_fila(fila, analistas) is not None
        else None
        for fila in seleccionadas
    }
    if len(asignados) != 1 or None in asignados:
        return (
            jsonify(
                {
                    "error": (
                        "Seleccione eventos de un solo analista con "
                        "usuario activo."
                    )
                }
            ),
            400,
        )
    asignado = next(iter(asignados))

    conflictos = review.conflictos(
        job.id, fuente, [fila["evento"] for fila in seleccionadas]
    )
    if conflictos:
        detalle = "; ".join(
            f"{conflicto['evento']} → solicitud "
            f"#{conflicto['solicitud_id']} ({conflicto['estado']})"
            for conflicto in conflictos
        )
        return (
            jsonify(
                {
                    "error": (
                        "Estos eventos ya están en revisión: " + detalle
                    )
                }
            ),
            409,
        )

    report_id = uuid4().hex
    estado = {
        "job_id": job.id,
        "user_id": current_user.id,
        "assigned_to_id": asignado,
        "fuente": fuente,
        "formato": formato,
        "nota": nota,
        "notified_at": utcnow().isoformat(),
        "base_url": request.host_url.rstrip("/"),
        "filas": [
            {
                clave: fila.get(clave)
                for clave in (
                    "evento",
                    "id_evento_fuente",
                    "fila_catalogo",
                    "fecha_hora",
                    "magnitud",
                    "analista",
                    "prioridad",
                    "motivo",
                    "fuerza",
                    "patron",
                    "contexto",
                    "n_usadas",
                    "max_residual_usado",
                    "sospechoso",
                    "sospechoso_residuo_km",
                    "sospechoso_perp_km",
                )
            }
            for fila in seleccionadas
        ],
        "estado": "en_cola",
        "progreso": 0,
        "paso": "Encolando…",
    }
    try:
        review_reports.guardar_estado(report_id, estado)
        from tasks.reports import generar_informe_revision

        generar_informe_revision.delay(report_id)
    except Exception as exc:  # noqa: BLE001 - Redis o Celery no disponibles
        review_reports.borrar_estado(report_id)
        return (
            jsonify({"error": f"No se pudo encolar la solicitud: {exc}"}),
            503,
        )

    registrar(
        "revision.solicitar",
        f"job:{job.id}",
        {
            "fuente": fuente,
            "eventos": ids,
            "formato": formato,
            "asignado": asignado,
            "report_id": report_id,
        },
    )
    return jsonify({"report_id": report_id})


@results_bp.get(
    "/jobs/<job_id>/indicios/revision/<report_id>/estado"
)
@login_required
@permiso_requerido("revisiones.crear")
def estado_solicitud_revision(job_id: str, report_id: str):
    job = _job(job_id)
    estado = review_reports.leer_estado(report_id)
    if (
        not estado
        or estado.get("job_id") != job.id
        or estado.get("user_id") != current_user.id
    ):
        abort(404)
    return jsonify(
        {
            "estado": estado.get("estado", ""),
            "progreso": estado.get("progreso", 0),
            "paso": estado.get("paso", ""),
            "error": estado.get("error", ""),
            "aviso": estado.get("aviso", ""),
            "formato": estado.get("formato", ""),
            "url_solicitud": estado.get("url_solicitud", ""),
        }
    )


def _render_tabla(job_id: str, tabla: str, opcion: str):
    job = _job(job_id)
    config, opciones, opcion = _opcion_valida(tabla, job)
    if request.args.get(PARAMETROS[tabla]):
        # La opción explícita ya fue validada en _opcion_valida.
        opcion = request.args.get(PARAMETROS[tabla])

    archivo = _archivo_tabla(tabla, opcion, job)
    if not archivo:
        abort(404)
    try:
        page = max(1, int(request.args.get("page", "1")))
    except ValueError:
        page = 1
    direccion = request.args.get("dir", "asc")
    if direccion not in ("asc", "desc"):
        direccion = "asc"
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "").strip()
    filtros = _filtros()
    restringido = usuario_restringido(current_user)
    catalogo_restringido = restringido and tabla == "catalogos"
    if catalogo_restringido and not codigos_usuario(current_user):
        abort(403)
    ocultas = campos_analista() if catalogo_restringido else None
    if ocultas:
        filtros = {
            clave: valor
            for clave, valor in filtros.items()
            if clave not in ocultas
        }
        if sort in ocultas:
            sort = ""

    tabla_datos = leer_tabla(
        ruta_workspace(job.id),
        archivo,
        q=q,
        filtros=filtros,
        sort=sort,
        direccion=direccion,
        page=page,
        predicado=(
            (lambda fila: evento_visible(fila, current_user))
            if restringido and not catalogo_restringido
            else None
        ),
        columnas_ocultas_busqueda=ocultas,
    )
    filtros = tabla_datos["filtros"]
    tabla_datos["rangos"] = _rangos_de_filtros(filtros)
    columnas = [(columna, titulo_columna(columna)) for columna in tabla_datos["columnas"]]
    if catalogo_restringido:
        columnas = [
            (columna, titulo)
            for columna, titulo in columnas
            if columna not in ocultas
        ]
    claves_mapa = claves_frontera(tabla_datos["columnas"])
    if tabla == "repetidos":
        fuente_mapa = _fuente_de_repetidos(opcion)
    else:
        fuente_mapa = opcion
    es_referencia = fuente_mapa == "publica" or fuentes_manifest.es_referencia(
        fuente_mapa
    )
    for fila in tabla_datos["filas"]:
        if claves_mapa:
            lat = fila.get(claves_mapa[0])
            lon = fila.get(claves_mapa[1])
            fila["_mapa"] = mapa_fila(lat, lon)
            fila["_ubicacion"] = clasificar_ubicacion(lat, lon)
        else:
            fila["_mapa"] = {
                "x": None,
                "y": None,
                "visible": False,
                "ubicacion": "",
            }
            fila["_ubicacion"] = None
        # El minimapa usa la misma paleta base que los mapas grandes.
        if es_referencia:
            fila["_mapa_color"] = colores.color_relleno(
                fuente_mapa,
                {
                    "percibido": fila.get("Percep.")
                    or fila.get("percibido")
                    or ""
                },
            )
        else:
            fila["_mapa_color"] = colores.COLOR_NO_PERCIBIDO
    ruta_artefacto = archivo if "/" in archivo else f"resultados/{archivo}"
    artefacto = next((a for a in job.artifacts if a.ruta == ruta_artefacto), None)
    parametro = PARAMETROS[tabla]
    endpoint = request.endpoint

    def _filtros_query() -> dict[str, str]:
        return {f"f_{clave}": valor for clave, valor in filtros.items()}

    def url_tab(otra: str) -> str:
        return url_for(endpoint, job_id=job.id, **{parametro: otra})

    def url_orden(columna: str) -> str:
        nueva = (
            "desc"
            if tabla_datos["sort"] == columna and tabla_datos["direccion"] == "asc"
            else "asc"
        )
        return url_for(
            endpoint,
            job_id=job.id,
            **{parametro: opcion},
            q=tabla_datos["q"],
            sort=columna,
            dir=nueva,
            **_filtros_query(),
        )

    def url_pagina(numero: int) -> str:
        return url_for(
            endpoint,
            job_id=job.id,
            **{parametro: opcion},
            q=tabla_datos["q"],
            sort=tabla_datos["sort"],
            dir=tabla_datos["direccion"],
            page=numero,
            **_filtros_query(),
        )

    def url_exportar() -> str:
        return url_for(
            "results.exportar",
            job_id=job.id,
            tabla=tabla,
            **{parametro: opcion},
            q=tabla_datos["q"],
            sort=tabla_datos["sort"],
            dir=tabla_datos["direccion"],
            **_filtros_query(),
        )

    def url_exportar_todo() -> str:
        return url_for(
            "results.exportar",
            job_id=job.id,
            tabla=tabla,
            **{parametro: opcion},
            todo=1,
        )

    def url_exportar_seleccionados() -> str:
        return url_for(
            "results.exportar_seleccionados",
            job_id=job.id,
            tabla=tabla,
            **{parametro: opcion},
        )

    def url_detalle(fila: int) -> str:
        actual = url_for(
            endpoint,
            job_id=job.id,
            **{parametro: opcion},
            q=tabla_datos["q"],
            sort=tabla_datos["sort"],
            dir=tabla_datos["direccion"],
            page=tabla_datos["page"],
            **_filtros_query(),
        )
        return url_for(
            "results.detalle",
            job_id=job.id,
            tabla=tabla,
            opcion=opcion,
            fila=fila,
            volver=actual,
        )

    def url_miniatura(fila: int) -> str:
        return url_for(
            "results.miniatura",
            job_id=job.id,
            tabla=tabla,
            opcion=opcion,
            fila=fila,
        )

    def url_catalogo() -> str:
        return url_for(
            "results.catalogo",
            job_id=job.id,
            opcion=opcion,
            q=tabla_datos["q"],
            sort=tabla_datos["sort"],
            dir=tabla_datos["direccion"],
            **_filtros_query(),
        )

    volver = url_for("jobs.detalle", job_id=job.id)
    titulo_opcion = dict(opciones)[opcion]

    grupos = None
    if tabla == "repetidos":
        labels = {codigo: _alias(job, codigo) for codigo in _fuentes_job(job)}
        grupos = [dict(grupo) for grupo in rep_grupos(list(labels), labels)]
        for grupo in grupos:
            activo = next(
                (titulo for clave, titulo in grupo["opciones"] if clave == opcion),
                None,
            )
            grupo["activo"] = activo is not None
            grupo["titulo_activo"] = activo or ""

    indice = cargar_indice(ruta_workspace(job.id))
    catalogos = indice.get("catalogos", {})
    fuente_catalogo = opcion if opcion in catalogos else opcion.split("_", 1)[0]
    catalogo_filas = (
        catalogos.get(fuente_catalogo, {}).get("filas") if fuente_catalogo in catalogos else None
    )

    return render_template(
        "results/table.html",
        job=job,
        clave=tabla,
        tabla_config=config,
        opcion=opcion,
        titulo_opcion=titulo_opcion,
        opciones=opciones,
        grupos=grupos,
        tabla=tabla_datos,
        columnas=columnas,
        filtros=filtros,
        artefacto=artefacto,
        parametro=parametro,
        endpoint=endpoint,
        volver=volver,
        catalogo_filas=catalogo_filas,
        url_tab=url_tab,
        url_orden=url_orden,
        url_pagina=url_pagina,
        url_exportar=url_exportar,
        url_exportar_todo=url_exportar_todo,
        url_exportar_seleccionados=url_exportar_seleccionados,
        url_detalle=url_detalle,
        url_miniatura=url_miniatura,
        url_catalogo=url_catalogo,
        restringido=restringido,
        catalogo_restringido=catalogo_restringido,
    )


def _fuente_de_repetidos(clave: str) -> str:
    if clave.startswith("publica"):
        return fuentes_manifest.referencia().id
    for definicion in fuentes_manifest.fuentes():
        if clave.startswith(f"{definicion.id}_"):
            return definicion.id
    return clave.split("_", 1)[0]


@results_bp.get("/jobs/<job_id>/resultados/no-publicados")
@login_required
@permiso_requerido("resultados.ver")
def no_publicados(job_id: str):
    return _render_tabla(
        job_id,
        "no_publicados",
        request.args.get("fuente") or fuentes_manifest.default_primary(),
    )


@results_bp.get("/jobs/<job_id>/resultados/no-actualizados")
@login_required
@permiso_requerido("resultados.ver")
def no_actualizados(job_id: str):
    return _render_tabla(
        job_id,
        "no_actualizados",
        request.args.get("fuente") or fuentes_manifest.default_primary(),
    )


@results_bp.get("/jobs/<job_id>/resultados/repetidos")
@login_required
@permiso_requerido("resultados.ver")
def repetidos(job_id: str):
    return _render_tabla(job_id, "repetidos", request.args.get("clave", "publica_amplio"))


@results_bp.get("/jobs/<job_id>/catalogos")
@login_required
@permiso_requerido("catalogos.ver")
def catalogos(job_id: str):
    return _render_tabla(job_id, "catalogos", request.args.get("catalogo") or "")


def _filtros_catalogo() -> dict[str, str]:
    filtros = _filtros()
    if usuario_restringido(current_user):
        filtros = {
            clave: valor
            for clave, valor in filtros.items()
            if clave not in campos_analista()
        }
    return filtros


def _params_catalogo(job_id: str, opcion: str) -> dict:
    params = {
        "job_id": job_id,
        "opcion": opcion,
        "v": catalog_export.VERSION_MAPAS,
    }
    for clave in ("q", "sort", "dir"):
        valor = request.args.get(clave, "").strip()
        if valor:
            params[clave] = valor
    for clave, valor in _filtros_catalogo().items():
        params[f"f_{clave}"] = valor
    return params


def _params_lista_catalogo(job_id: str, opcion: str) -> dict:
    params = {"job_id": job_id, "catalogo": opcion}
    for clave in ("q", "sort", "dir"):
        valor = request.args.get(clave, "").strip()
        if valor:
            params[clave] = valor
    for clave, valor in _filtros_catalogo().items():
        params[f"f_{clave}"] = valor
    return params


def _texto_filtros_catalogo(q: str, filtros: dict[str, str]) -> str:
    """Texto legible de los filtros que se aplican al catálogo y sus mapas."""
    if not q and not filtros:
        return "Sin filtros"
    partes = []
    if q:
        partes.append(f'Búsqueda: "{q}"')
    for clave, valor in filtros.items():
        titulo = titulo_columna(clave)
        mostrado = str(valor).replace("..", " a ")
        mostrado = re.sub(r"^(>=|<=|>|<|=)\s*", r"\1 ", mostrado)
        partes.append(f"{titulo} {mostrado}".strip())
    return "Filtros aplicados: " + " · ".join(partes)


def _datos_catalogo(job: Job, opcion: str) -> tuple[str, str, dict, dict]:
    if usuario_restringido(current_user) and not codigos_usuario(current_user):
        abort(403)
    opciones = _opciones("catalogos", job)
    titulos = dict(opciones)
    if opcion not in titulos:
        abort(404)
    archivo = _archivo_tabla("catalogos", opcion, job)
    if not archivo:
        abort(404)
    direccion = request.args.get("dir", "asc")
    if direccion not in ("asc", "desc"):
        direccion = "asc"
    filtros = _filtros_catalogo()
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "").strip()
    datos = catalog_export.preparar_catalogo(
        ruta_workspace(job.id),
        archivo,
        opcion,
        q=q,
        filtros=filtros,
        sort=sort,
        direccion=direccion,
        ocultar_analista=usuario_restringido(current_user),
    )
    cache_key = hashlib.sha1(
        json.dumps(
            {
                "job": job.id,
                "opcion": opcion,
                "q": q,
                "filtros": filtros,
                "sort": sort,
                "direccion": direccion,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    texto_filtros = _texto_filtros_catalogo(q, filtros)
    resumen = catalog_export.resumen_mapa(
        titulos[opcion], datos["total"], texto_filtros, job.id
    )
    return archivo, titulos[opcion], datos, {
        "cache_key": cache_key,
        "resumen": resumen,
        "filtros_texto": texto_filtros,
    }


def _planta_catalogo(datos: dict, clave: str | None = None):
    plantas = datos.get("plantas", [])
    if clave:
        return next((planta for planta in plantas if planta["clave"] == clave), None)
    return next(
        (planta for planta in plantas if planta["clave"] == "nacional"),
        plantas[0] if plantas else None,
    )


def _resumen_planta(
    titulo: str, planta: dict, filtros: str, job_id: str
) -> dict:
    return catalog_export.resumen_mapa(
        titulo,
        planta["total"],
        filtros,
        job_id,
        mapa=planta["titulo"],
    )


@results_bp.get("/jobs/<job_id>/resultados/catalogos/<opcion>/catalogo")
@login_required
@permiso_requerido("catalogos.ver")
def catalogo(job_id: str, opcion: str):
    """Vista previa del catálogo sanitizado, sus mapas y descargas."""
    job = _job(job_id)
    _archivo, titulo, datos, extra = _datos_catalogo(job, opcion)
    params = _params_catalogo(job.id, opcion)
    return render_template(
        "results/catalogo.html",
        job=job,
        opcion=opcion,
        titulo=titulo,
        datos=datos,
        version_mapas=catalog_export.VERSION_MAPAS,
        url_csv=url_for("results.catalogo_csv", **params),
        url_planta=lambda clave: url_for(
            "results.catalogo_planta_territorio",
            clave=clave,
            **params,
        ),
        url_zip=url_for("results.catalogo_zip", **params),
        url_volver=url_for(
            "results.catalogos", **_params_lista_catalogo(job.id, opcion)
        ),
        url_perfil=lambda perfil_id, modo: url_for(
            "results.catalogo_perfil",
            perfil_id=perfil_id,
            modo=modo,
            **params,
        ),
    )


@results_bp.get("/jobs/<job_id>/resultados/catalogos/<opcion>/catalogo.csv")
@login_required
@permiso_requerido("catalogos.ver")
def catalogo_csv(job_id: str, opcion: str):
    job = _job(job_id)
    _archivo, titulo, datos, _extra = _datos_catalogo(job, opcion)
    datos_csv = catalog_export.csv_catalogo(datos)
    nombre = f"catalogo_{opcion}_{job.inicio14[:8]}_{job.fin14[:8]}.csv"
    registrar(
        "download",
        entity=nombre,
        meta={"catalogo": opcion, "filas": datos["total"]},
    )
    return send_file(
        BytesIO(datos_csv),
        mimetype="text/csv",
        as_attachment=True,
        download_name=nombre,
    )


@results_bp.get(
    "/jobs/<job_id>/resultados/catalogos/<opcion>/catalogo/planta/<clave>.png"
)
@login_required
@permiso_requerido("catalogos.ver")
def catalogo_planta_territorio(job_id: str, opcion: str, clave: str):
    job = _job(job_id)
    _archivo, titulo, datos, extra = _datos_catalogo(job, opcion)
    planta = _planta_catalogo(datos, clave)
    if planta is None:
        abort(404)
    png = catalog_export.mapa_planta(
        ruta_workspace(job.id),
        planta,
        opcion,
        cache_key=extra["cache_key"],
        resumen=_resumen_planta(
            titulo, planta, extra["filtros_texto"], job.id
        ),
    )
    if not png:
        abort(404)
    return send_file(BytesIO(png), mimetype="image/png", max_age=0)


@results_bp.get("/jobs/<job_id>/resultados/catalogos/<opcion>/catalogo/planta.png")
@login_required
@permiso_requerido("catalogos.ver")
def catalogo_planta(job_id: str, opcion: str):
    """Compatibilidad: planta nacional, o la primera disponible."""
    job = _job(job_id)
    _archivo, titulo, datos, extra = _datos_catalogo(job, opcion)
    planta = _planta_catalogo(datos)
    if planta is None:
        abort(404)
    png = catalog_export.mapa_planta(
        ruta_workspace(job.id),
        planta,
        opcion,
        cache_key=extra["cache_key"],
        resumen=_resumen_planta(
            titulo, planta, extra["filtros_texto"], job.id
        ),
    )
    if not png:
        abort(404)
    return send_file(BytesIO(png), mimetype="image/png", max_age=0)


@results_bp.get(
    "/jobs/<job_id>/resultados/catalogos/<opcion>/catalogo/perfil/<perfil_id>.png"
)
@login_required
@permiso_requerido("catalogos.ver")
def catalogo_perfil(job_id: str, opcion: str, perfil_id: str):
    job = _job(job_id)
    _archivo, titulo, datos, extra = _datos_catalogo(job, opcion)
    if perfil_id not in datos["perfiles"]:
        abort(404)
    modo = request.args.get("modo", "auto")
    if modo not in ("auto", "perfil"):
        abort(404)
    eventos = [
        evento
        for evento in datos["eventos"]
        if evento.get("perfil") == perfil_id
    ]
    resumen = catalog_export.resumen_mapa(
        titulo,
        len(eventos),
        extra["filtros_texto"],
        job.id,
        mapa=(
            f"Perfil {perfil_id}"
            if modo == "perfil"
            else f"Perfil {perfil_id} + planta"
        ),
    )
    png = catalog_export.mapa_perfil(
        ruta_workspace(job.id),
        datos,
        opcion,
        perfil_id,
        cache_key=extra["cache_key"],
        resumen=resumen,
        modo=modo,
    )
    if not png:
        abort(404)
    return send_file(BytesIO(png), mimetype="image/png", max_age=0)


def _opciones_zip() -> tuple[bool, str]:
    """Opciones del ZIP: mapas de planta y variante de perfiles."""
    incluir_plantas = request.args.get("plantas", "1") not in (
        "0",
        "false",
        "no",
    )
    perfiles = request.args.get("perfiles", "ambos")
    if perfiles not in ("solo", "con_planta", "ambos"):
        perfiles = "ambos"
    return incluir_plantas, perfiles


@results_bp.get("/jobs/<job_id>/resultados/catalogos/<opcion>/catalogo.zip")
@login_required
@permiso_requerido("catalogos.ver")
def catalogo_zip(job_id: str, opcion: str):
    job = _job(job_id)
    _archivo, titulo, datos, extra = _datos_catalogo(job, opcion)
    incluir_plantas, variante = _opciones_zip()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archivo_zip:
        archivo_zip.writestr(
            "catalogo.csv", catalog_export.csv_catalogo(datos)
        )
        if incluir_plantas:
            for planta in datos["plantas"]:
                png = catalog_export.mapa_planta(
                    ruta_workspace(job.id),
                    planta,
                    opcion,
                    cache_key=extra["cache_key"],
                    resumen=_resumen_planta(
                        titulo, planta, extra["filtros_texto"], job.id
                    ),
                )
                if png:
                    archivo_zip.writestr(
                        f"planta_{planta['clave']}.png", png
                    )
        for perfil_id in datos["perfiles"]:
            eventos = [
                evento
                for evento in datos["eventos"]
                if evento.get("perfil") == perfil_id
            ]
            resumen = catalog_export.resumen_mapa(
                titulo,
                len(eventos),
                extra["filtros_texto"],
                job.id,
                mapa=f"Perfil {perfil_id}",
            )
            if variante in ("solo", "ambos"):
                solo = catalog_export.mapa_perfil(
                    ruta_workspace(job.id),
                    datos,
                    opcion,
                    perfil_id,
                    cache_key=extra["cache_key"],
                    resumen=resumen,
                    modo="perfil",
                )
                if solo:
                    archivo_zip.writestr(
                        f"perfil_{perfil_id}.png", solo
                    )
            if variante in ("con_planta", "ambos"):
                contexto = catalog_export.mapa_perfil(
                    ruta_workspace(job.id),
                    datos,
                    opcion,
                    perfil_id,
                    cache_key=extra["cache_key"],
                    resumen=resumen,
                    modo="auto",
                )
                if contexto:
                    archivo_zip.writestr(
                        f"perfil_{perfil_id}_planta.png", contexto
                    )
    buffer.seek(0)
    nombre = f"catalogo_{opcion}_{job.inicio14[:8]}_{job.fin14[:8]}.zip"
    registrar(
        "download",
        entity=nombre,
        meta={"catalogo": opcion, "filas": datos["total"]},
    )
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=nombre,
    )


@results_bp.get("/jobs/<job_id>/resultados/<tabla>/exportar")
@login_required
@permiso_requerido("resultados.exportar")
def exportar(job_id: str, tabla: str):
    job = _job(job_id)
    if tabla == "catalogos" and usuario_restringido(current_user):
        abort(403)
    config, _opciones, opcion = _opcion_valida(tabla, job)
    archivo = _archivo_tabla(tabla, opcion, job)
    if not archivo:
        abort(404)
    direccion = request.args.get("dir", "asc")
    if direccion not in ("asc", "desc"):
        direccion = "asc"
    # ``todo=1`` descarga el archivo completo; sin él se respetan filtros y orden.
    todo = request.args.get("todo") == "1"

    datos, total = exportar_csv(
        ruta_workspace(job.id),
        archivo,
        q="" if todo else request.args.get("q", "").strip(),
        filtros={} if todo else _filtros(),
        sort="" if todo else request.args.get("sort", "").strip(),
        direccion="asc" if todo else direccion,
        predicado=(
            (lambda fila: evento_visible(fila, current_user))
            if usuario_restringido(current_user) and tabla != "catalogos"
            else None
        ),
    )
    if not datos:
        abort(404)

    sufijo = "_todo" if todo else ""
    nombre = f"{tabla}_{opcion}{sufijo}_{job.inicio14[:8]}_{job.fin14[:8]}.csv"
    registrar(
        "download",
        entity=nombre,
        meta={
            "ruta": archivo if "/" in archivo else f"resultados/{archivo}",
            "filas": total,
            "todo": todo,
        },
    )
    return send_file(
        BytesIO(datos),
        mimetype="text/csv",
        as_attachment=True,
        download_name=nombre,
    )


@results_bp.post(
    "/jobs/<job_id>/resultados/<tabla>/exportar-seleccionados"
)
@login_required
@permiso_requerido("resultados.exportar")
def exportar_seleccionados(job_id: str, tabla: str):
    """Descarga solo las filas marcadas, aunque estén ocultas por el filtro."""
    job = _job(job_id)
    if tabla == "catalogos" and usuario_restringido(current_user):
        abort(403)
    _config, _opciones, opcion = _opcion_valida(tabla, job)
    archivo = _archivo_tabla(tabla, opcion, job)
    if not archivo:
        abort(404)
    filas_ids = []
    for valor in request.form.getlist("filas"):
        try:
            filas_ids.append(int(valor))
        except (TypeError, ValueError):
            continue
    if not filas_ids:
        abort(400)

    datos, total = exportar_seleccionados_csv(
        ruta_workspace(job.id),
        archivo,
        filas_ids,
        predicado=(
            (lambda fila: evento_visible(fila, current_user))
            if usuario_restringido(current_user) and tabla != "catalogos"
            else None
        ),
    )
    if not datos or not total:
        abort(404)

    nombre = (
        f"{tabla}_{opcion}_seleccion_"
        f"{job.inicio14[:8]}_{job.fin14[:8]}.csv"
    )
    registrar(
        "download",
        entity=nombre,
        meta={
            "ruta": archivo if "/" in archivo else f"resultados/{archivo}",
            "filas": total,
            "seleccionados": True,
        },
    )
    return send_file(
        BytesIO(datos),
        mimetype="text/csv",
        as_attachment=True,
        download_name=nombre,
    )


@results_bp.get("/jobs/<job_id>/resultados/<tabla>/<opcion>/<int:fila>/miniatura.png")
@login_required
@permiso_requerido("catalogos.ver")
def miniatura(job_id: str, tabla: str, opcion: str, fila: int):
    job = _job(job_id)
    if tabla != "catalogos" and not tiene_permiso(current_user, "resultados.ver"):
        abort(403)
    if tabla not in TABLAS:
        abort(404)
    if opcion not in [clave for clave, _titulo in _opciones(tabla, job)]:
        abort(404)
    archivo = _archivo_tabla(tabla, opcion, job)
    if not archivo:
        abort(404)
    leido = leer_filas(ruta_workspace(job.id), archivo)
    if leido is None:
        abort(404)
    _columnas, filas = leido
    if fila < 0 or fila >= len(filas):
        abort(404)
    if usuario_restringido(current_user) and not evento_visible(
        filas[fila], current_user
    ):
        abort(403)
    png = generar_miniatura(ruta_workspace(job.id), tabla, archivo, filas, fila)
    return send_file(BytesIO(png), mimetype="image/png", max_age=86400)


@results_bp.get("/jobs/<job_id>/resultados/<tabla>/<opcion>/<int:fila>/mapa.png")
@login_required
@permiso_requerido("resultados.exportar")
def mapa(job_id: str, tabla: str, opcion: str, fila: int):
    job = _job(job_id)
    if tabla not in TABLAS:
        abort(404)
    if opcion not in [clave for clave, _titulo in _opciones(tabla, job)]:
        abort(404)
    archivo = _archivo_tabla(tabla, opcion, job)
    if not archivo:
        abort(404)
    leido = leer_filas(ruta_workspace(job.id), archivo)
    if leido is None:
        abort(404)
    _columnas, filas = leido
    if fila < 0 or fila >= len(filas):
        abort(404)
    if usuario_restringido(current_user) and not evento_visible(
        filas[fila], current_user
    ):
        abort(403)
    titulo_opcion = next(
        (titulo for clave, titulo in _opciones(tabla, job) if clave == opcion),
        opcion,
    )
    resumen = resumen_mapa(
        tabla,
        f"{TABLAS[tabla]['titulo']} · {titulo_opcion}",
        filas,
        fila,
        archivo,
        job.id,
    )
    png = generar_mapa(
        ruta_workspace(job.id),
        tabla,
        opcion,
        archivo,
        filas,
        fila,
        resumen=resumen,
    )
    return send_file(BytesIO(png), mimetype="image/png", max_age=86400)


@results_bp.get("/jobs/<job_id>/resultados/<tabla>/<opcion>/<int:fila>")
@login_required
@permiso_requerido("catalogos.ver")
def detalle(job_id: str, tabla: str, opcion: str, fila: int):
    job = _job(job_id)
    if tabla != "catalogos" and not tiene_permiso(current_user, "resultados.ver"):
        abort(403)
    if tabla not in TABLAS:
        abort(404)
    config = TABLAS[tabla]
    opciones_detalle = _opciones(tabla, job)
    claves = [clave for clave, _titulo in opciones_detalle]
    if opcion not in claves:
        abort(404)

    archivo = _archivo_tabla(tabla, opcion, job)
    if not archivo:
        abort(404)
    leido = leer_filas(ruta_workspace(job.id), archivo)
    if leido is None:
        abort(404)
    columnas, filas = leido
    if fila < 0 or fila >= len(filas):
        abort(404)

    contexto = construir_detalle(tabla, archivo, filas, fila)
    if usuario_restringido(current_user) and not evento_visible(
        contexto["fila"], current_user
    ):
        abort(403)
    revision_estaciones = revisar_fila(
        ruta_workspace(job.id),
        tabla,
        opcion,
        contexto["fila"],
        solo_no_usadas=request.args.get("no_usadas") == "1",
        solo_disponibles=request.args.get("disponibles") == "1",
        radio_km=_numero_param("radio_km"),
        cerca_km=_numero_param("cerca_km", 50.0),
        solo_cercanas=request.args.get("solo_cercanas") == "1",
        ampliado=request.args.get("ampliado") or None,
    )
    if revision_estaciones and revision_estaciones.get("puede_consultar"):
        event_id = str(
            (revision_estaciones.get("evento") or {}).get("event_id") or ""
        )
        vista_consulta = availability.vista_clave(
            ampliado=revision_estaciones.get("ampliado") or "",
            radio_km=revision_estaciones.get("radio_mostrar"),
            cerca_km=revision_estaciones.get("cerca_km", 50.0),
            solo_cercanas=revision_estaciones.get("solo_cercanas", False),
            disponibles=revision_estaciones.get("solo_disponibles", False),
            todas=False,
        )
        revision_estaciones["consulta_tarea"] = (
            availability.tarea_en_curso(
                job.id,
                event_id,
                vista=vista_consulta,
            )
            if event_id
            else ""
        )
    parametro = PARAMETROS[tabla]
    volver = request.args.get("volver", "")
    if not volver.startswith("/") or volver.startswith("//"):
        volver = url_for(ENDPOINTS[tabla], job_id=job.id, **{parametro: opcion})
    volver_etiqueta = (
        request.args.get("volver_etiqueta", "").strip() or "Volver a la tabla"
    )
    desde_indicios = "/indicios" in volver
    analista_publicado = ""
    if tabla == "no_actualizados":
        analista_publicado = texto_analista_probable(
            indices_atribucion(ruta_workspace(job.id)),
            contexto["fila"].get("fecha_eventquery"),
            contexto["fila"].get("lat_eventquery"),
            contexto["fila"].get("lon_eventquery"),
        )
    puntos = puntos_mapa(
        tabla,
        contexto["fila"],
        opcion,
        contexto.get("grupo"),
        indice=fila,
        analista_publicado=analista_publicado,
    )
    for punto in puntos:
        punto["frontera"] = texto_frontera_coords(punto["lat"], punto["lon"])
    frontera_evento = next(
        (punto["frontera"] for punto in puntos if punto["frontera"] != "—"),
        "—",
    )
    eventos_clasificados, perfil_obj = clasificar_eventos(
        tabla,
        archivo,
        filas,
        fila,
        opcion=opcion,
        analista_publicado=analista_publicado,
    )
    marcar_sospechosos(puntos, eventos_clasificados)
    perfil_datos = perfil_desde_eventos(eventos_clasificados, perfil_obj, opcion, tabla)
    for punto in puntos:
        punto["clave"] = clave_evento(punto)
    for evento in (perfil_datos or {}).get("eventos", []):
        evento["clave"] = clave_evento(evento)
    hay_sospechosos = any(punto.get("sospechoso") for punto in puntos) or any(
        evento.get("sospechoso") for evento in eventos_clasificados
    )
    source_id = fuente_de_fila(tabla, opcion)
    evento_canonico = (revision_estaciones or {}).get("evento") or {}
    if source_id and not evento_canonico.get("event_id"):
        evento_canonico = (
            resolver_evento(
                ruta_workspace(job.id),
                source_id,
                tabla,
                contexto["fila"],
            )
            or {}
        )
    indicios_evento = None
    revision_solicitud = None
    if source_id and evento_canonico.get("event_id"):
        publicado = None
        if tabla == "no_publicados":
            publicado = False
        elif tabla == "no_actualizados":
            publicado = True
        elif tabla == "catalogos":
            publicado = indicios.estado_publicado(
                ruta_workspace(job.id), source_id, evento_canonico
            )
        sospechoso = None
        clasificado_evento = None
        try:
            lat_evento = float(evento_canonico.get("latitude"))
            lon_evento = float(evento_canonico.get("longitude"))
        except (TypeError, ValueError):
            lat_evento = lon_evento = None
        if lat_evento is not None and lon_evento is not None:
            for clasificado in eventos_clasificados:
                try:
                    if (
                        abs(float(clasificado.get("latitud")) - lat_evento) <= 0.01
                        and abs(float(clasificado.get("longitud")) - lon_evento)
                        <= 0.01
                    ):
                        sospechoso = bool(clasificado.get("sospechoso"))
                        clasificado_evento = clasificado
                        break
                except (TypeError, ValueError):
                    continue
        explicacion_sospechoso = ""
        if clasificado_evento:
            partes = []
            if clasificado_evento.get("residuo_km") is not None:
                partes.append(
                    f"residuo al slab {clasificado_evento['residuo_km']:.1f} km"
                )
            if clasificado_evento.get("perp_km") is not None:
                partes.append(
                    f"distancia al slab {clasificado_evento['perp_km']:.1f} km"
                )
            explicacion_sospechoso = "; ".join(partes)
        indicios_evento = indicios.evaluar_desde_canonico(
            ruta_workspace(job.id),
            source_id,
            evento_canonico,
            publicado=publicado,
            sospechoso=sospechoso,
            explicacion_sospechoso=explicacion_sospechoso,
            perfil_disponible=perfil_datos is not None,
        )
        revision_solicitud = review.solicitud_de_evento(
            job.id, source_id, evento_canonico.get("event_id")
        )
    historico_activo = request.args.get("historico") == "1"
    historico = historico_datos(perfil_datos) if historico_activo else None
    leyenda = leyenda_detalle(
        tabla,
        opcion,
        puntos,
        hay_sospechosos,
        superpuestos(puntos)
        or superpuestos(
            (perfil_datos or {}).get("eventos", []), perfil=True
        ),
    )
    mapa_modo = modo_mapa(request.args.get("mapa"))
    url_mapa = url_for(
        "results.mapa",
        job_id=job.id,
        tabla=tabla,
        opcion=opcion,
        fila=fila,
    )
    revision_visible = bool(
        revision_solicitud
        and tiene_permiso(current_user, "revisiones.ver")
        and (
            tiene_permiso(current_user, "trabajos.todos")
            or revision_solicitud.get("asignada_id") == current_user.id
        )
    )

    return render_template(
        "results/event.html",
        job=job,
        tabla=tabla,
        tabla_config=config,
        opcion=opcion,
        titulo_opcion=dict(opciones_detalle)[opcion],
        indice_fila=fila,
        columnas=columnas,
        volver=volver,
        volver_etiqueta=volver_etiqueta,
        desde_indicios=desde_indicios,
        archivo=archivo,
        url_mapa=url_mapa,
        puntos_mapa=puntos,
        perfil_datos=perfil_datos,
        hay_sospechosos=hay_sospechosos,
        historico_activo=historico_activo,
        historico=historico,
        frontera_evento=frontera_evento,
        leyenda_mapa=leyenda,
        mapa_modo=mapa_modo,
        titulo_columna=titulo_columna,
        revision_estaciones=revision_estaciones,
        indicios_evento=indicios_evento,
        revision_solicitud=revision_solicitud,
        revision_visible=revision_visible,
        puede_crear_revision=tiene_permiso(current_user, "revisiones.crear"),
        **contexto,
    )


def _numero_param(nombre: str, defecto=None):
    """Parámetro numérico de la URL, o el valor por defecto."""
    valor = request.args.get(nombre, "").strip().replace(",", ".")
    if not valor:
        return defecto
    try:
        return float(valor)
    except ValueError:
        return defecto


def _numero_valor(texto, defecto=None):
    """Convierte un valor de formulario o URL a número."""
    if texto is None:
        return defecto
    limpio = str(texto).strip().replace(",", ".")
    if not limpio:
        return defecto
    try:
        return float(limpio)
    except ValueError:
        return defecto


def _valor_bool(texto) -> bool:
    return str(texto or "").strip().lower() in {
        "1",
        "true",
        "on",
        "si",
        "sí",
    }


def _contexto_fila(job: Job, tabla: str, opcion: str, fila: int) -> dict:
    """Valida la fila de detalle y sus permisos, sin leer las extensiones."""
    if tabla not in TABLAS:
        abort(404)
    claves = [clave for clave, _titulo in _opciones(tabla, job)]
    if opcion not in claves:
        abort(404)
    archivo = _archivo_tabla(tabla, opcion, job)
    if not archivo:
        abort(404)
    leido = leer_filas(ruta_workspace(job.id), archivo)
    if leido is None:
        abort(404)
    _columnas, filas = leido
    if fila < 0 or fila >= len(filas):
        abort(404)
    contexto = construir_detalle(tabla, archivo, filas, fila)
    if usuario_restringido(current_user) and not evento_visible(
        contexto["fila"], current_user
    ):
        abort(403)
    return contexto


def _revision_de_fila(
    job: Job,
    tabla: str,
    opcion: str,
    fila: int,
    *,
    solo_no_usadas: bool = False,
    solo_disponibles: bool = False,
    radio_km: float | None = None,
    cerca_km: float = 50.0,
    solo_cercanas: bool = False,
    ampliado: str | None = None,
) -> dict | None:
    contexto = _contexto_fila(job, tabla, opcion, fila)
    return revisar_fila(
        ruta_workspace(job.id),
        tabla,
        opcion,
        contexto["fila"],
        solo_no_usadas=solo_no_usadas,
        solo_disponibles=solo_disponibles,
        radio_km=radio_km,
        cerca_km=cerca_km,
        solo_cercanas=solo_cercanas,
        ampliado=ampliado,
    )


@results_bp.get(
    "/jobs/<job_id>/resultados/<tabla>/<opcion>/<int:fila>/estaciones/<tipo>.csv"
)
@login_required
@permiso_requerido("resultados.exportar")
def estaciones_csv(job_id: str, tabla: str, opcion: str, fila: int, tipo: str):
    """Descarga los arribos o las estaciones sin arribos de un evento."""
    if tipo not in ("arribos", "sin-arribos"):
        abort(404)
    job = _job(job_id)
    revision = _revision_de_fila(
        job,
        tabla,
        opcion,
        fila,
        solo_no_usadas=request.args.get("no_usadas") == "1",
        solo_disponibles=request.args.get("disponibles") == "1",
        radio_km=_numero_param("radio_km"),
        cerca_km=_numero_param("cerca_km", 50.0),
        solo_cercanas=request.args.get("solo_cercanas") == "1",
        ampliado=request.args.get("ampliado") or None,
    )
    if not revision or revision.get("estado") != "ok":
        abort(404)
    if tipo == "sin-arribos" and not revision.get("tiene_sin_arribos"):
        abort(404)

    if tipo == "sin-arribos":
        revision["sin_arribos"] = filas_visibles(
            revision.get("sin_arribos") or [],
            radio_km=revision.get("radio_mostrar"),
            cerca_km=revision.get("cerca_km", 50.0),
            solo_cercanas=revision.get("solo_cercanas", False),
        )

    columnas, datos = filas_para_csv(
        revision, "arribos" if tipo == "arribos" else "sin_arribos"
    )
    if not datos:
        abort(404)

    salida = StringIO()
    salida.write("\ufeff")
    escritor = csv.writer(salida)
    escritor.writerow(columnas)
    escritor.writerows(datos)
    nombre = (
        f"estaciones_{tipo}_{opcion}_{job.inicio14[:8]}_{job.fin14[:8]}.csv"
    )
    registrar(
        "download",
        entity=nombre,
        meta={
            "tabla": tabla,
            "fuente": revision.get("fuente"),
            "filas": len(datos),
        },
    )
    return send_file(
        BytesIO(salida.getvalue().encode("utf-8")),
        mimetype="text/csv",
        as_attachment=True,
        download_name=nombre,
    )


@results_bp.post(
    "/jobs/<job_id>/resultados/<tabla>/<opcion>/<int:fila>"
    "/estaciones/disponibilidad"
)
@login_required
@permiso_requerido("trabajos.crear")
def consultar_estaciones_disponibilidad(
    job_id: str, tabla: str, opcion: str, fila: int
):
    """Encola la consulta de formas de onda del evento."""
    job = _job(job_id)
    radio_km = _numero_valor(request.values.get("radio_km"))
    cerca_km = _numero_valor(request.values.get("cerca_km"), 50.0)
    solo_cercanas = _valor_bool(request.values.get("solo_cercanas"))
    solo_disponibles = _valor_bool(request.values.get("disponibles"))
    ampliado = str(request.values.get("ampliado") or "") or None
    todas = _valor_bool(request.values.get("todas"))
    revision = _revision_de_fila(
        job,
        tabla,
        opcion,
        fila,
        solo_disponibles=solo_disponibles,
        radio_km=radio_km,
        cerca_km=cerca_km,
        solo_cercanas=solo_cercanas,
        ampliado=ampliado,
    )
    if not revision or revision.get("estado") != "ok":
        abort(404)
    if not revision.get("tiene_sin_arribos"):
        abort(404)
    if not revision.get("puede_consultar"):
        return jsonify(
            {
                "estado": "error",
                "mensaje": (
                    "La consulta de formas de onda no está disponible "
                    "en este entorno."
                ),
            }
        ), 503

    filas, total, omitidas = seleccionar_disponibilidad(
        revision.get("sin_arribos") or [],
        radio_km=revision.get("radio_mostrar"),
        cerca_km=revision.get("cerca_km", 50.0),
        solo_cercanas=revision.get("solo_cercanas", False),
        todas=todas,
        max_estaciones=availability.max_estaciones(),
        max_streams=availability.max_streams(),
    )
    if not filas:
        return jsonify(
            {
                "estado": "error",
                "mensaje": (
                    "No hay estaciones visibles para consultar. "
                    "Revise el radio o el filtro Solo cercanas."
                ),
            }
        ), 400

    evento = revision.get("evento") or {}
    event_id = str(evento.get("event_id") or "")
    event_time = str(evento.get("event_time") or "")
    if not event_id or not event_time:
        return jsonify(
            {"estado": "error", "mensaje": "El evento no tiene hora canónica."}
        ), 400

    vista = availability.vista_clave(
        ampliado=ampliado or "",
        radio_km=revision.get("radio_mostrar"),
        cerca_km=revision.get("cerca_km", 50.0),
        solo_cercanas=revision.get("solo_cercanas", False),
        disponibles=solo_disponibles,
        todas=todas,
    )
    existente = availability.tarea_en_curso(
        job.id, event_id, vista=vista
    )
    if existente:
        return jsonify({"estado": "en_curso", "task_id": existente}), 200

    try:
        tarea = consultar_disponibilidad.delay(
            job.id,
            revision.get("fuente"),
            event_id,
            event_time,
            filas,
            vista=vista,
        )
    except Exception:  # noqa: BLE001 - el usuario necesita un mensaje claro
        return jsonify(
            {
                "estado": "error",
                "mensaje": (
                    "No se pudo encolar la consulta de formas de onda. "
                    "Revise el worker y Redis."
                ),
            }
        ), 503

    task_id, creada = availability.registrar_tarea(
        job.id, event_id, tarea.id, vista
    )
    registrar(
        "availability.query",
        entity=job.id,
        meta={
            "tabla": tabla,
            "fuente": revision.get("fuente"),
            "evento": event_id,
            "estaciones": len(filas),
            "total": total,
            "omitidas": omitidas,
            "todas": todas,
            "vista": vista,
        },
    )
    if not creada:
        return jsonify({"estado": "en_curso", "task_id": task_id}), 200
    return jsonify(
        {
            "estado": "encolada",
            "task_id": tarea.id,
            "total": total,
            "consultadas": len(filas),
            "omitidas": omitidas,
            "todas": todas,
        }
    ), 202


@results_bp.get(
    "/jobs/<job_id>/resultados/<tabla>/<opcion>/<int:fila>"
    "/estaciones/disponibilidad/<task_id>"
)
@login_required
@permiso_requerido("trabajos.crear")
def estado_estaciones_disponibilidad(
    job_id: str, tabla: str, opcion: str, fila: int, task_id: str
):
    """Estado de una consulta de disponibilidad encolada."""
    job = _job(job_id)
    _contexto_fila(job, tabla, opcion, fila)
    resultado = celery.AsyncResult(task_id)
    estado = resultado.state
    datos = {"estado": estado}
    if estado == "PROGRESS":
        datos["fase"] = str((resultado.info or {}).get("fase") or "")
    elif estado == "SUCCESS":
        valor = resultado.result or {}
        if isinstance(valor, dict) and valor.get("estado") == "ok":
            datos.update({"estado": "ok", "resultado": valor})
            volver = request.args.get("volver", "")
            if not volver.startswith("/") or volver.startswith("//"):
                volver = url_for(
                    ENDPOINTS[tabla],
                    job_id=job.id,
                    **{PARAMETROS[tabla]: opcion},
                )
            revision = _revision_de_fila(
                job,
                tabla,
                opcion,
                fila,
                solo_no_usadas=request.args.get("no_usadas") == "1",
                solo_disponibles=request.args.get("disponibles") == "1",
                radio_km=_numero_param("radio_km"),
                cerca_km=_numero_param("cerca_km", 50.0),
                solo_cercanas=request.args.get("solo_cercanas") == "1",
                ampliado=request.args.get("ampliado") or None,
            )
            if revision:
                revision["consulta_tarea"] = ""
                datos["html"] = render_template(
                    "results/_estaciones_sin_arribos.html",
                    job=job,
                    tabla=tabla,
                    opcion=opcion,
                    indice_fila=fila,
                    volver=volver,
                    revision_estaciones=revision,
                )
        else:
            datos.update(
                {
                    "estado": "error",
                    "mensaje": str(
                        valor.get("mensaje")
                        if isinstance(valor, dict)
                        else "La consulta no devolvió un resultado válido."
                    ),
                }
            )
    elif estado == "FAILURE":
        datos.update(
            {
                "estado": "error",
                "mensaje": "La consulta de formas de onda falló en el worker.",
            }
        )
    return jsonify(datos)


@results_bp.post(
    "/jobs/<job_id>/resultados/<tabla>/<opcion>/<int:fila>"
    "/estaciones/ampliar"
)
@login_required
@permiso_requerido("trabajos.crear")
def ampliar_estaciones(job_id: str, tabla: str, opcion: str, fila: int):
    """Encola la ampliación del inventario contra la base de SeisComp."""
    job = _job(job_id)
    revision = _revision_de_fila(job, tabla, opcion, fila)
    if not revision or revision.get("estado") != "ok":
        abort(404)
    if not revision.get("tiene_sin_arribos"):
        abort(404)
    if not amplification.configurada():
        return jsonify(
            {
                "estado": "error",
                "mensaje": (
                    "La base de SeisComp no está configurada en este entorno."
                ),
            }
        ), 503

    evento = revision.get("evento") or {}
    event_id = str(evento.get("event_id") or "")
    id_origen = str(evento.get("origin_id") or "")
    base = str(evento.get("database") or "") or os.environ.get(
        "SEISCOMP_DB_NAME", "seiscomp2"
    )
    event_time = str(evento.get("event_time") or "")
    latitud = evento.get("latitude")
    longitud = evento.get("longitude")
    if (
        not event_id
        or not event_time
        or latitud is None
        or longitud is None
    ):
        return jsonify(
            {
                "estado": "error",
                "mensaje": (
                    "El evento no tiene la hora o las coordenadas necesarias "
                    "para ampliar."
                ),
            }
        ), 400

    sin_limite = str(request.values.get("sin_limite") or "").lower() in {
        "1",
        "true",
        "on",
        "si",
        "sí",
    }
    texto_radio = str(request.values.get("radio_km") or "").strip()
    try:
        radio = float(texto_radio.replace(",", ".")) if texto_radio else None
    except ValueError:
        radio = None
    if not sin_limite and (radio is None or radio <= 0):
        return jsonify(
            {
                "estado": "error",
                "mensaje": "Indique un radio válido o marque Sin límite.",
            }
        ), 400
    if sin_limite:
        radio = None

    clave = amplification.clave_radio(radio)
    existente = amplification.tarea_en_curso(job.id, event_id, clave)
    if existente:
        return jsonify(
            {"estado": "en_curso", "task_id": existente, "clave": clave}
        ), 200

    picadas = [
        [grupo.get("red", ""), grupo.get("estacion", "")]
        for grupo in revision.get("grupos", [])
    ]
    try:
        tarea = ampliar_sin_arribos.delay(
            job.id,
            revision.get("fuente"),
            event_id,
            base,
            id_origen,
            event_time,
            float(latitud),
            float(longitud),
            picadas,
            radio,
        )
    except Exception:  # noqa: BLE001 - el usuario necesita un mensaje claro
        return jsonify(
            {
                "estado": "error",
                "mensaje": (
                    "No se pudo encolar la ampliación. Revise el worker y Redis."
                ),
            }
        ), 503

    task_id, creada = amplification.registrar_tarea(
        job.id, event_id, clave, tarea.id
    )
    registrar(
        "availability.amplify",
        entity=job.id,
        meta={
            "tabla": tabla,
            "fuente": revision.get("fuente"),
            "evento": event_id,
            "radio": radio,
            "sin_limite": sin_limite,
            "clave": clave,
        },
    )
    if not creada:
        return jsonify(
            {"estado": "en_curso", "task_id": task_id, "clave": clave}
        ), 200
    return jsonify(
        {"estado": "encolada", "task_id": tarea.id, "clave": clave}
    ), 202


@results_bp.get(
    "/jobs/<job_id>/resultados/<tabla>/<opcion>/<int:fila>"
    "/estaciones/ampliar/<task_id>"
)
@login_required
@permiso_requerido("trabajos.crear")
def estado_ampliacion(
    job_id: str, tabla: str, opcion: str, fila: int, task_id: str
):
    """Estado de una ampliación encolada."""
    job = _job(job_id)
    _contexto_fila(job, tabla, opcion, fila)
    resultado = celery.AsyncResult(task_id)
    estado = resultado.state
    datos = {"estado": estado}
    if estado == "PROGRESS":
        datos["fase"] = str((resultado.info or {}).get("fase") or "")
    elif estado == "SUCCESS":
        valor = resultado.result or {}
        if isinstance(valor, dict) and valor.get("estado") == "ok":
            volver = request.args.get("volver", "")
            if not volver.startswith("/") or volver.startswith("//"):
                volver = url_for(
                    ENDPOINTS[tabla],
                    job_id=job.id,
                    **{PARAMETROS[tabla]: opcion},
                )
            url = url_for(
                "results.detalle",
                job_id=job.id,
                tabla=tabla,
                opcion=opcion,
                fila=fila,
                volver=volver,
                ampliado=valor.get("clave"),
            )
            datos.update(
                {
                    "estado": "ok",
                    "url": url,
                    "clave": valor.get("clave", ""),
                    "filas": valor.get("filas", 0),
                }
            )
        else:
            datos.update(
                {
                    "estado": "error",
                    "mensaje": str(
                        valor.get("mensaje")
                        if isinstance(valor, dict)
                        else "La ampliación no devolvió un resultado válido."
                    ),
                }
            )
    elif estado == "FAILURE":
        datos.update(
            {
                "estado": "error",
                "mensaje": "La ampliación contra la base falló en el worker.",
            }
        )
    return jsonify(datos)
