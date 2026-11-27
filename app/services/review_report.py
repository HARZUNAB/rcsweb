"""Renderizado DOCX y PDF de solicitudes de revisión."""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from . import formatting


def _texto(valor, default="—") -> str:
    if valor is None:
        return default
    texto = str(valor).strip()
    return texto or default


def _numero(valor, decimales=1) -> str:
    if valor is None or str(valor).strip() == "":
        return "—"
    return formatting.numero(valor, decimales)


def _primero(*valores):
    for valor in valores:
        if valor is not None and str(valor).strip() != "":
            return valor
    return None


CRUCE_TEXTO = {
    "con_cruce": "Con cruce",
    "sin_cruce": "Sin cruce",
    "sin_evaluar": "Sin evaluar",
}


def _cruce(valor) -> str:
    texto = "" if valor is None else str(valor).strip()
    return CRUCE_TEXTO.get(texto, _texto(valor))


def _identificador(evento: dict) -> str:
    fila = evento.get("fila") or {}
    return _texto(
        fila.get("id_evento_fuente") or fila.get("evento")
    )


def _solucion(valor) -> str:
    texto = "" if valor is None else str(valor).strip()
    if texto == "Sí":
        return "Sospechosa"
    if texto == "No":
        return "Normal"
    if texto in {"", "Desconocido"}:
        return "Sin evaluar"
    return texto


def _motivo_prioridad(fila: dict) -> str:
    texto = _texto(fila.get("motivo_prioridad"), "")
    if texto:
        return texto
    motivo = _texto(fila.get("motivo"), "")
    return {
        "sospechosa": "Localización",
        "fase": "Fases",
        "ambas": "Localización + fases",
    }.get(motivo, "")


def _wadati(fila: dict) -> str:
    """Línea descriptiva del análisis Wadati, sin recalcular nada."""
    try:
        pares = int(float(str(fila.get("wadati_n") or 0)))
    except (TypeError, ValueError):
        return ""
    if pares < 3:
        return ""
    partes = [
        f"N {pares}",
        f"Vp/Vs {_numero(fila.get('wadati_vp_vs'), 2)}",
        f"R² {_numero(fila.get('wadati_r2'), 2)}",
        f"dispersión {_numero(fila.get('wadati_dispersion'), 2)} s",
    ]
    calidad = _texto(fila.get("wadati_calidad"), "")
    if calidad:
        partes.append(calidad.capitalize())
    return " · ".join(partes)


def _fecha_corta(valor) -> str:
    texto = str(valor or "").strip()
    if not texto:
        return ""
    try:
        instante = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return texto[:16].replace("T", " ")
    return instante.strftime("%Y-%m-%d %H:%M")


def _ondas(fila: dict) -> str:
    """Antecedente de la consulta de formas de onda del evento."""
    datos = fila.get("ondas") or {}
    if not isinstance(datos, dict):
        return ""
    try:
        consultadas = int(datos.get("consultadas") or 0)
        disponibles = int(datos.get("disponibles") or 0)
        sin_datos = int(datos.get("sin_datos") or 0)
    except (TypeError, ValueError):
        return ""
    if consultadas <= 0:
        return ""
    partes = [
        f"{disponibles} disponibles sin usar",
        f"{consultadas} consultadas",
    ]
    if sin_datos:
        partes.append(f"{sin_datos} sin datos")
    fecha = _fecha_corta(datos.get("consultado_en"))
    if fecha:
        partes.append(f"consulta {fecha}")
    return " · ".join(partes)


def _cruce_antecedente(fila: dict, kind: str):
    """Filas del antecedente local y acción solicitada."""
    cruce = fila.get("cruce") or {}
    if not isinstance(cruce, dict):
        return []
    candidato = cruce.get("candidato") or {}
    filas = []
    if candidato:
        filas.append(
            (
                "Solución local (antecedente)",
                " · ".join(
                    [
                        _texto(candidato.get("evento_local")),
                        _texto(candidato.get("fecha_local")),
                        _texto(candidato.get("etiqueta")),
                    ]
                ),
            )
        )
        diferencias = cruce.get("diferencias") or {}
        partes = [
            f"Δt {_numero(candidato.get('dt_seg'), 1)} s",
            f"distancia {_numero(candidato.get('dist_km'), 1)} km",
        ]
        if diferencias.get("profundidad") is not None:
            partes.append(f"Δprof {diferencias['profundidad']:+.1f} km")
        if diferencias.get("magnitud") is not None:
            partes.append(f"Δmag {diferencias['magnitud']:+.1f}")
        filas.append(("Comparación", " · ".join(partes)))
        criterio = (cruce.get("criterio") or {}).get("texto")
        if criterio:
            filas.append(("Criterio de cruce", criterio))
    else:
        filas.append(
            ("Antecedente", "Sin contraparte local comparable.")
        )
    if kind == "publicacion":
        if candidato:
            accion = (
                "Revisar la publicación y, si corresponde, actualizarla "
                f"con la solución local {_texto(candidato.get('evento_local'))}."
            )
        else:
            accion = "Revisar la publicación sin contraparte local."
        filas.append(("Acción solicitada", accion))
    return filas


def _resumen(evento: dict) -> list[tuple[str, str]]:
    fila = evento.get("fila") or {}
    canonico = evento.get("canonico") or {}
    latitud = _primero(canonico.get("latitude"), fila.get("latitud"))
    longitud = _primero(canonico.get("longitude"), fila.get("longitud"))
    profundidad = _primero(canonico.get("depth_km"), fila.get("profundidad_km"))
    magnitud = _primero(canonico.get("magnitude"), fila.get("magnitud"))
    magnitud_tipo = (
        canonico.get("magnitude_type")
        or ((canonico.get("raw") or {}).get("Tipo_mag."))
        or (fila.get("magnitud_tipo") or "")
    )
    etiqueta_analista = (
        "Analista del candidato"
        if fila.get("kind") == "publicacion"
        else "Analista"
    )
    resumen = [
        ("Evento", _texto(fila.get("evento"))),
        ("ID de fuente", _texto(fila.get("id_evento_fuente"))),
        ("Fecha y hora", _texto(fila.get("fecha_hora"))),
        (
            "Coordenadas",
            f"{_numero(latitud, 2)}, {_numero(longitud, 2)}",
        ),
        ("Profundidad", f"{_numero(profundidad, 1)} km"),
        ("Magnitud", _numero(magnitud, 1)),
        ("Tipo de magnitud", _texto(magnitud_tipo)),
        (
            etiqueta_analista,
            _texto(fila.get("analista") or canonico.get("analyst")),
        ),
        ("Cruce Eventquery", _cruce(fila.get("cruce_eventquery"))),
        ("Solución", _solucion(fila.get("sospechoso"))),
        ("Prioridad", _texto(fila.get("prioridad"))),
    ]
    motivo = _motivo_prioridad(fila)
    if motivo:
        resumen.append(("Motivo de prioridad", motivo))
    wadati = _wadati(fila)
    if wadati:
        resumen.append(("Wadati", wadati))
    ondas = _ondas(fila)
    if ondas:
        resumen.append(("Formas de onda", ondas))
    kind = _texto(fila.get("kind"), "")
    if kind == "publicacion":
        resumen.append(("Tipo de solicitud", "Publicación"))
    resumen.extend(_cruce_antecedente(fila, kind))
    return resumen


def _encabezado(datos: dict) -> list[tuple[str, str]]:
    return [
        ("Trabajo", _texto(datos.get("job_id"))),
        ("Fuente", _texto(datos.get("source"))),
        ("Creador", _texto(datos.get("creado_por"))),
        ("Analista asignado", _texto(datos.get("asignado"))),
        ("Elaboración", _texto(datos.get("elaborado"))),
        ("Eventos", str(len(datos.get("eventos") or []))),
        ("Nota", _texto(datos.get("nota"))),
    ]


def generar_docx(datos: dict, ruta: Path) -> None:
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Cm, Pt

    documento = Document()
    seccion = documento.sections[0]
    seccion.orientation = WD_ORIENT.LANDSCAPE
    seccion.page_width, seccion.page_height = (
        seccion.page_height,
        seccion.page_width,
    )
    documento.styles["Normal"].font.size = Pt(9)
    documento.add_heading("Informe de solicitud de revisión", level=0)

    tabla = documento.add_table(rows=0, cols=2)
    tabla.style = "Table Grid"
    for clave, valor in _encabezado(datos):
        celdas = tabla.add_row().cells
        celdas[0].text = clave
        celdas[1].text = valor

    documento.add_paragraph("")
    documento.add_heading("Índice de eventos", level=1)
    indice = documento.add_table(rows=1, cols=3)
    indice.style = "Table Grid"
    for celda, titulo in zip(
        indice.rows[0].cells, ("Fecha y hora", "ID de fuente", "Prioridad")
    ):
        celda.text = titulo
    for evento in datos.get("eventos") or []:
        fila = evento.get("fila") or {}
        celdas = indice.add_row().cells
        celdas[0].text = _texto(fila.get("fecha_hora"))
        celdas[1].text = _identificador(evento)
        celdas[2].text = _texto(fila.get("prioridad"))

    for evento in datos.get("eventos") or []:
        documento.add_page_break()
        documento.add_heading(
            "Evento " + _identificador(evento), level=1
        )
        resumen = documento.add_table(rows=0, cols=2)
        resumen.style = "Table Grid"
        for clave, valor in _resumen(evento):
            celdas = resumen.add_row().cells
            celdas[0].text = clave
            celdas[1].text = valor

        mapa = evento.get("mapa")
        if mapa:
            documento.add_paragraph("")
            documento.add_picture(BytesIO(mapa), width=Cm(24))

    documento.save(str(ruta))


def generar_pdf(datos: dict, ruta: Path) -> None:
    from PIL import Image as PILImage
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    estilos = getSampleStyleSheet()
    estilos.add(
        ParagraphStyle(
            name="RevisionSmall",
            parent=estilos["BodyText"],
            fontSize=7.5,
            leading=9,
        )
    )
    estilos.add(
        ParagraphStyle(
            name="RevisionCell",
            parent=estilos["BodyText"],
            fontSize=7,
            leading=8,
        )
    )
    documento = SimpleDocTemplate(
        str(ruta),
        pagesize=landscape(A4),
        leftMargin=1.2 * cm,
        rightMargin=1.2 * cm,
        topMargin=1.2 * cm,
        bottomMargin=1.2 * cm,
        title="Informe de solicitud de revisión",
    )
    historia = [
        Paragraph("Informe de solicitud de revisión", estilos["Title"]),
        Spacer(1, 0.3 * cm),
    ]

    def _tabla_datos(pares):
        filas = [
            [
                Paragraph(
                    escape(str(clave)).replace("\n", "<br/>"),
                    estilos["RevisionCell"],
                ),
                Paragraph(
                    escape(str(valor)).replace("\n", "<br/>"),
                    estilos["RevisionCell"],
                ),
            ]
            for clave, valor in pares
        ]
        tabla = Table(filas, colWidths=[4 * cm, 20 * cm])
        tabla.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return tabla

    historia.append(_tabla_datos(_encabezado(datos)))
    historia.append(Spacer(1, 0.4 * cm))
    historia.append(Paragraph("Índice de eventos", estilos["Heading2"]))
    indice = [
        [
            Paragraph("Fecha y hora", estilos["RevisionCell"]),
            Paragraph("ID de fuente", estilos["RevisionCell"]),
            Paragraph("Prioridad", estilos["RevisionCell"]),
        ]
    ]
    for evento in datos.get("eventos") or []:
        fila = evento.get("fila") or {}
        indice.append(
            [
                Paragraph(
                    escape(_texto(fila.get("fecha_hora"))),
                    estilos["RevisionCell"],
                ),
                Paragraph(
                    escape(_identificador(evento)), estilos["RevisionCell"]
                ),
                Paragraph(
                    escape(_texto(fila.get("prioridad"))),
                    estilos["RevisionCell"],
                ),
            ]
        )
    tabla_indice = Table(indice, colWidths=[5 * cm, 10 * cm, 4 * cm])
    tabla_indice.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.whitesmoke),
            ]
        )
    )
    historia.append(tabla_indice)

    for evento in datos.get("eventos") or []:
        historia.append(PageBreak())
        historia.append(
            Paragraph(
                escape("Evento " + _identificador(evento)),
                estilos["Heading1"],
            )
        )
        historia.append(_tabla_datos(_resumen(evento)))
        mapa = evento.get("mapa")
        if mapa:
            imagen = PILImage.open(BytesIO(mapa))
            ancho, alto = imagen.size
            max_ancho, max_alto = 25 * cm, 11 * cm
            escala = min(max_ancho / ancho, max_alto / alto)
            historia.append(Spacer(1, 0.3 * cm))
            historia.append(
                Image(
                    BytesIO(mapa),
                    width=ancho * escala,
                    height=alto * escala,
                )
            )

    documento.build(historia)
