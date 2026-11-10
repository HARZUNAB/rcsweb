"""Pruebas del catálogo de estaciones y sus proveedores."""

from __future__ import annotations

from datetime import datetime

from app.domain.catalogs.stations import (
    CatalogoEstaciones,
    EstacionLista,
    ResolutorEstaciones,
    cargar_seisan_hyp,
    leer_station_hyp,
)


def _escribir_hyp(tmp_path, nombre, contenido):
    ruta = tmp_path / nombre
    ruta.write_text(contenido, encoding="latin-1")
    return ruta


def test_leer_station_hyp_normaliza_coordenadas(tmp_path):
    ruta = _escribir_hyp(
        tmp_path,
        "STATION0.HYP",
        "RESET TEST(02)=500.0\n"
        "  PB012102.59S 6929.24W 900 +0.16\n"
        "PATCX2049.24S 7009.17W 832 +0.15\n"
        "  RPN 2707.62S10920.04W 110 +0.02\n"
        "  LLCH3336.63S 7137.09W  30\n",
    )

    estaciones = {estacion.station: estacion for estacion in leer_station_hyp(ruta)}

    assert set(estaciones) == {"PB01", "PATCX", "RPN", "LLCH"}
    pb01 = estaciones["PB01"]
    assert abs(pb01.latitude - (-21.0431666)) < 1e-6
    assert abs(pb01.longitude - (-69.4873333)) < 1e-6
    assert pb01.elevation_m == 900.0
    assert estaciones["PATCX"].source_file == "STATION0.HYP"
    assert abs(estaciones["RPN"].longitude - (-109.334)) < 1e-3
    assert estaciones["LLCH"].elevation_m == 30.0


def test_catalogo_resuelve_duplicado_por_cercania(tmp_path):
    _escribir_hyp(
        tmp_path,
        "STATIONA.HYP",
        "  CAL 2227.52S 6855.81W2300 +0.42\n",
    )
    _escribir_hyp(
        tmp_path,
        "STATIONB.HYP",
        "  CAL 4249.37S 7238.50W 889 +0.16\n",
    )
    catalogo = cargar_seisan_hyp(tmp_path)

    norte = catalogo.resolver("CAL", lat_evento=-22.0, lon_evento=-69.0)
    sur = catalogo.resolver("CAL", lat_evento=-42.0, lon_evento=-72.0)

    assert norte is not None and norte.latitude > -30
    assert sur is not None and sur.latitude < -40


def test_catalogo_resuelve_duplicado_por_distancia_del_pick(tmp_path):
    _escribir_hyp(
        tmp_path,
        "STATION0.HYP",
        "  CAL 2227.52S 6855.81W2300 +0.42\n",
    )
    _escribir_hyp(
        tmp_path,
        "STATION1.HYP",
        "  CAL 4249.37S 7238.50W 889 +0.16\n",
    )
    catalogo = cargar_seisan_hyp(tmp_path)

    # El evento está cerca de la entrada norte, pero el pick declara 2.340 km:
    # debe ganar la entrada sur, que es la que produce esa distancia.
    elegida = catalogo.resolver(
        "CAL", lat_evento=-22.0, lon_evento=-69.0, distancia=2340.0
    )

    assert elegida is not None
    assert elegida.latitude < -40


def test_catalogo_respeta_epocas():
    catalogo = CatalogoEstaciones()
    catalogo.agregar(
        EstacionLista(
            network="C1",
            station="PB01",
            latitude=-21.0,
            longitude=-69.0,
            start_time=datetime(2020, 1, 1),
            end_time=datetime(2020, 12, 31),
            source_file="inventario",
        )
    )
    catalogo.agregar(
        EstacionLista(
            network="C1",
            station="PB01",
            latitude=-22.0,
            longitude=-70.0,
            start_time=datetime(2021, 1, 1),
            end_time=None,
            source_file="inventario",
        )
    )

    dentro = catalogo.resolver(
        "PB01", network="C1", instante=datetime(2020, 6, 1)
    )
    fuera = catalogo.resolver(
        "PB01", network="C1", instante=datetime(2019, 6, 1)
    )
    actual = catalogo.resolver(
        "PB01", network="C1", instante=datetime(2022, 6, 1)
    )

    assert dentro is not None and dentro.latitude == -21.0
    assert fuera is None
    assert actual is not None and actual.latitude == -22.0


def test_resolutor_selecciona_proveedor_por_regla(tmp_path):
    _escribir_hyp(
        tmp_path,
        "STATION0.HYP",
        "  PB012102.59S 6929.24W 900 +0.16\n",
    )
    config = {
        "providers": {
            "lista": {
                "kind": "seisan_hyp",
                "dir": str(tmp_path),
                "glob": "STATION*.HYP",
            }
        },
        "rules": [{"match": "Seisan", "provider": "lista"}],
        "default": "lista",
    }
    resolutor = ResolutorEstaciones(config)

    assert resolutor.resolver("Seisan_v9.1", "PB01") is not None
    assert resolutor.resolver("Otro", "PB01") is not None
    assert resolutor.resolver("Seisan_v9.1", "NOEXISTE") is None


def test_catalogo_no_mezcla_redes_del_inventario():
    catalogo = CatalogoEstaciones()
    catalogo.agregar(
        EstacionLista(network="C1", station="PB01", latitude=-21.0, longitude=-69.0)
    )
    catalogo.agregar(
        EstacionLista(network="CX", station="PB01", latitude=-30.0, longitude=-71.0)
    )

    c1 = catalogo.resolver("PB01", network="C1")
    otra = catalogo.resolver("PB01", network="XX")

    assert c1 is not None and c1.network == "C1"
    assert otra is None


def test_catalogo_sin_red_acepta_respaldo_sin_red():
    catalogo = CatalogoEstaciones()
    catalogo.agregar(
        EstacionLista(network="", station="PB01", latitude=-21.0, longitude=-69.0)
    )

    estacion = catalogo.resolver("PB01", network="C1")

    assert estacion is not None
    assert estacion.network == ""
