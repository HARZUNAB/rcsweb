"""Pruebas del glosario y la ayuda contextual."""

from __future__ import annotations

from app.services import glossary


def test_glosario_tiene_los_terminos_clave():
    claves = {
        "cruce_eventquery",
        "cobertura_debil",
        "indicio_debil",
        "residual_extremo",
        "patron_puntual",
        "patron_sin_fase",
        "peso",
    }
    for clave in claves:
        dato = glossary.definicion(clave)
        assert dato is not None, clave
        assert dato["titulo"]
        assert dato["texto"]

    grupos = glossary.grupos()
    incluidas = {
        termino["clave"]
        for grupo in grupos
        for termino in grupo["terminos"]
    }
    assert claves <= incluidas
    assert incluidas == set(glossary.TERMINOS)


def test_pagina_ayuda_requiere_sesion(client):
    respuesta = client.get("/ayuda")
    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_pagina_ayuda_lista_el_glosario(client, login):
    login()
    respuesta = client.get("/ayuda")
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert "Glosario de términos" in html
    assert "Cobertura débil" in html
    assert "Indicio débil" in html
    assert "Residual extremo" in html
    assert "Cruce Eventquery" in html
