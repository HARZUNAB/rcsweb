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
        "fase_fuerte",
        "residual_temporal",
        "parametros_actualizados",
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
    assert "Fase fuerte" in html
    assert "Residual temporal" in html
    assert "Parámetros actualizados" in html


def test_estados_de_estacion_estan_en_cobertura():
    grupos = {grupo["clave"]: grupo for grupo in glossary.grupos()}
    cobertura = {termino["clave"] for termino in grupos["cobertura"]["terminos"]}
    usuarios = {termino["clave"] for termino in grupos["usuarios"]["terminos"]}
    estados = {
        "estacion_observada",
        "estacion_sin_consultar",
        "estacion_sin_datos",
        "estacion_disponible_no_usada",
    }
    assert estados <= cobertura
    assert not estados & usuarios


def test_pagina_ayuda_vuelve_al_origen(client, login):
    login()
    respuesta = client.get(
        "/ayuda", query_string={"volver": "/admin/usuarios"}
    )
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert 'href="/admin/usuarios"' in html
    assert "Volver" in html
    assert "Volver a trabajos" not in html


def test_pagina_ayuda_rechaza_origen_inseguro(client, login):
    login()
    for valor in (
        "https://evil.example/x",
        "//evil.example/x",
        "/\\evil.example/x",
        "/ayuda?x=1",
    ):
        respuesta = client.get("/ayuda", query_string={"volver": valor})
        assert respuesta.status_code == 200
        html = respuesta.get_data(as_text=True)
        assert "evil.example" not in html
        assert "Volver a trabajos" in html


def test_panel_de_ayuda_conserva_la_pagina(client, login):
    login()
    respuesta = client.get("/admin/usuarios")
    assert respuesta.status_code == 200
    html = respuesta.get_data(as_text=True)
    assert 'href="/ayuda?volver=' in html
    assert "/ayuda?volver=/admin/usuarios" in html


def test_barra_de_ayuda_no_se_enlaza_a_si_misma(client, login):
    login()
    html = client.get("/ayuda").get_data(as_text=True)
    assert 'href="/ayuda?volver=' not in html
