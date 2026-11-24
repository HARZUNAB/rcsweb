"""Genera los manuales en DOCX a partir de los Markdown de ``docs/``.

La fuente de verdad son los archivos Markdown. El script convierte cada uno a
HTML, lo recorre y construye un DOCX con portada, índice, tablas, bloques de
código e imágenes incrustadas.

Requisitos:
    - ``markdown``, ``beautifulsoup4``, ``python-docx`` y ``Pillow`` en el
      entorno de desarrollo.

Uso:
    .venv/bin/python scripts/generar_docs.py
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlparse

import markdown
from bs4 import BeautifulSoup, NavigableString, Tag
from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image as PILImage

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
IMG = DOCS / "img"

MANUALES = {
    "manual_usuario": (
        "Manual de usuario",
        "Guía de uso de RCS Web",
    ),
    "manual_tecnico": (
        "Manual técnico",
        "Instalación, operación y mantenimiento",
    ),
    "guia_despliegue_prueba": (
        "Guía de despliegue de prueba",
        "Cuenta rcswebtest, acceso seguro y actualizaciones",
    ),
}

PARTES = {
    "manual_usuario": ["manual_usuario.md"],
    "manual_tecnico": ["manual_tecnico.md", "anexos/D_parametros.md"],
    "guia_despliegue_prueba": ["guia_despliegue_prueba.md"],
}

MESES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

AZUL = RGBColor(0x1F, 0x3A, 0x5F)
GRIS = RGBColor(0x52, 0x60, 0x6D)
GRIS_CLARO = RGBColor(0x7B, 0x87, 0x94)


def _version() -> str:
    datos = tomllib.loads((RAIZ / "pyproject.toml").read_text(encoding="utf-8"))
    return datos["project"]["version"]


def _fecha_larga() -> str:
    hoy = date.today()
    return f"{MESES[hoy.month - 1]} de {hoy.year}"


def _sombra(celda, color: str) -> None:
    tc_pr = celda._tc.get_or_add_tcPr()
    sombra = OxmlElement("w:shd")
    sombra.set(qn("w:fill"), color)
    tc_pr.append(sombra)


def _estilos(doc: Document) -> None:
    normal = doc.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.space_after = Pt(4)

    for nombre, tamano in (("Heading 1", 19), ("Heading 2", 14), ("Heading 3", 12)):
        estilo = doc.styles[nombre]
        estilo.font.name = "Calibri"
        estilo.font.size = Pt(tamano)
        estilo.font.color.rgb = AZUL
        estilo.font.bold = True
        estilo.paragraph_format.space_before = Pt(14)
        estilo.paragraph_format.space_after = Pt(5)
        estilo.paragraph_format.keep_with_next = True

    if "Code Block" not in [estilo.name for estilo in doc.styles]:
        from docx.enum.style import WD_STYLE_TYPE

        codigo = doc.styles.add_style("Code Block", WD_STYLE_TYPE.PARAGRAPH)
        codigo.font.name = "Consolas"
        codigo.font.size = Pt(8.5)
        codigo.paragraph_format.space_after = Pt(0)
        codigo.paragraph_format.space_before = Pt(0)


def _texto(elemento: Tag) -> str:
    return re.sub(r"\s+", " ", elemento.get_text(" ", strip=True)).strip()


def _runs(parrafo, elemento, *, negrita=False, cursiva=False) -> None:
    """Agrega el contenido en línea de un elemento HTML a un párrafo."""
    for hijo in elemento.children:
        if isinstance(hijo, NavigableString):
            texto = str(hijo)
            if texto.strip():
                run = parrafo.add_run(texto)
                run.bold = negrita
                run.italic = cursiva
            continue
        if not isinstance(hijo, Tag):
            continue
        nombre = hijo.name
        if nombre in ("strong", "b"):
            _runs(parrafo, hijo, negrita=True, cursiva=cursiva)
        elif nombre in ("em", "i"):
            _runs(parrafo, hijo, negrita=negrita, cursiva=True)
        elif nombre == "code":
            run = parrafo.add_run(_texto(hijo))
            run.font.name = "Consolas"
            run.font.size = Pt(8.8)
        elif nombre == "br":
            parrafo.add_run().add_break()
        elif nombre == "a":
            run = parrafo.add_run(_texto(hijo))
            run.font.color.rgb = AZUL
            run.underline = True
        elif nombre in ("sub", "sup"):
            run = parrafo.add_run(_texto(hijo))
            if nombre == "sub":
                run.font.subscript = True
            else:
                run.font.superscript = True
        elif nombre == "img":
            _imagen(parrafo, hijo)
        else:
            _runs(parrafo, hijo, negrita=negrita, cursiva=cursiva)


def _imagen(parrafo, img: Tag) -> None:
    src = img.get("src", "")
    if src.startswith("file://"):
        ruta = Path(unquote(urlparse(src).path))
    else:
        ruta = (DOCS / src).resolve()
    if not ruta.is_file():
        return
    with PILImage.open(ruta) as datos:
        ancho, alto = datos.size
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = parrafo.add_run()
    if alto / ancho > 21 / 16:
        run.add_picture(str(ruta), height=Cm(21))
    else:
        run.add_picture(str(ruta), width=Cm(16))


def _codigo(doc: Document, pre: Tag) -> None:
    parrafo = doc.add_paragraph(style="Code Block")
    sombra = OxmlElement("w:shd")
    sombra.set(qn("w:fill"), "F1F4F8")
    parrafo._p.get_or_add_pPr().append(sombra)
    lineas = pre.get_text().strip("\n").splitlines() or [""]
    for indice, linea in enumerate(lineas):
        run = parrafo.add_run(linea)
        run.font.name = "Consolas"
        run.font.size = Pt(8.5)
        if indice < len(lineas) - 1:
            run.add_break()


def _tabla(doc: Document, tabla: Tag) -> None:
    filas = tabla.find_all("tr")
    if not filas:
        return
    columnas = max(len(fila.find_all(["th", "td"])) for fila in filas)
    textos = []
    for fila in filas:
        textos.append(
            [_texto(celda) for celda in fila.find_all(["th", "td"])]
        )
    pesos = []
    for indice in range(columnas):
        palabras = []
        for fila in textos:
            if indice < len(fila):
                palabras.extend(fila[indice].split())
        largo = max((len(palabra) for palabra in palabras), default=0)
        pesos.append(max(4.0, largo * 0.7))
    total = sum(pesos) or 1.0
    anchos = [max(1.3, 16.0 * peso / total) for peso in pesos]
    factor = 16.0 / sum(anchos) if sum(anchos) else 1.0
    anchos = [ancho * factor for ancho in anchos]

    tabla_doc = doc.add_table(rows=0, cols=columnas)
    tabla_doc.style = "Table Grid"
    tabla_doc.alignment = WD_TABLE_ALIGNMENT.CENTER
    tabla_doc.autofit = False
    for indice, ancho in enumerate(anchos):
        tabla_doc.columns[indice].width = Cm(ancho)
    for fila in filas:
        celdas = fila.find_all(["th", "td"])
        fila_doc = tabla_doc.add_row().cells
        for indice, celda in enumerate(celdas):
            if indice >= columnas:
                break
            fila_doc[indice].width = Cm(anchos[indice])
            parrafo = fila_doc[indice].paragraphs[0]
            es_cabecera = celda.name == "th"
            referencia = re.fullmatch(
                r"\[\[PAGEREF:([A-Za-z0-9_]+)\]\]", _texto(celda)
            )
            if referencia:
                _pageref(parrafo, referencia.group(1))
            else:
                _runs(parrafo, celda, negrita=es_cabecera)
            for run in parrafo.runs:
                run.font.size = Pt(9)
            if es_cabecera:
                _sombra(fila_doc[indice], "EEF4FA")


def _lista(doc: Document, lista: Tag, nivel: int = 0) -> None:
    estilo = "List Bullet" if lista.name == "ul" else "List Number"
    for item in lista.find_all("li", recursive=False):
        parrafo = doc.add_paragraph(style=estilo)
        if nivel:
            parrafo.paragraph_format.left_indent = Cm(0.6 * nivel)
        _runs(parrafo, item)
        for sublista in item.find_all(["ul", "ol"], recursive=False):
            _lista(doc, sublista, nivel + 1)


def _cuerpo(doc: Document, soup: BeautifulSoup) -> None:
    for elemento in soup.children:
        if not isinstance(elemento, Tag):
            continue
        nombre = elemento.name
        if nombre in ("h1", "script", "style"):
            continue
        if nombre in ("h2", "h3", "h4", "h5"):
            texto = _texto(elemento)
            parrafo = doc.add_heading(texto, level=int(nombre[1]))
            _bookmark(parrafo, texto)
        elif nombre == "p":
            imagenes = elemento.find_all("img")
            if imagenes and not _texto(elemento):
                for imagen in imagenes:
                    _imagen(doc.add_paragraph(), imagen)
            else:
                parrafo = doc.add_paragraph()
                _runs(parrafo, elemento)
                for imagen in imagenes:
                    _imagen(doc.add_paragraph(), imagen)
        elif nombre in ("ul", "ol"):
            _lista(doc, elemento)
        elif nombre == "table":
            _tabla(doc, elemento)
        elif nombre == "pre":
            _codigo(doc, elemento)
        elif nombre == "blockquote":
            parrafo = doc.add_paragraph()
            parrafo.paragraph_format.left_indent = Cm(0.5)
            _runs(parrafo, elemento, cursiva=True)
            for run in parrafo.runs:
                run.font.color.rgb = GRIS
        elif nombre == "img":
            _imagen(doc.add_paragraph(), elemento)
        elif nombre == "hr":
            doc.add_paragraph()


def _portada(doc: Document, titulo: str, subtitulo: str) -> None:
    for _ in range(2):
        doc.add_paragraph()
    marca = doc.add_paragraph()
    marca.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = marca.add_run("RCS Web")
    run.bold = True
    run.font.size = Pt(13)
    run.font.color.rgb = AZUL

    parrafo = doc.add_paragraph()
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = parrafo.add_run(titulo)
    run.bold = True
    run.font.size = Pt(30)
    run.font.color.rgb = AZUL

    parrafo = doc.add_paragraph()
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = parrafo.add_run(subtitulo)
    run.font.size = Pt(14)
    run.font.color.rgb = GRIS

    for _ in range(3):
        doc.add_paragraph()
    parrafo = doc.add_paragraph()
    parrafo.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = parrafo.add_run(f"Versión {_version()}\n{_fecha_larga()}")
    run.font.size = Pt(11)
    run.font.color.rgb = GRIS_CLARO
    doc.add_page_break()


def _indice(doc: Document) -> None:
    """Índice real de Word, con números de página.

    El campo TOC se actualiza al abrir el DOCX (``updateFields``) o con F9.
    En Markdown no existe paginación; las páginas viven en el DOCX.
    """
    parrafo = doc.add_paragraph()
    run = parrafo.add_run("Contenido")
    run.bold = True
    run.font.size = Pt(19)
    run.font.color.rgb = AZUL
    parrafo.paragraph_format.space_before = Pt(14)
    parrafo.paragraph_format.space_after = Pt(5)

    campo = OxmlElement("w:fldSimple")
    campo.set(qn("w:instr"), 'TOC \\o "1-3" \\h \\z \\u')
    campo.set(qn("w:dirty"), "true")
    relleno = OxmlElement("w:r")
    texto = OxmlElement("w:t")
    texto.text = (
        "Actualice el índice con F9 o al abrir el documento para ver "
        "las páginas."
    )
    relleno.append(texto)
    campo.append(relleno)
    parrafo._p.append(campo)
    doc.add_page_break()


def _actualizar_campos(doc: Document) -> None:
    """Pide a Word/LibreOffice que actualice TOC y PAGEREF al abrir."""
    ajustes = doc.settings.element
    for anterior in ajustes.findall(qn("w:updateFields")):
        ajustes.remove(anterior)
    actualizar = OxmlElement("w:updateFields")
    actualizar.set(qn("w:val"), "true")
    ajustes.append(actualizar)


_BOOKMARKS: set[str] = set()
_BOOKMARK_ID = [0]


def _nombre_bookmark(texto: str) -> str:
    coincidencia = re.match(
        r"^(Anexo [A-F])|^([A-F]\.\d+(?:\.\d+)?)", texto.strip()
    )
    if not coincidencia:
        return ""
    base = coincidencia.group(1) or coincidencia.group(2)
    return "_" + re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_")


def _bookmark(parrafo, texto: str) -> None:
    nombre = _nombre_bookmark(texto)
    if not nombre or nombre in _BOOKMARKS:
        return
    _BOOKMARKS.add(nombre)
    _BOOKMARK_ID[0] += 1
    identificador = str(_BOOKMARK_ID[0])
    inicio = OxmlElement("w:bookmarkStart")
    inicio.set(qn("w:id"), identificador)
    inicio.set(qn("w:name"), nombre)
    fin = OxmlElement("w:bookmarkEnd")
    fin.set(qn("w:id"), identificador)
    parrafo._p.insert(0, inicio)
    parrafo._p.append(fin)


def _pageref(parrafo, nombre: str) -> None:
    campo = OxmlElement("w:fldSimple")
    campo.set(qn("w:instr"), f"PAGEREF {nombre} \\h")
    campo.set(qn("w:dirty"), "true")
    run = OxmlElement("w:r")
    texto = OxmlElement("w:t")
    texto.text = "—"
    run.append(texto)
    campo.append(run)
    parrafo._p.append(campo)


def _pie(doc: Document, titulo: str) -> None:
    pie = doc.sections[0].footer.paragraphs[0]
    pie.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = pie.add_run(f"RCS Web · {titulo} · página ")
    run.font.size = Pt(8)
    run.font.color.rgb = GRIS_CLARO
    campo = OxmlElement("w:fldSimple")
    campo.set(qn("w:instr"), "PAGE")
    pie._p.append(campo)


def _texto_manual(nombre: str) -> str:
    partes = PARTES.get(nombre, [f"{nombre}.md"])
    trozos = []
    for parte in partes:
        ruta = DOCS / parte
        if not ruta.is_file():
            print(f"aviso: no existe {ruta.relative_to(RAIZ)}; se omite")
            continue
        trozos.append(ruta.read_text(encoding="utf-8"))
    return "\n\n".join(trozos)


def _convertir(nombre: str, titulo: str, subtitulo: str) -> Path:
    texto = _texto_manual(nombre)
    _BOOKMARKS.clear()
    _BOOKMARK_ID[0] = 0
    conversor = markdown.Markdown(
        extensions=["extra", "toc", "sane_lists"],
        extension_configs={"toc": {"toc_depth": "2-3"}},
    )
    soup = BeautifulSoup(conversor.convert(texto), "html.parser")

    doc = Document()
    seccion = doc.sections[0]
    seccion.page_width = Cm(21)
    seccion.page_height = Cm(29.7)
    seccion.top_margin = Cm(2)
    seccion.bottom_margin = Cm(2)
    seccion.left_margin = Cm(2.1)
    seccion.right_margin = Cm(2.1)
    _estilos(doc)
    doc.core_properties.title = titulo
    doc.core_properties.subject = subtitulo
    doc.core_properties.author = "RCS Web"
    doc.core_properties.comments = f"Versión {_version()}"

    _portada(doc, titulo, subtitulo)
    _indice(doc)
    _cuerpo(doc, soup)
    _pie(doc, titulo)
    _actualizar_campos(doc)

    salida = DOCS / f"{nombre}.docx"
    doc.save(salida)
    print(
        f"{salida.name}: {salida.stat().st_size} bytes, "
        f"{len(doc.inline_shapes)} imágenes"
    )
    return salida


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    for nombre, (titulo, subtitulo) in MANUALES.items():
        _convertir(nombre, titulo, subtitulo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
