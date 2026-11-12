"""Pruebas de las etiquetas visibles y del formato numérico."""

from __future__ import annotations

from app.services import formatting


def test_etiqueta_patron_fuera_de_orden():
    assert (
        formatting.patron_texto("fuera_de_orden")
        == "Fase inconsistente con la distancia"
    )
    assert (
        formatting.patron_corto("fuera_de_orden")
        == "Inconsistente con la distancia"
    )


def test_etiqueta_patron_fuera_de_orden_debil():
    assert (
        formatting.patron_texto("fuera_de_orden_debil")
        == "Fase inconsistente con la distancia (baja influencia)"
    )
    assert (
        formatting.patron_corto("fuera_de_orden_debil")
        == "Inconsistente con la distancia (baja influencia)"
    )


def test_etiquetas_conservan_valores_desconocidos():
    assert formatting.patron_texto("otro_patron") == "otro_patron"
    assert formatting.tipo_indicio_texto("otro_tipo") == "otro_tipo"
    assert formatting.patron_texto("") == ""


def test_tipos_indicio_se_traducen_y_separan_por_coma():
    assert (
        formatting.tipos_indicio_texto("residual_alto, fuera_de_orden")
        == "Residual alto, Fase inconsistente con la distancia"
    )


def test_peso_04_usa_la_escala_de_influencia():
    assert formatting.peso_04(1.0) == 0.0
    assert formatting.peso_04(0.0) == 4.0
    assert formatting.peso_04_texto(0.3) == "3"
    assert formatting.peso_04_texto(3.6e-22) == "4"
