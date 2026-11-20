"""Paneles de contexto sismotectónico por perfil."""

from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required

from ..domain.catalogs import canonical
from ..domain.catalogs import manifest as fuentes_manifest
from ..extensions import db
from ..models import Job, User, utcnow
from ..security import (
    permiso_requerido,
    puede_ver_trabajo,
    tiene_permiso,
    tiene_rol,
)
from ..services import colores, indicios, panels, plots, review, review_reports
from ..services.audit import registrar
from ..services.borders import texto_frontera_coords
from ..services.history import datos as historico_datos
from ..services.maps import modo_mapa
from ..services.workspace import ruta_workspace

panels_bp = Blueprint("panels", __name__)

TIPOS_VALIDOS = {"", "no_publicado", "no_actualizado", "repetido"}
TIPOS_PLURAL = {
    "no_publicado": "No publicados",
    "no_actualizado": "No actualizados",
    "repetido": "Repetidos",
}


def _url_panel(
    job_id: str,
    dataset: str,
    tipo: str = "",
    fuente: str = "",
    grupo: str = "",
    ident: str = "",
) -> str:
    parametros = {"job_id": job_id, "dataset": dataset}
    if tipo:
        parametros["tipo"] = tipo
    if fuente:
        parametros["fuente"] = fuente
    if grupo:
        parametros["grupo"] = grupo
    if ident:
        parametros["ident"] = ident
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


def _fuentes_observaciones() -> tuple[str, ...]:
    return tuple(
        definicion.id
        for definicion in fuentes_manifest.locales()
        if definicion.visible_in_observaciones
    )


def _titulo_fuente(fuente: str) -> str:
    return "Todas las fuentes" if not fuente else panels.etiqueta_fuente(fuente)


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
    if dataset == "observaciones":
        if tipo not in TIPOS_VALIDOS:
            tipo = ""
        if fuente not in _fuentes_observaciones():
            fuente = ""
    else:
        tipo = ""
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


def _clave_fecha(valor) -> str:
    return " ".join(str(valor or "").split())


def _antecedentes_panel(workspace, eventos: list[dict]):
    """Prioridad, cruce y caso sin cruce por evento, para Paneles."""
    fuentes = {
        evento.get("fuente")
        for evento in eventos
        if evento.get("fuente") and not evento.get("es_referencia")
    }
    por_fecha: dict[tuple[str, str], dict] = {}
    for fuente in fuentes:
        for fila in indicios.leer_indicios(workspace, fuente):
            clave = (fuente, _clave_fecha(fila.get("fecha_hora")))
            por_fecha[clave] = fila
    por_referencia: dict[str, dict] = {}
    try:
        datos = indicios.leer_detalle_cruce(workspace)
    except Exception:
        datos = {}
    for grupo in (datos.get("sin_cruce") or {}).get("eventos") or []:
        por_referencia[str(grupo.get("fila"))] = grupo
    return por_fecha, por_referencia


def _eventos_vista(
    job: Job,
    eventos: list[dict],
    volver: str,
    antecedentes=None,
) -> list[dict]:
    por_fecha, por_referencia = antecedentes or ({}, {})
    vista = []
    for evento in eventos:
        origen = evento.get("origen") or {}
        tabla = origen.get("tabla")
        fila = origen.get("fila")
        indicio = None
        sin_cruce = None
        if evento.get("es_referencia"):
            sin_cruce = por_referencia.get(str(fila))
        else:
            indicio = por_fecha.get(
                (evento.get("fuente"), _clave_fecha(evento.get("fecha")))
            )
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
                "fuente_etiqueta": evento.get("fuente_etiqueta", ""),
                "es_referencia": bool(evento.get("es_referencia")),
                "percibido": evento.get("percibido", ""),
                "color": evento.get("color", ""),
                "mag": evento["mag"],
                "tipo": evento.get("tipo", ""),
                "prof": evento["prof"],
                "revision": evento["revision"],
                "sospechoso": evento["sospechoso"],
                "territorio": evento["territorio"],
                "url": url,
                "fila_catalogo": fila,
                "prioridad": (indicio or {}).get("prioridad", ""),
                "cruce_eventquery": (indicio or {}).get(
                    "cruce_eventquery", ""
                ),
                "fuerza": (indicio or {}).get("fuerza", ""),
                "wadati_calidad": (indicio or {}).get("wadati_calidad", ""),
                "sin_cruce": bool(sin_cruce),
                "candidato_local": (sin_cruce or {}).get("candidato"),
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
        return ctx["dataset"].removeprefix("catalogo_")
    # Fuente mixta: se identifica como observaciones para no atribuir el grupo
    # completo a una sola fuente en el título del core.
    return "observaciones"


def _fuente_titulo_png(ctx: dict) -> str:
    if ctx["dataset"].startswith("catalogo_"):
        clave = ctx["dataset"].removeprefix("catalogo_")
        return panels.etiqueta_fuente(clave)
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


def _frontera_punto(evento: dict) -> str:
    try:
        return texto_frontera_coords(
            float(evento["lat"]), float(evento["lon"])
        )
    except (KeyError, TypeError, ValueError):
        return "—"


def _puntos_grupo(eventos: list[dict]) -> list[dict]:
    """Puntos del grupo con el mismo contrato que el mapa de Resultados."""
    puntos = []
    for evento in eventos:
        codigo = evento.get("fuente") or "publicado"
        estilo = colores.estilo_punto(
            codigo,
            {
                "percibido": evento.get("percibido", ""),
                "sospechoso": bool(evento.get("sospechoso")),
            },
        )
        puntos.append(
            {
                "fuente": codigo,
                "etiqueta": (
                    "Publicado"
                    if codigo == "publicado"
                    else panels.etiqueta_fuente(codigo)
                ),
                "color": estilo["color"],
                "borde": estilo["borde"],
                "borde_ancho": estilo["borde_ancho"],
                "rol": None,
                "percibido": evento.get("percibido", ""),
                "fecha": evento.get("fecha", ""),
                "lat": evento.get("lat"),
                "lon": evento.get("lon"),
                "prof": evento.get("prof"),
                "along_km": evento.get("along_km"),
                "mag": evento.get("mag", ""),
                "tipo": evento.get("tipo", ""),
                "analista": evento.get("analista", ""),
                "frontera": _frontera_punto(evento),
                "sospechoso": bool(evento.get("sospechoso")),
                "estado": "",
                "url": evento.get("url"),
            }
        )
    return puntos


def _perfil_grupo(ident: str, puntos: list[dict]) -> dict | None:
    grafico = panels.perfiles_grafico([ident]).get(ident)
    if not grafico:
        return None
    return {
        "id": ident,
        "topo_p": grafico.get("topo_p", []),
        "topo_alt": grafico.get("topo_alt", []),
        "slab_p": grafico.get("slab_p", []),
        "slab_depth": grafico.get("slab_depth", []),
        "slab_lon": grafico.get("slab_lon", []),
        "slab_lat": grafico.get("slab_lat", []),
        "eventos": [
            punto
            for punto in puntos
            if punto.get("along_km") is not None
            and punto.get("prof") is not None
        ],
    }


def _leyenda_grupo(puntos: list[dict]) -> list[dict]:
    items = [
        {
            "etiqueta": "Sismo no percibido / registrado",
            "relleno": colores.COLOR_NO_PERCIBIDO,
            "borde": "#000000",
            "borde_ancho": 1.2,
        },
        {
            "etiqueta": "Sismo percibido",
            "relleno": colores.COLOR_PERCIBIDO,
            "borde": "#000000",
            "borde_ancho": 1.2,
        },
    ]
    if any(punto.get("sospechoso") for punto in puntos):
        items.append(
            {
                "etiqueta": "Sospechoso (borde violeta)",
                "relleno": colores.COLOR_NEUTRO,
                "borde": colores.COLOR_BORDE_SOSPECHOSO,
                "borde_ancho": colores.GROSOR_BORDE_SOSPECHOSO,
            }
        )
    items.append(
        {
            "etiqueta": "Evento seleccionado",
            "relleno": "transparent",
            "borde": colores.COLOR_RESALTADO,
            "borde_ancho": 2.0,
        }
    )
    return items


def _volver_panel(job: Job, valores) -> str:
    dataset = str(valores.get("dataset") or "").strip()
    grupo = str(valores.get("grupo") or "").strip()
    ident = str(valores.get("ident") or "").strip()
    if dataset and grupo in ("perfil", "territorio") and ident:
        return url_for(
            "panels.grupo",
            job_id=job.id,
            dataset=dataset,
            grupo=grupo,
            ident=ident,
        )
    return url_for("panels.index", job_id=job.id)


def _usuario_por_codigo(codigo: str, analistas: list[User]) -> User | None:
    texto = str(codigo or "").strip().lower()
    if not texto:
        return None
    for usuario in analistas:
        if str(usuario.analyst_code or "").strip().lower() == texto:
            return usuario
    return None


def _supervisores_activos() -> list[User]:
    usuarios = db.session.execute(db.select(User)).scalars()
    return [
        usuario
        for usuario in usuarios
        if usuario.active and tiene_rol(usuario, "supervisor")
    ]


def _contexto_publicacion(job: Job, fila: int):
    workspace = ruta_workspace(job.id)
    referencia = fuentes_manifest.referencia()
    eventos = canonical.leer_canonico(workspace, referencia.id)
    ref = next(
        (evento for evento in eventos if evento.get("raw_index") == fila),
        None,
    )
    if ref is None:
        return None
    datos = indicios.leer_detalle_cruce(workspace)
    grupo = next(
        (
            item
            for item in (datos.get("sin_cruce") or {}).get("eventos") or []
            if item.get("fila") == fila
        ),
        None,
    )
    candidato = (grupo or {}).get("candidato")
    analistas = review.usuarios_analistas()
    sugerido = _usuario_por_codigo(
        (candidato or {}).get("analista", ""), analistas
    )
    return {
        "referencia": referencia,
        "ref": ref,
        "grupo": grupo,
        "candidato": candidato,
        "sugerido": sugerido,
        "supervisores": _supervisores_activos(),
    }


@panels_bp.route(
    "/jobs/<job_id>/paneles/publicacion/<int:fila>",
    methods=["GET", "POST"],
)
@login_required
@permiso_requerido("paneles.ver")
def revision_publicacion(job_id: str, fila: int):
    """Solicitud de revisión de un evento publicado en Eventquery."""
    job = _job_panel(job_id)
    if not tiene_permiso(current_user, "revisiones.crear"):
        abort(403)
    contexto = _contexto_publicacion(job, fila)
    if contexto is None:
        abort(404)
    ref = contexto["ref"]
    candidato = contexto["candidato"]
    grupo = contexto["grupo"]
    volver = _volver_panel(job, request.values)

    def _render(estado_http: int = 200):
        return (
            render_template(
                "panels/publicacion.html",
                job=job,
                fila=fila,
                referencia=contexto["referencia"],
                ref=ref,
                grupo=grupo,
                candidato=candidato,
                sugerido=contexto["sugerido"],
                supervisores=contexto["supervisores"],
                volver=volver,
                dataset=request.values.get("dataset", ""),
                grupo_panel=request.values.get("grupo", ""),
                ident=request.values.get("ident", ""),
            ),
            estado_http,
        )

    if request.method != "POST":
        return _render()

    asignado = None
    valor = request.form.get("asignado", "").strip()
    if valor:
        try:
            asignado = db.session.get(User, int(valor))
        except (TypeError, ValueError):
            asignado = None
    if asignado is None:
        asignado = contexto["sugerido"]
    if asignado is None:
        flash("Seleccione un responsable para la revisión.", "danger")
        return _render(400)
    if not asignado.active or not (
        tiene_rol(asignado, "analista") or tiene_rol(asignado, "supervisor")
    ):
        flash("El responsable asignado no está activo o no tiene rol.", "danger")
        return _render(400)

    conflictos = review.conflictos(
        job.id, contexto["referencia"].id, [ref["event_id"]]
    )
    if conflictos:
        flash(
            "El evento ya está en una solicitud activa.",
            "warning",
        )
        return redirect(volver)

    formato = request.form.get("formato", "pdf").strip().lower()
    if formato not in ("pdf", "docx"):
        formato = "pdf"
    nota = request.form.get("nota", "").strip()
    cruce = {
        "candidato": candidato,
        "diferencias": (grupo or {}).get("diferencias") or {},
        "criterio": (grupo or {}).get("criterio") or {},
    }
    fila_informe = {
        "fuente": contexto["referencia"].id,
        "evento": ref["event_id"],
        "id_evento_fuente": ref.get("source_event_id", ""),
        "fila_catalogo": fila,
        "fecha_hora": ref.get("event_time", ""),
        "latitud": ref.get("latitude"),
        "longitud": ref.get("longitude"),
        "profundidad_km": ref.get("depth_km"),
        "magnitud": ref.get("magnitude"),
        "magnitud_tipo": ref.get("magnitude_type", ""),
        "analista": (candidato or {}).get("analista", ""),
        "cruce_eventquery": "sin_cruce" if candidato else "sin_evaluar",
        "sospechoso": "Desconocido",
        "prioridad": "Publicación",
        "motivo": "publicacion",
        "motivo_prioridad": "Publicación",
        "fuerza": "",
        "patron": "sin_fase",
        "contexto": "",
        "n_usadas": "",
        "max_residual_usado": "",
        "kind": "publicacion",
        "cruce": cruce,
        "ondas": {},
    }
    report_id = uuid4().hex
    estado = {
        "job_id": job.id,
        "user_id": current_user.id,
        "assigned_to_id": asignado.id,
        "fuente": contexto["referencia"].id,
        "formato": formato,
        "nota": nota,
        "kind": "publicacion",
        "notified_at": utcnow().isoformat(),
        "base_url": request.host_url.rstrip("/"),
        "filas": [fila_informe],
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
        flash(f"No se pudo encolar la solicitud: {exc}", "danger")
        return _render(503)

    registrar(
        "revision.solicitar",
        f"job:{job.id}",
        {
            "fuente": contexto["referencia"].id,
            "eventos": [ref["event_id"]],
            "formato": formato,
            "asignado": asignado.id,
            "kind": "publicacion",
        },
    )
    flash(
        "Solicitud de publicación encolada. Aparecerá en Revisiones al "
        "terminar la generación.",
        "success",
    )
    return redirect(volver)


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

    datos_completos = panels.filtrar_por_analista(
        panels.cargar(workspace, dataset), current_user
    )
    tipo = request.args.get("tipo", "")
    fuente = request.args.get("fuente", "")
    if dataset == "observaciones":
        if tipo not in TIPOS_VALIDOS:
            tipo = ""
        if fuente not in _fuentes_observaciones():
            fuente = ""
    else:
        tipo = ""
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

    grupo_inicial = request.args.get("grupo", "")
    ident_inicial = request.args.get("ident", "")
    if grupo_inicial == "perfil":
        validos = {perfil["id"] for perfil in datos["perfiles"]}
    elif grupo_inicial == "territorio":
        validos = {territorio["nombre"] for territorio in datos["territorios"]}
    else:
        validos = set()
    if ident_inicial not in validos:
        grupo_inicial = ""
        ident_inicial = ""

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
        for clave in _fuentes_observaciones():
            total = fuentes_tipo.get(clave, 0)
            fuentes_tabs.append(
                {
                    "clave": clave,
                    "titulo": panels.etiqueta_fuente(clave),
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
    eventos_vista = _eventos_vista(
        job,
        datos["eventos"],
        volver,
        _antecedentes_panel(ruta_workspace(job.id), datos["eventos"]),
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
        grupo_inicial=grupo_inicial,
        ident_inicial=ident_inicial,
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
    ctx["datos"] = panels.filtrar_por_analista(ctx["datos"], current_user)
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
    ctx["datos"] = panels.filtrar_por_analista(ctx["datos"], current_user)
    detalle = panels.grupo_eventos(ctx["datos"], grupo, ident)
    if detalle is None:
        abort(404)

    volver = _url_panel(
        job.id,
        ctx["dataset"],
        ctx["tipo"],
        ctx["fuente"],
        grupo=grupo,
        ident=ident,
    )
    eventos_vista = _eventos_vista(
        job,
        detalle["eventos"],
        volver,
        _antecedentes_panel(ruta_workspace(job.id), detalle["eventos"]),
    )
    datos_vista = {
        "total": len(detalle["eventos"]),
        "con_perfil": sum(1 for e in detalle["eventos"] if e.get("perfil")),
        "sin_perfil": sum(1 for e in detalle["eventos"] if not e.get("perfil")),
        "sospechosos": detalle["resumen"].get("sospechosos", 0),
        "eventos": eventos_vista,
    }
    puntos = _puntos_grupo(eventos_vista)
    perfil_datos = _perfil_grupo(ident, puntos) if grupo == "perfil" else None
    parametros = _parametros_grupo(job, ctx, grupo, ident)
    url_offline = url_for(
        "panels.grupo", **{**parametros, "mapa": "offline"}
    )
    url_online = url_for(
        "panels.grupo", **{**parametros, "mapa": "online"}
    )
    historico_activo = bool(
        perfil_datos and request.args.get("historico") == "1"
    )
    historico = None
    if historico_activo:
        perfil = panels.perfil_historico(ident)
        if perfil is not None:
            historico = historico_datos(perfil)
    url_mapa = url_for(
        "panels.grupo_mapa", **parametros
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
        puntos_mapa=puntos,
        perfil_datos=perfil_datos,
        leyenda_mapa=_leyenda_grupo(puntos),
        mapa_modo=modo_mapa(request.args.get("mapa")),
        url_offline=url_offline,
        url_online=url_online,
        url_mapa=url_mapa,
        puede_exportar=True,
        etiquetas_fuente=fuentes_manifest.etiquetas(),
        historico_activo=historico_activo,
        historico=historico,
        texto_sin_perfil="El grupo no tiene perfil de subducción asignado.",
        titulo_mapa="Mapa interactivo",
        descripcion_mapa=(
            "Planta y perfil del grupo. Haga clic en un evento de cualquiera "
            "de las dos vistas para ver sus parámetros."
        ),
        download_name=f"panel_{grupo}_{ident}.png",
        volver=volver,
        puede_solicitar=tiene_permiso(current_user, "revisiones.crear"),
        grupo_panel=grupo,
        ident=ident,
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
