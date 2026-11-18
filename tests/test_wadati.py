"""Pruebas del análisis Wadati de tiempos P/S."""

from __future__ import annotations

from app.services import wadati


def _arribos(pares, *, peso=1.0, usada="Sí") -> list[dict]:
    datos = []
    for indice, (tp, ts) in enumerate(pares, start=1):
        estacion = f"E{indice}"
        datos.append(
            {
                "red": "C1",
                "estacion": estacion,
                "fase": "P",
                "segundos": tp,
                "peso": peso,
                "usada": usada,
            }
        )
        datos.append(
            {
                "red": "C1",
                "estacion": estacion,
                "fase": "S",
                "segundos": ts,
                "peso": peso,
                "usada": usada,
            }
        )
    return datos


def test_wadati_ajuste_consistente():
    pares = [(5.0, 8.75), (10.0, 17.5), (15.0, 26.25), (20.0, 35.0)]
    resultado = wadati.analizar(_arribos(pares))

    assert resultado["disponible"] is True
    assert resultado["n_pares"] == 4
    assert abs(resultado["vp_vs"] - 1.75) < 1e-6
    assert abs(resultado["t0"]) < 1e-6
    assert abs(resultado["r2"] - 1.0) < 1e-6
    assert abs(resultado["dispersion"]) < 1e-6
    assert resultado["calidad"] == "consistente"


def test_wadati_estima_t0():
    pares = [(6.0, 9.75), (11.0, 18.5), (16.0, 27.25), (21.0, 36.0)]
    resultado = wadati.analizar(_arribos(pares))

    assert abs(resultado["vp_vs"] - 1.75) < 1e-6
    assert abs(resultado["t0"] - 1.0) < 1e-6
    assert resultado["calidad"] == "consistente"
    assert "T0 fuera de ±2 s" not in resultado["mensaje"]


def test_wadati_advierte_t0_grande():
    pares = [(8.0, 11.75), (13.0, 20.5), (18.0, 29.25), (23.0, 38.0)]
    resultado = wadati.analizar(_arribos(pares))

    assert abs(resultado["t0"] - 3.0) < 1e-6
    assert "T0 fuera de ±2 s" in resultado["mensaje"]


def test_wadati_vp_vs_invalido_sin_t0():
    pares = [(5.0, 8.0), (10.0, 12.5), (15.0, 17.0), (20.0, 21.5)]
    resultado = wadati.analizar(_arribos(pares))

    assert resultado["n_pares"] == 4
    assert resultado["vp_vs"] < 1.0
    assert resultado["t0"] is None
    assert resultado["calidad"] == "dudoso"
    assert "Ajuste no válido" in resultado["mensaje"]


def test_wadati_tres_pares_es_preliminar():
    pares = [(5.0, 8.75), (10.0, 17.5), (15.0, 26.25)]
    resultado = wadati.analizar(_arribos(pares))

    assert resultado["n_pares"] == 3
    assert resultado["calidad"] == "preliminar"
    assert "preliminar" in resultado["mensaje"]


def test_wadati_menos_de_tres_pares_es_insuficiente():
    pares = [(5.0, 8.75), (10.0, 17.5)]
    resultado = wadati.analizar(_arribos(pares))

    assert resultado["disponible"] is False
    assert resultado["n_pares"] == 0
    assert resultado["calidad"] == "insuficiente"
    assert "al menos 3" in resultado["mensaje"]


def test_wadati_sin_s_no_arma_pares():
    datos = [
        {
            "red": "C1",
            "estacion": "E1",
            "fase": "P",
            "segundos": 5.0,
            "peso": 0.0,
            "usada": "Sí",
        }
    ]
    resultado = wadati.analizar(datos)
    assert resultado["calidad"] == "insuficiente"
    assert resultado["n_pares"] == 0


def test_wadati_outlier_es_dudoso():
    pares = [(5.0, 8.75), (10.0, 17.5), (15.0, 26.25), (20.0, 40.0)]
    resultado = wadati.analizar(_arribos(pares))

    assert resultado["n_pares"] == 4
    assert resultado["calidad"] == "dudoso"


def test_wadati_expone_residuo_por_punto():
    pares = [(5.0, 8.75), (10.0, 17.5), (15.0, 26.25), (20.0, 40.0)]
    resultado = wadati.analizar(_arribos(pares))

    residuos = [punto["residuo"] for punto in resultado["puntos"]]
    assert len(residuos) == 4
    assert all(isinstance(valor, float) for valor in residuos)
    assert abs(residuos[0]) < abs(residuos[-1])


def test_wadati_excluye_peso_sin_influencia():
    datos = _arribos(
        [(5.0, 8.75), (10.0, 17.5), (15.0, 26.25), (20.0, 35.0)]
    )
    for registro in datos:
        if registro["estacion"] == "E4":
            registro["peso"] = 0.0
    resultado = wadati.analizar(datos)

    assert resultado["n_pares"] == 3
    assert resultado["calidad"] == "preliminar"
