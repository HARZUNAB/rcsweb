"""Pruebas de miniaturas, mapas y rutas de imágenes."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.extensions import db
from app.models import Job, nuevo_uuid
from app.services import plots
from app.services.extent import (
    MARGEN_MAXIMO,
    MARGEN_MINIMO,
    MARGEN_UN_EVENTO,
    margen_planta_eventos,
)
from app.services.workspace import crear_workspace

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 128


def test_fuente_por_tabla():
    assert plots._fuente("no_publicados", "seisan") == "seisan"
    assert plots._fuente("no_actualizados", "seiscomp") == "seiscomp"
    assert plots._fuente("repetidos", "publica_estricto") == "eventquery"
    assert plots._fuente("repetidos", "seiscomp_amplio") == "seiscomp"
    assert plots._fuente("repetidos", "seisan_exclu") == "seisan"


def test_eventos_no_publicados_y_no_actualizados():
    no_pub = {
        "Fecha_Hora": "2026-10-01 00:00:00",
        "Latitud": "-30.0",
        "Longitud": "-71.0",
        "Prof.": "10.0",
        "Mag.": "3.0",
        "Tipo_mag.": "ML",
        "Analista": "ana",
    }
    eventos = plots._eventos("no_publicados", "x.csv", [no_pub], 0)
    assert len(eventos) == 1
    assert eventos[0]["rol"] == "local"
    assert eventos[0]["latitud"] == -30.0

    no_act = {
        "fecha_local": "2026-10-01 00:00:00",
        "lat_local": "-30.0",
        "lon_local": "-71.0",
        "prof_local": "10.0",
        "mag_local": "3.0",
        "tipo_mag_local": "ML",
        "analista": "ana",
        "fecha_eventquery": "2026-10-01 00:00:00",
        "lat_eventquery": "-30.1",
        "lon_eventquery": "-71.1",
        "prof_eventquery": "12.0",
        "mag_eventquery": "3.1",
        "tipo_mag_eventquery": "ML",
    }
    eventos = plots._eventos("no_actualizados", "x.csv", [no_act], 0)
    assert [evento["rol"] for evento in eventos] == ["local", "publicado"]


def test_eventos_no_actualizados_propagan_analista_probable():
    fila = {
        "fecha_local": "2026-10-01 00:00:00",
        "lat_local": "-30.0",
        "lon_local": "-71.0",
        "prof_local": "10.0",
        "mag_local": "3.0",
        "tipo_mag_local": "ML",
        "analista": "beto",
        "fecha_eventquery": "2026-10-01 00:00:00",
        "lat_eventquery": "-30.1",
        "lon_eventquery": "-71.1",
        "prof_eventquery": "12.0",
        "mag_eventquery": "3.1",
        "tipo_mag_eventquery": "ML",
    }

    eventos = plots._eventos(
        "no_actualizados",
        "no_actualizados_seisan.csv",
        [fila],
        0,
        opcion="seisan",
        analista_publicado="SeisComp: cris; Seisan: beto",
    )

    assert eventos[0]["analista"] == "beto"
    assert eventos[0]["analista_etiqueta"] == "Analista"
    assert eventos[1]["analista"] == "SeisComp: cris; Seisan: beto"
    assert eventos[1]["analista_etiqueta"] == "Analista probable"

    for posicion, evento in enumerate(eventos):
        evento["along_km"] = float(posicion * 10)
    datos = plots.perfil_desde_eventos(
        eventos,
        {"id": "P1", "slab": {}},
        "seisan",
        "no_actualizados",
    )

    assert datos["eventos"][0]["analista_etiqueta"] == "Analista"
    assert datos["eventos"][1]["analista_etiqueta"] == "Analista probable"
    assert datos["eventos"][1]["analista"] == "SeisComp: cris; Seisan: beto"


def test_eventos_catalogo_eventquery_usa_analista_probable():
    fila = {
        "Fecha_Hora": "2026-10-01 00:00:00",
        "Latitud": "-30.0",
        "Longitud": "-71.0",
        "Prof.": "10.0",
        "Mag.": "3.0",
        "Tipo_mag.": "ML",
        "Analista probable": "SeisComp: cris; Seisan: beto",
        "Percep.": "",
    }

    eventos = plots._eventos(
        "catalogos",
        "catalogo_eventquery.csv",
        [fila],
        0,
        opcion="eventquery",
    )

    assert len(eventos) == 1
    assert eventos[0]["analista"] == "SeisComp: cris; Seisan: beto"
    assert eventos[0]["analista_etiqueta"] == "Analista probable"


def test_eventos_repetidos_publicados_combinan_analistas():
    fila = {
        "fecha_hora": "2026-10-01 00:00:00",
        "latitud": "-30.0",
        "longitud": "-71.0",
        "prof": "10.0",
        "mag": "3.0",
        "tipomag": "ML",
        "analista_seisan": "beto",
        "analista_seiscomp": "cris",
        "percibido": "",
    }

    eventos = plots._eventos(
        "repetidos",
        "repetidos_publica_amplio.csv",
        [fila],
        0,
        opcion="publica_amplio",
    )

    assert len(eventos) == 1
    assert eventos[0]["analista"] == "SeisComp: cris; Seisan: beto"
    assert eventos[0]["analista_etiqueta"] == "Analista probable"


def test_ruta_cache_no_permite_salir(tmp_path):
    with pytest.raises(ValueError):
        plots._ruta_cache(tmp_path, "miniaturas", "no_publicados", "../fuera.csv", 0)


def test_ruta_cache_permite_ruta_anidada(tmp_path):
    ruta = plots._ruta_cache(
        tmp_path,
        "miniaturas",
        "catalogos",
        "resultados/catalogo_eventquery.csv",
        3,
    )

    assert ruta.name == "3.png"
    assert ruta.parent.name == "catalogo_eventquery"
    assert "resultados" in ruta.parts
    assert ruta.parent.is_dir()


def test_generar_miniatura_catalogo_usa_ruta_anidada(app, tmp_path, monkeypatch):
    app.config["RCS_CORE_PATH"] = tmp_path / "core"
    workspace = tmp_path / "ws"
    (workspace / "plots").mkdir(parents=True)
    filas = [
        {
            "Fecha_Hora": "2026-10-01 00:00:00",
            "Latitud": "-30.0",
            "Longitud": "-71.0",
            "Prof.": "10.0",
            "Mag.": "3.0",
            "Tipo_mag.": "ML",
            "Analista": "ana",
        }
    ]
    monkeypatch.setattr(plots, "_dibujar_miniatura", lambda eventos, perfil: PNG)
    monkeypatch.setattr(plots, "_perfiles", lambda: [])

    with app.app_context():
        png = plots.generar_miniatura(
            workspace,
            "catalogos",
            "resultados/catalogo_eventquery.csv",
            filas,
            0,
        )

    destino = (
        workspace
        / "plots"
        / "miniaturas"
        / "catalogos"
        / "resultados"
        / "catalogo_eventquery"
        / "0.png"
    )
    assert png == PNG
    assert destino.is_file()


def test_placeholder_es_png():
    datos = plots._placeholder("Sin perfil", ancho=260, alto=110)
    assert datos.startswith(b"\x89PNG\r\n\x1a\n")


def _job_done():
    job = Job(
        id=nuevo_uuid(),
        period_start=datetime(2026, 10, 1, tzinfo=UTC),
        period_end=datetime(2026, 10, 31, tzinfo=UTC),
        status="done",
    )
    db.session.add(job)
    db.session.commit()
    workspace = crear_workspace(job.id)
    (workspace / "resultados").mkdir(parents=True, exist_ok=True)
    (workspace / "resultados" / "no_publicados_seisan.csv").write_text(
        "Fecha_Hora,Latitud,Longitud,Prof.,Mag.,Tipo_mag.,Analista\n"
        "2026-10-01 00:00:00,-30.0,-71.0,10.0,3.0,ML,ana\n",
        encoding="utf-8",
    )
    return job


def test_ruta_miniatura_y_mapa(client, login, monkeypatch):
    job = _job_done()
    login()
    monkeypatch.setattr("app.blueprints.results.generar_miniatura", lambda *args, **kwargs: PNG)
    monkeypatch.setattr("app.blueprints.results.generar_mapa", lambda *args, **kwargs: PNG)

    respuesta = client.get(f"/jobs/{job.id}/resultados/no_publicados/seisan/0/miniatura.png")
    assert respuesta.status_code == 200
    assert respuesta.mimetype == "image/png"
    assert respuesta.data.startswith(b"\x89PNG")

    respuesta = client.get(f"/jobs/{job.id}/resultados/no_publicados/seisan/0/mapa.png")
    assert respuesta.status_code == 200
    assert respuesta.mimetype == "image/png"

    assert (
        client.get(f"/jobs/{job.id}/resultados/no_publicados/seisan/99/miniatura.png").status_code
        == 404
    )


def test_generar_miniatura_cachea(app, tmp_path, monkeypatch):
    app.config["RCS_CORE_PATH"] = tmp_path / "core"
    workspace = tmp_path / "ws"
    (workspace / "plots").mkdir(parents=True)
    filas = [
        {
            "Fecha_Hora": "2026-10-01 00:00:00",
            "Latitud": "-30.0",
            "Longitud": "-71.0",
            "Prof.": "10.0",
            "Mag.": "3.0",
            "Tipo_mag.": "ML",
            "Analista": "ana",
        }
    ]
    llamadas = []

    def _falso(eventos, perfil):
        llamadas.append(1)
        return PNG

    monkeypatch.setattr(plots, "_dibujar_miniatura", _falso)
    monkeypatch.setattr(plots, "_perfiles", lambda: [])

    with app.app_context():
        primero = plots.generar_miniatura(
            workspace, "no_publicados", "no_publicados_seisan.csv", filas, 0
        )
        segundo = plots.generar_miniatura(
            workspace, "no_publicados", "no_publicados_seisan.csv", filas, 0
        )

    assert primero == segundo == PNG
    assert len(llamadas) == 1


def test_clasificar_eventos_marca_sospechosos_y_residuo(monkeypatch):
    eventos = [
        {
            "rol": "local",
            "latitud": -30.0,
            "longitud": -71.0,
            "prof": 40.0,
            "along_km": 10.0,
            "perp_km": 2.0,
        },
        {
            "rol": "publicado",
            "latitud": -30.1,
            "longitud": -71.1,
            "prof": 20.0,
            "along_km": 20.0,
            "perp_km": 3.0,
        },
    ]
    monkeypatch.setattr(plots, "_eventos", lambda *args, **kwargs: eventos)
    monkeypatch.setattr(plots, "_perfiles", lambda: [{"id": "P1"}])
    monkeypatch.setattr(
        plots,
        "_asignar",
        lambda filas, perfiles: (filas, {"id": "P1"}),
    )
    monkeypatch.setattr(
        plots,
        "_residuo_slab",
        lambda evento, perfil: 42.0 if evento["rol"] == "local" else 5.0,
    )
    monkeypatch.setattr(
        plots,
        "_es_sospechoso",
        lambda evento: evento["rol"] == "local",
    )

    clasificados, perfil = plots.clasificar_eventos("no_actualizados", "x.csv", [], 0)

    assert perfil == {"id": "P1"}
    assert clasificados[0]["residuo_km"] == 42.0
    assert clasificados[0]["sospechoso"] is True
    assert clasificados[1]["residuo_km"] == 5.0
    assert clasificados[1]["sospechoso"] is False


def test_marcar_sospechosos_propaga_por_coordenadas():
    puntos = [
        {"lat": -30.0, "lon": -71.0},
        {"lat": -30.1, "lon": -71.1},
        {"lat": -40.0, "lon": -73.0},
    ]
    eventos = [
        {"latitud": -30.0, "longitud": -71.0, "sospechoso": True},
        {"latitud": -30.1, "longitud": -71.1, "sospechoso": False},
    ]

    plots.marcar_sospechosos(puntos, eventos)

    assert [punto["sospechoso"] for punto in puntos] == [True, False, False]


def test_perfil_mapa_incluye_topo_slab_y_frontera(monkeypatch):
    eventos = [
        {
            "rol": "local",
            "latitud": -30.0,
            "longitud": -71.0,
            "prof": 10.0,
            "fecha hora": "2026-10-01 00:00:00",
            "magnitud": "2.5",
            "tipo": "ML",
            "analista": "ana",
        },
        {
            "rol": "publicado",
            "latitud": -30.1,
            "longitud": -71.1,
            "prof": 20.0,
            "fecha hora": "2026-10-01 00:00:00",
            "magnitud": "2.6",
            "tipo": "ML",
            "analista": "",
        },
    ]

    monkeypatch.setattr(plots, "_eventos", lambda *args, **kwargs: eventos)
    monkeypatch.setattr(plots, "_perfiles", lambda: [{"id": "P1"}])
    monkeypatch.setattr(
        plots,
        "_asignar",
        lambda filas, perfiles: (
            [
                {**filas[0], "along_km": 0.0, "perp_km": 0.0},
                {**filas[1], "along_km": 10.0, "perp_km": 2.0},
            ],
            {
                "id": "P1",
                "topo_p": [0.0, 10.0],
                "topo_alt": [0.0, 1000.0],
                "slab": {"p": [0.0, 10.0], "depth": [20.0, float("nan")]},
            },
        ),
    )
    monkeypatch.setattr(plots, "texto_frontera_coords", lambda lat, lon: "Argentina — 12.0 km")

    datos = plots.perfil_mapa("no_actualizados", "no_actualizados_seisan.csv", [], 0, "seiscomp")

    assert datos is not None
    assert datos["topo_p"] == [0.0, 10.0]
    assert datos["topo_alt"] == [0.0, 1000.0]
    assert datos["slab_depth"] == [20.0, None]
    assert len(datos["eventos"]) == 2
    assert datos["eventos"][0]["fuente"] == "seiscomp"
    assert datos["eventos"][0]["color"] == "#ffff00"
    assert datos["eventos"][1]["fuente"] == "eventquery"
    assert datos["eventos"][1]["color"] == "#ffffff"
    assert datos["eventos"][1]["rol"] == "publicado"
    assert datos["eventos"][0]["dist_km"] == 0.0
    assert datos["eventos"][0]["frontera"] == "Argentina — 12.0 km"


def test_perfil_mapa_sin_perfil_devuelve_none(monkeypatch):
    monkeypatch.setattr(
        plots,
        "_eventos",
        lambda *args, **kwargs: [{"rol": "local", "latitud": -30, "longitud": -71}],
    )
    monkeypatch.setattr(plots, "_perfiles", lambda: [])
    monkeypatch.setattr(plots, "_asignar", lambda filas, perfiles: (filas, None))

    assert plots.perfil_mapa("no_publicados", "x.csv", [], 0, "seiscomp") is None


def test_resumen_mapa_no_publicado():
    filas = [
        {
            "Fecha_Hora": "2026-10-13 09:55:59",
            "Latitud": "-23.007",
            "Longitud": "-69.027",
            "Prof.": "128.5",
            "Mag.": "2.8",
            "Tipo_mag.": "ML",
            "Analista": "maca",
            "Publicado_en": "",
            "Estado": "Ambiguo: 2 candidatos en SeisComp",
        }
    ]
    resumen = plots.resumen_mapa(
        "no_publicados", "No publicados · Seisan", filas, 0, "x.csv", "job1"
    )
    assert resumen is not None
    assert resumen["titulo"] == "No publicados · Seisan"
    texto = " ".join(resumen["filas"])
    assert "2026-10-13 09:55:59" in texto
    assert "2.8 ML" in texto
    assert "128.5" in texto
    assert "-23.007" in texto
    assert "maca" in texto
    assert "Ambiguo: 2 candidatos" in texto
    assert "trabajo job1" in resumen["pie"]


def test_resumen_mapa_no_actualizado():
    filas = [
        {
            "fecha_local": "2026-10-01 10:00:00",
            "lat_local": "-30.0",
            "lon_local": "-71.0",
            "prof_local": "20.0",
            "mag_local": "3.0",
            "tipo_mag_local": "ML",
            "fecha_eventquery": "2026-10-01 10:00:10",
            "lat_eventquery": "-30.010",
            "lon_eventquery": "-71.010",
            "prof_eventquery": "21.0",
            "mag_eventquery": "3.1",
            "tipo_mag_eventquery": "ML",
            "analista": "ana",
            "dt_seg": "10",
            "dlat": "0.010",
            "dlon": "0.010",
            "dist_km": "1.5",
            "publicacion_probable": "Alta",
            "revision": "Sí",
            "discrepancias": "lat, lon",
        }
    ]
    resumen = plots.resumen_mapa(
        "no_actualizados", "No actualizados · Seisan", filas, 0, "x.csv", "job2"
    )
    texto = " ".join(resumen["filas"] + [resumen["nota"] or ""])
    assert len(resumen["filas"]) == 2
    assert resumen["filas"][0].startswith("Local ·")
    assert resumen["filas"][1].startswith("Publicado ·")
    assert "\n" not in " ".join(resumen["filas"])
    assert "Δt 10 s" in texto
    assert "Alta" in texto
    assert "lat, lon" in texto


def test_resumen_mapa_repetido():
    filas = [
        {
            "fecha_hora": "2026-10-01 00:00:00",
            "latitud": "-30.0",
            "longitud": "-71.0",
            "prof": "10.0",
            "mag": "2.5",
            "tipomag": "ML",
            "analista": "ana",
            "referencia": "Prueba",
            "percibido": "f",
        }
    ]
    resumen = plots.resumen_mapa(
        "repetidos", "Repetidos · Publicados", filas, 0, "x.csv", "job3"
    )
    texto = " ".join(resumen["filas"])
    assert len(resumen["filas"]) == 1
    assert resumen["filas"][0].startswith("Seleccionado ·")
    assert "2.5 ML" in texto
    assert "Referencia: Prueba" in texto


def test_componer_resumen_agrega_encabezado():
    from io import BytesIO

    from PIL import Image

    base = Image.new("RGB", (240, 120), "white")
    buffer = BytesIO()
    base.save(buffer, format="PNG")
    resumen = {
        "titulo": "No publicados · Seisan",
        "filas": ["2026-10-13 09:55:59 | 2.8 ML"],
        "pie": "RCS Web · trabajo job1",
    }
    final = plots._componer_resumen(buffer.getvalue(), resumen)
    imagen = Image.open(BytesIO(final))
    assert imagen.width == 240
    assert imagen.height > 120


def test_margen_un_evento_usa_vista_regional():
    eventos = [{"latitud": "-23.0", "longitud": "-69.0"}]
    assert margen_planta_eventos(eventos) == MARGEN_UN_EVENTO


def test_margen_un_evento_repetido_usa_vista_regional():
    eventos = [
        {"latitud": "-23.0", "longitud": "-69.0"},
        {"latitud": "-23.0", "longitud": "-69.0"},
    ]
    assert margen_planta_eventos(eventos) == MARGEN_UN_EVENTO


def test_margen_soluciones_cercanas_se_acerca():
    eventos = [
        {"latitud": "-23.000", "longitud": "-69.000"},
        {"latitud": "-23.001", "longitud": "-69.001"},
    ]
    assert margen_planta_eventos(eventos) == pytest.approx(0.01)


def test_margen_soluciones_casi_identicas_usa_el_piso():
    eventos = [
        {"latitud": "-23.00000", "longitud": "-69.00000"},
        {"latitud": "-23.00001", "longitud": "-69.00001"},
    ]
    assert margen_planta_eventos(eventos) == MARGEN_MINIMO


def test_margen_soluciones_separadas_crece_con_la_separacion():
    eventos = [
        {"latitud": "-23.0", "longitud": "-69.0"},
        {"latitud": "-23.0", "longitud": "-69.6"},
    ]
    assert margen_planta_eventos(eventos) == pytest.approx(0.3)


def test_margen_grupo_disperso_usa_el_maximo():
    eventos = [
        {"latitud": "-23.0", "longitud": "-69.0"},
        {"latitud": "-33.0", "longitud": "-71.0"},
    ]
    assert margen_planta_eventos(eventos) == MARGEN_MAXIMO


def test_margen_sin_coordenadas_devuelve_none():
    assert margen_planta_eventos([]) is None
    assert margen_planta_eventos(None) is None
    assert margen_planta_eventos([{"latitud": "x", "longitud": "-69.0"}]) is None
    assert margen_planta_eventos([{"latitud": "-23.0"}]) is None


def test_fuente_imagen_usa_el_tamano_solicitado():
    fuente = plots._fuente_imagen("DejaVuSans.ttf", 22)
    assert getattr(fuente, "size", None) == 22


def test_componer_resumen_crece_con_una_fila_por_evento():
    from io import BytesIO

    from PIL import Image

    base = Image.new("RGB", (800, 200), "white")
    buffer = BytesIO()
    base.save(buffer, format="PNG")
    una = {
        "titulo": "No actualizados · Seisan",
        "filas": ["Local · 2026-10-01 | 3.0 ML"],
        "pie": "RCS Web · trabajo job1",
    }
    dos = {
        "titulo": "No actualizados · Seisan",
        "filas": [
            "Local · 2026-10-01 | 3.0 ML",
            "Publicado · 2026-10-01 | 3.1 ML",
        ],
        "pie": "RCS Web · trabajo job1",
    }
    alto_una = Image.open(
        BytesIO(plots._componer_resumen(buffer.getvalue(), una))
    ).height
    alto_dos = Image.open(
        BytesIO(plots._componer_resumen(buffer.getvalue(), dos))
    ).height
    assert alto_dos > alto_una


def test_resumen_mapa_repetido_una_fila_por_solucion(monkeypatch):
    filas = [
        {
            "fecha_hora": "2026-10-01 00:00:00",
            "latitud": "-30.0",
            "longitud": "-71.0",
            "prof": "10.0",
            "mag": "2.5",
            "tipomag": "ML",
            "analista": "ana",
        },
        {
            "fecha_hora": "2026-10-01 00:00:02",
            "latitud": "-30.002",
            "longitud": "-71.003",
            "prof": "11.0",
            "mag": "2.4",
            "tipomag": "ML",
            "analista": "beto",
        },
    ]
    monkeypatch.setattr(
        plots,
        "grupo_repetidos",
        lambda _filas, _indice, _archivo: [
            {"fila": filas[1], "_fila": 1},
            {"fila": filas[0], "_fila": 0},
        ],
    )
    resumen = plots.resumen_mapa(
        "repetidos", "Repetidos · Publicados", filas, 0, "x.csv", "job3"
    )
    assert len(resumen["filas"]) == 2
    assert resumen["filas"][0].startswith("Seleccionado ·")
    assert resumen["filas"][1].startswith("Solución ·")
    assert "Grupo: 2 soluciones" in resumen["nota"]
