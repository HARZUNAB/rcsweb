"""Tablas de resultados, detalle y exportación."""

from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO

from flask import (
    Blueprint,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..domain.catalogs import manifest as fuentes_manifest
from ..extensions import db
from ..models import Job
from ..security import permiso_requerido, puede_ver_trabajo
from ..services import catalog_export, colores
from ..services.analysts import (
    campos_analista,
    codigos_usuario,
    evento_visible,
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
@permiso_requerido("catalogos.ver")
def overview(job_id: str):
    job = _job(job_id)
    return redirect(url_for("jobs.detalle", job_id=job.id) + "#resultados")


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
@permiso_requerido("catalogos.ver")
def no_publicados(job_id: str):
    return _render_tabla(
        job_id,
        "no_publicados",
        request.args.get("fuente") or fuentes_manifest.default_primary(),
    )


@results_bp.get("/jobs/<job_id>/resultados/no-actualizados")
@login_required
@permiso_requerido("catalogos.ver")
def no_actualizados(job_id: str):
    return _render_tabla(
        job_id,
        "no_actualizados",
        request.args.get("fuente") or fuentes_manifest.default_primary(),
    )


@results_bp.get("/jobs/<job_id>/resultados/repetidos")
@login_required
@permiso_requerido("catalogos.ver")
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
    texto_filtros = "Con filtros aplicados" if q or filtros else "Sin filtros"
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
    if usuario_restringido(current_user):
        if tabla == "catalogos" or not evento_visible(filas[fila], current_user):
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
    if usuario_restringido(current_user):
        if tabla == "catalogos" or not evento_visible(filas[fila], current_user):
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
    if usuario_restringido(current_user):
        if tabla == "catalogos" or not evento_visible(
            contexto["fila"], current_user
        ):
            abort(403)
    parametro = PARAMETROS[tabla]
    volver = request.args.get("volver", "")
    if not volver.startswith("/") or volver.startswith("//"):
        volver = url_for(ENDPOINTS[tabla], job_id=job.id, **{parametro: opcion})
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
        if punto.get("fila") is not None:
            punto["url"] = url_for(
                "results.detalle",
                job_id=job.id,
                tabla=tabla,
                opcion=opcion,
                fila=punto["fila"],
                volver=volver,
            )
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
        **contexto,
    )
