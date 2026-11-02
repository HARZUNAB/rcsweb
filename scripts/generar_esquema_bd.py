"""Genera los diagramas de esquema de base de datos para el manual técnico."""

from __future__ import annotations

from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
IMG = RAIZ / "docs" / "img"
FUENTES = Path(matplotlib.get_data_path()) / "fonts" / "ttf"

AZUL = "#1f3a5f"
TEXTO = "#1f2933"
GRIS = "#52606d"
BORDE = "#dbe4ee"
RELLENO_ACTIVO = "#eef4fa"
RELLENO_RESERVADO = "#f7f7f4"
RELLENO_ARCHIVO = "#e8f0fb"
RELLENO_TITULO = "#ffffff"


def _fuente(tamano: int, negrita: bool = False):
    nombre = "DejaVuSans-Bold.ttf" if negrita else "DejaVuSans.ttf"
    return ImageFont.truetype(str(FUENTES / nombre), tamano)


def _texto(dibujo, x, y, texto, tamano=15, negrita=False, color=TEXTO, ancho=None):
    fuente = _fuente(tamano, negrita)
    if ancho is None:
        dibujo.text((x, y), texto, font=fuente, fill=color)
        return
    palabras = str(texto).split()
    linea = ""
    for palabra in palabras:
        candidata = (linea + " " + palabra).strip()
        if dibujo.textlength(candidata, font=fuente) <= ancho:
            linea = candidata
        else:
            dibujo.text((x, y), linea, font=fuente, fill=color)
            y += tamano + 5
            linea = palabra
    if linea:
        dibujo.text((x, y), linea, font=fuente, fill=color)


def _linea_discontinua(dibujo, inicio, fin, color=GRIS, ancho=2, paso=10):
    x1, y1 = inicio
    x2, y2 = fin
    largo = max(abs(x2 - x1), abs(y2 - y1))
    if largo == 0:
        return
    dx = (x2 - x1) / largo
    dy = (y2 - y1) / largo
    recorrido = 0
    while recorrido < largo:
        fin_tramo = min(recorrido + paso, largo)
        dibujo.line(
            (
                x1 + dx * recorrido,
                y1 + dy * recorrido,
                x1 + dx * fin_tramo,
                y1 + dy * fin_tramo,
            ),
            fill=color,
            width=ancho,
        )
        recorrido += paso * 2


def _flecha(dibujo, puntos, color=GRIS, ancho=2, discontinua=False, etiqueta=None):
    for indice in range(len(puntos) - 1):
        inicio = puntos[indice]
        fin = puntos[indice + 1]
        if discontinua:
            _linea_discontinua(dibujo, inicio, fin, color=color, ancho=ancho)
        else:
            dibujo.line((*inicio, *fin), fill=color, width=ancho)
    (x1, y1), (x2, y2) = puntos[-2], puntos[-1]
    largo = max(abs(x2 - x1), abs(y2 - y1)) or 1
    dx = (x2 - x1) / largo
    dy = (y2 - y1) / largo
    punta = 10
    base_x = x2 - dx * punta
    base_y = y2 - dy * punta
    normal_x = -dy * 5
    normal_y = dx * 5
    dibujo.polygon(
        [
            (x2, y2),
            (base_x + normal_x, base_y + normal_y),
            (base_x - normal_x, base_y - normal_y),
        ],
        fill=color,
    )
    if etiqueta:
        medio_x = (puntos[0][0] + puntos[-1][0]) / 2
        medio_y = (puntos[0][1] + puntos[-1][1]) / 2
        _texto(dibujo, medio_x + 6, medio_y - 18, etiqueta, 13, color=GRIS)


def _caja(
    dibujo,
    x,
    y,
    ancho,
    alto,
    titulo,
    campos,
    *,
    relleno=RELLENO_ACTIVO,
    borde=AZUL,
    discontinua=False,
    tamano_titulo=22,
    tamano_campo=17,
):
    if discontinua:
        _linea_discontinua(
            dibujo,
            (x, y),
            (x + ancho, y),
            color=borde,
            ancho=2,
        )
        _linea_discontinua(
            dibujo,
            (x + ancho, y),
            (x + ancho, y + alto),
            color=borde,
            ancho=2,
        )
        _linea_discontinua(
            dibujo,
            (x + ancho, y + alto),
            (x, y + alto),
            color=borde,
            ancho=2,
        )
        _linea_discontinua(
            dibujo,
            (x, y + alto),
            (x, y),
            color=borde,
            ancho=2,
        )
    else:
        dibujo.rounded_rectangle(
            (x, y, x + ancho, y + alto),
            radius=12,
            fill=relleno,
            outline=borde,
            width=2,
        )
    dibujo.line(
        (x + 2, y + 38, x + ancho - 2, y + 38),
        fill=borde,
        width=1,
    )
    _texto(dibujo, x + 14, y + 8, titulo, tamano_titulo, True, AZUL)
    cursor = y + 46
    for campo in campos:
        _texto(dibujo, x + 14, cursor, campo, tamano_campo, color=TEXTO)
        cursor += tamano_campo + 6


def _leyenda(dibujo, x, y):
    dibujo.rounded_rectangle(
        (x, y, x + 190, y + 46), radius=8, fill=RELLENO_ACTIVO, outline=AZUL, width=2
    )
    _texto(dibujo, x + 12, y + 12, "Tabla activa", 14, color=TEXTO)
    _linea_discontinua(
        dibujo,
        (x + 215, y + 12),
        (x + 285, y + 12),
        color="#7b8794",
        ancho=2,
    )
    _texto(dibujo, x + 295, y + 3, "Tabla reservada", 14, color=GRIS)
    _flecha(dibujo, [(x + 215, y + 36), (x + 285, y + 36)], color=GRIS, ancho=2)
    _texto(dibujo, x + 295, y + 27, "Clave foránea", 14, color=GRIS)


def _base_datos():
    ancho, alto = 1600, 1100
    imagen = Image.new("RGB", (ancho, alto), "white")
    dibujo = ImageDraw.Draw(imagen)

    _texto(dibujo, 50, 30, "Esquema relacional de RCS Web", 32, True, AZUL)
    _texto(
        dibujo,
        50,
        72,
        "PostgreSQL 16 · tablas activas, claves foráneas y control de migraciones",
        17,
        color=GRIS,
    )
    _leyenda(dibujo, 1160, 28)

    _caja(
        dibujo,
        220,
        130,
        320,
        155,
        "audit_log",
        [
            "PK id",
            "FK user_id → users",
            "action / entity",
            "created_at",
        ],
    )
    _caja(
        dibujo,
        620,
        130,
        330,
        175,
        "users",
        [
            "PK id",
            "username (único)",
            "role / active",
        ],
    )
    _caja(
        dibujo,
        80,
        380,
        350,
        205,
        "catalog_requests",
        [
            "PK id (UUID)",
            "mode / status",
            "FK requested_by_id → users",
        ],
    )
    _caja(
        dibujo,
        1150,
        380,
        350,
        235,
        "jobs",
        [
            "PK id (UUID)",
            "status / progress",
            "FK created_by_id → users",
            "FK catalog_request_id",
        ],
    )
    _caja(
        dibujo,
        80,
        660,
        350,
        185,
        "catalog_request_files",
        [
            "PK id",
            "FK request_id → catalog_requests",
            "kind / status",
        ],
    )
    _caja(
        dibujo,
        560,
        670,
        320,
        150,
        "job_files",
        [
            "PK id",
            "FK job_id → jobs",
            "kind / sha256",
        ],
    )
    _caja(
        dibujo,
        940,
        670,
        320,
        170,
        "job_sources",
        [
            "PK id",
            "FK job_id → jobs",
            "kind / format",
            "FK catalog_file_id",
        ],
    )
    _caja(
        dibujo,
        1300,
        670,
        250,
        150,
        "job_steps",
        [
            "PK id",
            "FK job_id → jobs",
            "script / status",
        ],
    )
    _caja(
        dibujo,
        940,
        890,
        320,
        140,
        "job_artifacts",
        [
            "PK id",
            "FK job_id → jobs",
            "tipo / ruta",
        ],
    )
    _caja(
        dibujo,
        1300,
        890,
        250,
        90,
        "alembic_version",
        ["PK version_num"],
        relleno="#f7f7f4",
        borde="#7b8794",
    )

    _flecha(dibujo, [(620, 210), (545, 210)], etiqueta="1:N")
    _flecha(dibujo, [(730, 305), (255, 380)], etiqueta="1:N")
    _flecha(dibujo, [(900, 305), (1325, 380)], etiqueta="1:N")
    _flecha(dibujo, [(430, 470), (1150, 470)], etiqueta="1:N")
    _flecha(dibujo, [(255, 585), (255, 660)], etiqueta="1:N")
    _flecha(
        dibujo,
        [(430, 760), (480, 760), (480, 855), (1100, 855), (1100, 840)],
    )
    _flecha(dibujo, [(1230, 615), (760, 670)], etiqueta="1:N")
    _flecha(dibujo, [(1300, 615), (1080, 670)], etiqueta="1:N")
    _flecha(dibujo, [(1425, 615), (1425, 670)], etiqueta="1:N")
    _flecha(
        dibujo,
        [(1500, 500), (1570, 500), (1570, 1010), (1260, 1010)],
        etiqueta="1:N",
    )

    _texto(
        dibujo,
        50,
        1055,
        "Los resultados sísmicos y mapas no se guardan en estas tablas: viven en el workspace.",
        14,
        color=GRIS,
    )
    imagen.save(IMG / "esquema_bd.png", optimize=True)
    return imagen.size


def _catalogos():
    ancho, alto = 1600, 1080
    imagen = Image.new("RGB", (ancho, alto), "white")
    dibujo = ImageDraw.Draw(imagen)

    _texto(dibujo, 50, 30, "Catálogos de fuentes y catálogo canónico", 32, True, AZUL)
    _texto(
        dibujo,
        50,
        72,
        "Los catálogos no se cargan en PostgreSQL: se normalizan como archivos y JSONL.",
        17,
        color=GRIS,
    )
    _leyenda(dibujo, 1160, 28)

    dibujo.rounded_rectangle(
        (30, 110, 830, 760),
        radius=14,
        outline="#7b8794",
        width=2,
    )
    _texto(dibujo, 50, 118, "workspace/<job_id>/", 18, True, GRIS)

    dibujo.rounded_rectangle(
        (880, 110, 1570, 1020),
        radius=14,
        outline="#7b8794",
        width=2,
    )
    _texto(dibujo, 900, 118, "PostgreSQL · esquema canónico reservado", 18, True, GRIS)

    _caja(
        dibujo,
        60,
        165,
        350,
        120,
        "Eventquery (CSV)",
        [
            "datos/new_2_<eventquery>.csv",
            "time · lat · lon · depth",
            "mag · tipo_mag · ref · perc",
        ],
        relleno=RELLENO_ARCHIVO,
    )
    _caja(
        dibujo,
        60,
        310,
        350,
        120,
        "SeisComp (CSV)",
        [
            "seiscomp_<inicio>_<fin>.csv",
            "datos/seiscomp_parametros.csv",
            "ot_utc · lat · lon · prof",
        ],
        relleno=RELLENO_ARCHIVO,
    )
    _caja(
        dibujo,
        60,
        455,
        350,
        120,
        "Seisan (select.out)",
        [
            "select.out (texto)",
            "datos/salida_collect.csv",
            "eventos · orígenes · magnitudes",
        ],
        relleno=RELLENO_ARCHIVO,
    )
    _caja(
        dibujo,
        480,
        260,
        300,
        150,
        "Pipeline / adaptadores",
        [
            "normaliza cada fuente",
            "compara y cruza resultados",
            "escribe el catálogo canónico",
        ],
    )
    _caja(
        dibujo,
        480,
        500,
        300,
        220,
        "Catálogo canónico JSONL",
        [
            "catalogo/<source_id>/eventos.jsonl",
            "source_id · event_id · event_time",
            "latitude · longitude · depth_km",
            "magnitude · agency · analyst",
            "status · is_preferred · is_published",
        ],
    )
    _caja(
        dibujo,
        930,
        160,
        330,
        180,
        "catalog_events",
        [
            "PK id · FK job_id → jobs",
            "source_id / event_id",
            "event_time · magnitude",
            "status · is_preferred",
        ],
        relleno=RELLENO_RESERVADO,
        borde="#7b8794",
        discontinua=True,
    )
    _caja(
        dibujo,
        930,
        370,
        330,
        180,
        "stations",
        [
            "PK id · FK job_id → jobs",
            "source_id",
            "network · station · channel",
            "status",
        ],
        relleno=RELLENO_RESERVADO,
        borde="#7b8794",
        discontinua=True,
    )
    _caja(
        dibujo,
        930,
        580,
        330,
        180,
        "arrivals",
        [
            "PK id · FK job_id → jobs",
            "source_id / event_id",
            "phase · pick_time",
            "pick_status · weight",
        ],
        relleno=RELLENO_RESERVADO,
        borde="#7b8794",
        discontinua=True,
    )
    _caja(
        dibujo,
        930,
        790,
        330,
        180,
        "waveform_availability",
        [
            "PK id · FK job_id → jobs",
            "source_id / event_id",
            "window_start / end · status",
        ],
        relleno=RELLENO_RESERVADO,
        borde="#7b8794",
        discontinua=True,
    )
    _caja(
        dibujo,
        60,
        800,
        350,
        130,
        "catalog_request_files",
        [
            "PK id · FK request_id",
            "kind · format · status",
            "stored_path · sha256",
        ],
    )
    _caja(
        dibujo,
        480,
        800,
        300,
        130,
        "job_sources",
        [
            "PK id · FK job_id → jobs",
            "kind · format · role",
            "capabilities (JSON)",
        ],
    )

    _flecha(dibujo, [(410, 225), (480, 320)])
    _flecha(dibujo, [(410, 370), (480, 370)])
    _flecha(dibujo, [(410, 515), (480, 430)])
    _flecha(dibujo, [(630, 410), (630, 500)], etiqueta="escribe")
    _flecha(
        dibujo,
        [(780, 540), (860, 540), (860, 250), (930, 250)],
        discontinua=True,
    )
    _flecha(
        dibujo,
        [(780, 560), (890, 560), (890, 460), (930, 460)],
        discontinua=True,
    )
    _flecha(
        dibujo,
        [(780, 580), (900, 580), (900, 670), (930, 670)],
        discontinua=True,
    )
    _flecha(
        dibujo,
        [(780, 600), (910, 600), (910, 880), (930, 880)],
        discontinua=True,
    )
    _flecha(dibujo, [(410, 865), (480, 865)])
    _flecha(dibujo, [(630, 800), (630, 720)], discontinua=True, etiqueta="enlace lógico")

    _texto(
        dibujo,
        50,
        1045,
        "Las tablas de la derecha existen por migración, pero el pipeline actual no las llena.",
        15,
        color=GRIS,
    )
    imagen.save(IMG / "esquema_catalogos.png", optimize=True)
    return imagen.size


def main():
    IMG.mkdir(parents=True, exist_ok=True)
    print("esquema_bd.png", _base_datos())
    print("esquema_catalogos.png", _catalogos())


if __name__ == "__main__":
    main()
