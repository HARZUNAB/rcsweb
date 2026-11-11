"""Pruebas del enriquecimiento temporal de residuales."""

from __future__ import annotations

from pathlib import Path

from app.domain.catalogs import canonical
from app.services import residuals


def _evento(source_id: str, event_id: str, **cambios) -> dict:
    base = {
        "source_id": source_id,
        "event_id": event_id,
        "event_time": "2025-03-26 00:24:19",
        "latitude": -21.081,
        "longitude": -69.000,
    }
    base.update(cambios)
    return base


def _arribo(source_id: str, event_id: str, **cambios) -> dict:
    base = {
        "source_id": source_id,
        "event_id": event_id,
        "station": "PB01",
        "phase": "P",
        "pick_time": "2025-03-26 00:24:35.160000",
        "residual": None,
        "database": "Seisan_v9.1",
        "pick_id": "central-pick",
        "raw": {},
    }
    base.update(cambios)
    return base


def _escribir(workspace: Path, source_id: str, eventos, arribos) -> None:
    canonical.escribir_registros(
        canonical.ruta_canonica(workspace, source_id), eventos
    )
    canonical.escribir_registros(
        canonical.ruta_arribos(workspace, source_id), arribos
    )


def test_enriquece_residual_desde_fuente_local(tmp_path):
    workspace = tmp_path / "ws"
    _escribir(
        workspace,
        "central",
        [_evento("central", "central:000000")],
        [_arribo("central", "central:000000")],
    )
    _escribir(
        workspace,
        "seisan",
        [_evento("seisan", "seisan:000000")],
        [
            _arribo(
                "seisan",
                "seisan:000000",
                residual=-0.25,
                database="seisan",
                pick_id="seisan-pick",
            )
        ],
    )

    resultado = residuals.enriquecer_residuales(workspace)

    assert resultado == {"central": 1}
    arribo = canonical.leer_arribos(workspace, "central")[0]
    assert arribo["residual"] == -0.25
    assert arribo["raw"]["residual_fuente"] == "seisan"
    assert arribo["raw"]["residual_pick"] == "seisan-pick"
    assert arribo["raw"]["residual_dt"] == 0.0
    assert arribo["raw"]["residual_mismo_sistema"] is True


def test_no_enriquece_si_el_pick_no_coincide(tmp_path):
    workspace = tmp_path / "ws"
    _escribir(
        workspace,
        "central",
        [_evento("central", "central:000000")],
        [_arribo("central", "central:000000")],
    )
    _escribir(
        workspace,
        "seisan",
        [_evento("seisan", "seisan:000000")],
        [
            _arribo(
                "seisan",
                "seisan:000000",
                residual=-0.25,
                database="seisan",
                pick_time="2025-03-26 00:24:36.160000",
            )
        ],
    )

    assert residuals.enriquecer_residuales(workspace) == {}
    assert canonical.leer_arribos(workspace, "central")[0]["residual"] is None


def test_no_enriquece_si_el_evento_esta_lejos(tmp_path):
    workspace = tmp_path / "ws"
    _escribir(
        workspace,
        "central",
        [_evento("central", "central:000000")],
        [_arribo("central", "central:000000")],
    )
    _escribir(
        workspace,
        "seisan",
        [
            _evento(
                "seisan",
                "seisan:000000",
                latitude=-21.181,
                longitude=-69.000,
            )
        ],
        [
            _arribo(
                "seisan",
                "seisan:000000",
                residual=-0.25,
                database="seisan",
            )
        ],
    )

    assert residuals.enriquecer_residuales(workspace) == {}
    assert canonical.leer_arribos(workspace, "central")[0]["residual"] is None


def test_prioriza_la_fuente_del_mismo_sistema(tmp_path):
    workspace = tmp_path / "ws"
    _escribir(
        workspace,
        "central",
        [_evento("central", "central:000000")],
        [
            _arribo(
                "central",
                "central:000000",
                database="Seisan_v9.1",
            )
        ],
    )
    _escribir(
        workspace,
        "seisan",
        [_evento("seisan", "seisan:000000")],
        [
            _arribo(
                "seisan",
                "seisan:000000",
                residual=-0.25,
                database="seisan",
            )
        ],
    )
    _escribir(
        workspace,
        "seiscomp",
        [_evento("seiscomp", "seiscomp:000000")],
        [
            _arribo(
                "seiscomp",
                "seiscomp:000000",
                residual=-0.30,
                database="seiscomp",
            )
        ],
    )

    residuals.enriquecer_residuales(workspace)

    arribo = canonical.leer_arribos(workspace, "central")[0]
    assert arribo["residual"] == -0.25
    assert arribo["raw"]["residual_fuente"] == "seisan"
    assert arribo["raw"]["residual_mismo_sistema"] is True


def test_usa_otra_fuente_si_no_esta_la_del_mismo_sistema(tmp_path):
    workspace = tmp_path / "ws"
    _escribir(
        workspace,
        "central",
        [_evento("central", "central:000000")],
        [
            _arribo(
                "central",
                "central:000000",
                database="Seisan_v9.1",
            )
        ],
    )
    _escribir(
        workspace,
        "seiscomp",
        [_evento("seiscomp", "seiscomp:000000")],
        [
            _arribo(
                "seiscomp",
                "seiscomp:000000",
                residual=-0.30,
                database="seiscomp",
            )
        ],
    )

    residuals.enriquecer_residuales(workspace)

    arribo = canonical.leer_arribos(workspace, "central")[0]
    assert arribo["residual"] == -0.30
    assert arribo["raw"]["residual_fuente"] == "seiscomp"
    assert arribo["raw"]["residual_mismo_sistema"] is False


def test_hay_residuales_por_enriquecer(tmp_path):
    workspace = tmp_path / "ws"
    _escribir(
        workspace,
        "central",
        [_evento("central", "central:000000")],
        [_arribo("central", "central:000000")],
    )
    assert residuals.hay_residuales_por_enriquecer(workspace) is False

    _escribir(
        workspace,
        "seisan",
        [_evento("seisan", "seisan:000000")],
        [
            _arribo(
                "seisan",
                "seisan:000000",
                residual=-0.25,
                database="seisan",
            )
        ],
    )
    assert residuals.hay_residuales_por_enriquecer(workspace) is True
