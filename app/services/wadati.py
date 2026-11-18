"""Análisis Wadati de tiempos P/S por evento.

Estima Vp/Vs y la corrección de la hora de origen a partir de los pares P/S
de cada estación. Es un análisis complementario: no cambia la localización ni la
prioridad.
"""

from __future__ import annotations

import math

import numpy as np

MIN_PARES = 3
MIN_PARES_CONSISTENTE = 4
UMBRAL_R2 = 0.90
UMBRAL_VP_VS_MIN = 1.5
UMBRAL_VP_VS_MAX = 2.0
UMBRAL_DISPERSION = 0.5
UMBRAL_T0 = 2.0


def _numero(valor) -> float | None:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None


def _fase(registro: dict) -> str:
    return str(registro.get("fase") or "").strip().upper()


def _influyente(peso) -> float:
    """Peso canónico 0–1: 1.0 es máxima influencia y 0.0 se excluye."""
    valor = _numero(peso)
    if valor is None:
        return 1.0
    return max(0.0, min(1.0, valor))


def _usada(registro: dict) -> bool:
    return str(registro.get("usada") or "").strip().lower() in {
        "sí",
        "si",
        "yes",
        "true",
        "1",
    }


def _elegir(registros: list[dict]) -> dict | None:
    validos = [
        registro
        for registro in registros
        if _numero(registro.get("segundos")) is not None
    ]
    if not validos:
        return None
    usados = [registro for registro in validos if _usada(registro)]
    return min(
        usados or validos,
        key=lambda registro: _numero(registro.get("segundos")),
    )


def _vacio(mensaje: str, puntos: list[dict] | None = None) -> dict:
    return {
        "disponible": False,
        "n_pares": 0,
        "n_usadas": 0,
        "vp_vs": None,
        "t0": None,
        "r2": None,
        "dispersion": None,
        "pendiente": None,
        "intercepto": None,
        "calidad": "insuficiente",
        "mensaje": mensaje,
        "puntos": puntos or [],
    }


def analizar(arribos: list[dict] | None) -> dict:
    """Ajusta la recta de Wadati para los pares P/S de un evento."""
    grupos: dict[tuple[str, str], list[dict]] = {}
    for registro in arribos or []:
        red = str(registro.get("red") or "").strip()
        estacion = str(registro.get("estacion") or "").strip()
        if not estacion:
            continue
        grupos.setdefault((red, estacion), []).append(registro)

    puntos: list[dict] = []
    for (red, estacion), registros in grupos.items():
        p = _elegir(
            [registro for registro in registros if _fase(registro).startswith("P")]
        )
        s = _elegir(
            [registro for registro in registros if _fase(registro).startswith("S")]
        )
        if p is None or s is None:
            continue
        tp = _numero(p.get("segundos"))
        ts = _numero(s.get("segundos"))
        if tp is None or ts is None:
            continue
        diferencia = ts - tp
        if not math.isfinite(diferencia) or diferencia <= 0:
            continue
        peso = min(_influyente(p.get("peso")), _influyente(s.get("peso")))
        if peso <= 0:
            continue
        puntos.append(
            {
                "red": red,
                "estacion": estacion,
                "tp": tp,
                "ts_tp": diferencia,
                "peso": peso,
                "usada": _usada(p) and _usada(s),
            }
        )

    n_pares = len(puntos)
    n_usadas = sum(1 for punto in puntos if punto["usada"])
    if n_pares < MIN_PARES:
        return _vacio(
            "Insuficiente: se necesitan al menos "
            f"{MIN_PARES} estaciones con P y S.",
            puntos,
        )

    x = np.array([punto["tp"] for punto in puntos], dtype=float)
    y = np.array([punto["ts_tp"] for punto in puntos], dtype=float)
    pesos = np.array([punto["peso"] for punto in puntos], dtype=float)
    if not np.isfinite(pesos).all() or float(pesos.sum()) <= 0:
        pesos = np.ones_like(pesos)
    raiz = np.sqrt(pesos)
    matriz = np.column_stack([x, np.ones_like(x)])
    coeficientes, *_ = np.linalg.lstsq(
        matriz * raiz[:, None], y * raiz, rcond=None
    )
    pendiente = float(coeficientes[0])
    intercepto = float(coeficientes[1])
    ajuste = pendiente * x + intercepto
    residuos = y - ajuste
    suma_residuos = float(np.sum(residuos**2))
    suma_total = float(np.sum((y - float(np.mean(y))) ** 2))
    if suma_total <= 0:
        r2 = 1.0 if suma_residuos <= 0 else 0.0
    else:
        r2 = max(0.0, min(1.0, 1.0 - suma_residuos / suma_total))
    dispersion = float(math.sqrt(suma_residuos / n_pares))
    vp_vs = 1.0 + pendiente if math.isfinite(pendiente) else None
    ajuste_valido = (
        vp_vs is not None
        and math.isfinite(vp_vs)
        and vp_vs > 1.0
    )
    t0 = (
        -intercepto / pendiente
        if ajuste_valido and pendiente != 0
        else None
    )

    if n_pares < MIN_PARES_CONSISTENTE:
        calidad = "preliminar" if ajuste_valido else "dudoso"
    elif (
        ajuste_valido
        and UMBRAL_VP_VS_MIN <= vp_vs <= UMBRAL_VP_VS_MAX
        and r2 >= UMBRAL_R2
        and dispersion <= UMBRAL_DISPERSION
    ):
        calidad = "consistente"
    else:
        calidad = "dudoso"

    mensaje = (
        f"{n_pares} pares P/S · R² {r2:.2f} · "
        f"dispersión {dispersion:.2f} s"
    )
    if vp_vs is not None:
        mensaje += f" · Vp/Vs {vp_vs:.2f}"
    if not ajuste_valido:
        mensaje += (
            " · Ajuste no válido: Vp/Vs ≤ 1. Revise los picks P/S."
        )
    else:
        if t0 is not None and abs(t0) > UMBRAL_T0:
            mensaje += " · T0 fuera de ±2 s: revise la hora de origen."
        if calidad == "preliminar":
            mensaje += " · Ajuste preliminar: solo 3 pares."
        elif calidad == "dudoso":
            mensaje += " · Ajuste dudoso: revise picks, fases y pesos."

    return {
        "disponible": True,
        "n_pares": n_pares,
        "n_usadas": n_usadas,
        "vp_vs": vp_vs,
        "t0": t0,
        "r2": r2,
        "dispersion": dispersion,
        "pendiente": pendiente,
        "intercepto": intercepto,
        "calidad": calidad,
        "mensaje": mensaje,
        "puntos": puntos,
    }
