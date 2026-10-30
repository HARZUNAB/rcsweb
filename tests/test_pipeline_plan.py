"""Pruebas del plan dinámico del pipeline."""

from __future__ import annotations

from types import SimpleNamespace

from app.services import pipeline


def _job() -> SimpleNamespace:
    return SimpleNamespace(inicio14="20261001000000", fin14="20261031235959")


def _claves(pasos) -> list[str]:
    return [paso.clave for paso in pasos]


def test_plan_solo_seiscomp():
    pasos = pipeline._construir_pasos(
        _job(), "eventquery_20261001000000_20261031235959.csv", ["seiscomp"]
    )

    assert _claves(pasos) == [
        "normalizar_eventquery",
        "convertir_seiscomp",
        "comparar_seiscomp",
        "detectar_repetidos",
    ]
    assert pasos[-1].post is not None


def test_plan_solo_seisan():
    pasos = pipeline._construir_pasos(
        _job(), "eventquery_20261001000000_20261031235959.csv", ["seisan"]
    )

    claves = _claves(pasos)
    assert "normalizar_seisan" in claves
    assert "armar_catalogo" in claves
    assert "comparar_seisan" in claves
    assert "cruzar_no_publicados" not in claves
    assert "revisar_excluidos" in claves
    assert pasos[-1].clave == "detectar_repetidos"


def test_plan_ambas_fuentes():
    pasos = pipeline._construir_pasos(
        _job(),
        "eventquery_20261001000000_20261031235959.csv",
        ["seiscomp", "seisan"],
    )

    claves = _claves(pasos)
    assert "comparar_seiscomp" in claves
    assert "comparar_seisan" in claves
    assert "cruzar_no_publicados" in claves
    assert "revisar_excluidos" in claves
    assert pasos[-1].post is None


def test_plan_sin_fuente_local_falla():
    try:
        pipeline._construir_pasos(_job(), "eventquery_20261001000000_20261031235959.csv", [])
    except pipeline.PipelineError:
        pass
    else:  # pragma: no cover
        raise AssertionError("debía rechazar un trabajo sin fuentes locales")


def test_renombrar_repetidos_de_seiscomp(tmp_path):
    informes = tmp_path / "informes"
    informes.mkdir()
    for sufijo in ("amplio", "estricto"):
        (informes / f"rep_seisan_{sufijo}.txt").write_text("x\n", encoding="utf-8")

    pipeline._renombrar_repetidos("seiscomp")(tmp_path)

    assert (informes / "rep_seiscomp_amplio.txt").is_file()
    assert (informes / "rep_seiscomp_estricto.txt").is_file()
    assert not (informes / "rep_seisan_amplio.txt").exists()


def test_progreso_re_captura_detalle():
    linea = "@@PROGRESO@@ 0.6600 Fases de seiscomp · 10.000 llegadas"

    coincidencia = pipeline.PROGRESO_RE.search(linea)

    assert coincidencia is not None
    assert coincidencia.group(1) == "0.6600"
    assert coincidencia.group(2) == "Fases de seiscomp · 10.000 llegadas"


def test_actualizar_progreso_muestra_detalle_sin_perder_porcentaje(app):
    from app.extensions import db
    from app.models import Job

    job = Job(id="job-progreso", status="running", progress=0,
              current_step="Exportando SeisComp (3/10)")
    db.session.add(job)
    db.session.commit()

    pipeline._actualizar_progreso(
        job.id, 2, 10, 0.5,
        detalle="Fases · 10.000 llegadas", titulo="Exportando SeisComp",
    )
    db.session.expire_all()
    job = db.session.get(Job, job.id)

    assert job.progress == 25
    assert job.current_step == "Exportando SeisComp · Fases · 10.000 llegadas"

    # El porcentaje puede redondear al mismo entero; el detalle igual cambia.
    pipeline._actualizar_progreso(
        job.id, 2, 10, 0.5001,
        detalle="Fases · 20.000 llegadas", titulo="Exportando SeisComp",
    )
    db.session.expire_all()
    job = db.session.get(Job, job.id)

    assert job.progress == 25
    assert job.current_step == "Exportando SeisComp · Fases · 20.000 llegadas"

    # Un cierre de paso sin título no pisa el detalle visible.
    pipeline._actualizar_progreso(job.id, 3, 10, 0.0)
    db.session.expire_all()
    job = db.session.get(Job, job.id)

    assert job.current_step == "Exportando SeisComp · Fases · 20.000 llegadas"
