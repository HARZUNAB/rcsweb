"""Pruebas de las métricas de correlación de estaciones sin arribos."""

from __future__ import annotations

import numpy as np
import pytest

from core import correlacion


def test_parse_stream_acepta_localizacion_vacia():
    assert correlacion.parse_stream("CX.HMBCX..HHZ") == (
        "CX",
        "HMBCX",
        "",
        "HHZ",
    )
    with pytest.raises(correlacion.ErrorCorrelacion):
        correlacion.parse_stream("CX.HMBCX")


def test_media_movil_y_sta_lta_detectan_un_pulso():
    fs = 100.0
    rng = np.random.default_rng(7)
    datos = rng.normal(0, 0.01, int(20 * fs))
    datos[int(12 * fs) : int(13 * fs)] += 1.0
    ratio = correlacion.sta_lta_ratio(datos, fs, 0.5, 10.0)
    maximo, instante = correlacion.max_sta_lta(
        ratio,
        inicio=0.0,
        fs=fs,
        desde=11.0,
        hasta=14.0,
    )
    assert maximo is not None and maximo > 3.0
    assert instante is not None and 12.0 <= instante <= 13.0


def test_correlacion_max_encuentra_el_lag():
    fs = 100.0
    rng = np.random.default_rng(11)
    n_ref = 400
    max_lag = 2.0
    muestras_lag = int(max_lag * fs)
    t = np.arange(n_ref) / fs
    ref = np.sin(2 * np.pi * 6.0 * t) * np.hanning(n_ref)
    cand = rng.normal(0, 0.02, n_ref + 2 * muestras_lag)
    desplazamiento = int(0.4 * fs)
    inicio = muestras_lag + desplazamiento
    cand[inicio : inicio + n_ref] += ref * 2.0
    cc, lag = correlacion.correlacion_max(ref, cand, fs, max_lag)
    assert cc is not None and cc > 0.99
    assert lag is not None and abs(lag - 0.4) < 0.02


def test_clasificar_distingue_los_estados():
    podria, _ = correlacion.clasificar(
        cc_max=0.8,
        lag_s=0.2,
        sta_lta=4.0,
        cc_min=0.5,
        sta_lta_min=3.0,
        lag_max_s=5.0,
    )
    senal, _ = correlacion.clasificar(
        cc_max=0.2,
        lag_s=0.2,
        sta_lta=4.0,
        cc_min=0.5,
        sta_lta_min=3.0,
        lag_max_s=5.0,
    )
    debil, _ = correlacion.clasificar(
        cc_max=0.8,
        lag_s=0.2,
        sta_lta=1.0,
        cc_min=0.5,
        sta_lta_min=3.0,
        lag_max_s=5.0,
    )
    sin_senal, _ = correlacion.clasificar(
        cc_max=0.2,
        lag_s=0.2,
        sta_lta=1.0,
        cc_min=0.5,
        sta_lta_min=3.0,
        lag_max_s=5.0,
    )
    assert podria == correlacion.CLASIFICACION_PODRIA
    assert senal == correlacion.CLASIFICACION_SENAL
    assert debil == correlacion.CLASIFICACION_DEBIL
    assert sin_senal == correlacion.CLASIFICACION_SIN_SENAL


def test_correlacion_max_rechaza_ventana_corta():
    cc, lag = correlacion.correlacion_max(
        np.ones(100),
        np.ones(50),
        fs=100.0,
        max_lag_s=2.0,
    )
    assert cc is None
    assert lag is None
