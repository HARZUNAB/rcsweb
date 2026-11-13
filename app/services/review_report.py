"""Renderizado DOCX y PDF de solicitudes de revisión."""

from __future__ import annotations

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


def _identificador(evento: dict) -> str:
    fila = evento.get("fila") or {}
    return _texto(
        fila.get("id_evento_fuente") or fila.get("evento")
    )


def _resumen(evento: dict) -> list[tuple[str, str]]:
    fila = evento.get("fila") or {}
    canonico = evento.get("canonico") or {}
    clasificacion = evento.get("clasificacion") or {}
    latitud = _primero(canonico.get("latitude"), fila.get("latitud"))
    longitud = _primero(canonico.get("longitude"), fila.get("longitud"))
    profundidad = _primero(canonico.get("depth_km"), fila.get("profundidad_km"))
    magnitud = _primero(canonico.get("magnitude"), fila.get("magnitud"))
    magnitud_tipo = (
        canonico.get("magnitude_type")
        or ((canonico.get("raw") or {}).get("Tipo_mag."))
        or (fila.get("magnitud_tipo") or "")
    )
    return [
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
            "Analista",
            _texto(fila.get("analista") or canonico.get("analyst")),
        ),
        ("Publicado", _texto(fila.get("publicado"))),
        (
            "Solución",
            (
                f"{_texto(fila.get('sospechoso'))} · "
                f"residuo {_numero(clasificacion.get('residuo_km'), 1)} km"
                if fila.get("sospechoso")
                else _texto(fila.get("sospechoso"))
            ),
        ),
        ("Perfil", _texto(clasificacion.get("perfil"))),
        ("Prioridad", _texto(fila.get("prioridad"))),
        ("Motivo", _texto(fila.get("motivo"))),
        ("Cobertura", _texto(fila.get("contexto"))),
        ("Estaciones usadas", _texto(fila.get("n_usadas"))),
        (
            "Máximo residual",
            f"{_numero(fila.get('max_residual_usado'), 2)} s",
        ),
        ("Enlace", _texto(evento.get("url"))),
    ]


def _encabezado(datos: dict) -> list[tuple[str, str]]:
    return [
        ("Trabajo", _texto(datos.get("job_id"))),
        ("Fuente", _texto(datos.get("source"))),
        ("Creador", _texto(datos.get("creado_por"))),
        ("Analista asignado", _texto(datos.get("asignado"))),
        ("Notificación", _texto(datos.get("notified_at"))),
        ("Eventos", str(len(datos.get("eventos") or []))),
        ("Nota", _texto(datos.get("nota"))),
    ]


def _evidencia(evento: dict) -> list[list[str]]:
    filas = evento.get("evidencia") or []
    if not filas:
        return []
    agrupadas: dict[tuple, dict] = {}
    for fila in filas:
        clave = (
            _texto(fila.get("red"), ""),
            _texto(fila.get("estacion"), ""),
            _texto(fila.get("fase"), ""),
            _texto(fila.get("hora_pick"), ""),
        )
        actual = agrupadas.get(clave)
        if actual is None:
            actual = dict(fila)
            actual["_tipos"] = []
            agrupadas[clave] = actual
        tipo = _texto(fila.get("tipo_indicio"), "")
        if tipo and tipo not in actual["_tipos"]:
            actual["_tipos"].append(tipo)
    datos = [
        [
            "Estación",
            "Fase",
            "Pick",
            "t (s)",
            "Residual",
            "Peso",
            "Distancia",
            "Tipo",
        ]
    ]
    for fila in agrupadas.values():
        estacion = " ".join(
            parte
            for parte in (fila.get("red"), fila.get("estacion"))
            if parte
        )
        datos.append(
            [
                estacion,
                _texto(fila.get("fase")),
                _texto(fila.get("hora_pick")),
                _texto(fila.get("t_seg")),
                _texto(fila.get("residual")),
                _texto(fila.get("peso")),
                _texto(fila.get("distancia_km")),
                ", ".join(fila.get("_tipos") or []),
            ]
        )
    return datos


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

        evidencia = _evidencia(evento)
        documento.add_paragraph("")
        documento.add_heading("Evidencia de fases", level=2)
        if evidencia:
            tabla_evidencia = documento.add_table(
                rows=1, cols=len(evidencia[0])
            )
            tabla_evidencia.style = "Table Grid"
            for celda, titulo in zip(
                tabla_evidencia.rows[0].cells, evidencia[0]
            ):
                celda.text = titulo
            for fila in evidencia[1:]:
                celdas = tabla_evidencia.add_row().cells
                for celda, valor in zip(celdas, fila):
                    celda.text = valor
        else:
            documento.add_paragraph("Sin inconsistencia de fases.")

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
                Paragraph(escape(str(clave)), estilos["RevisionCell"]),
                Paragraph(escape(str(valor)), estilos["RevisionCell"]),
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
        historia.append(Spacer(1, 0.3 * cm))
        historia.append(
            Paragraph("Evidencia de fases", estilos["Heading2"])
        )
        evidencia = _evidencia(evento)
        if evidencia:
            filas = [
                [
                    Paragraph(escape(str(valor)), estilos["RevisionCell"])
                    for valor in fila
                ]
                for fila in evidencia
            ]
            tabla = Table(
                filas,
                colWidths=[
                    3.6 * cm,
                    1.2 * cm,
                    4.2 * cm,
                    1.5 * cm,
                    2.0 * cm,
                    1.2 * cm,
                    2.0 * cm,
                    6.3 * cm,
                ],
                repeatRows=1,
            )
            tabla.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                        (
                            "BACKGROUND",
                            (0, 0),
                            (-1, 0),
                            colors.whitesmoke,
                        ),
                    ]
                )
            )
            historia.append(tabla)
        else:
            historia.append(
                Paragraph(
                    "Sin inconsistencia de fases.",
                    estilos["RevisionSmall"],
                )
            )

    documento.build(historia)
