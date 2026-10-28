"""Pruebas de autenticación y acceso."""

from __future__ import annotations


def test_dashboard_requiere_login(client):
    respuesta = client.get("/")

    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_login_correcto(client):
    respuesta = client.post(
        "/login",
        data={"username": "tester", "password": "secret"},
        follow_redirects=True,
    )

    assert respuesta.status_code == 200
    assert "Trabajos" in respuesta.get_data(as_text=True)


def test_login_incorrecto(client):
    respuesta = client.post(
        "/login",
        data={"username": "tester", "password": "mala"},
    )

    assert respuesta.status_code == 200
    assert "incorrectos" in respuesta.get_data(as_text=True)


def test_dashboard_prioriza_solicitud(client, login):
    login()

    html = client.get("/").get_data(as_text=True)

    assert "Solicitar catálogos" in html
    assert "Subir catálogos" in html
    assert html.index("Solicitar catálogos") < html.index("Subir catálogos")


def test_logout_cierra_sesion(client):
    client.post("/login", data={"username": "tester", "password": "secret"})

    respuesta = client.post("/logout")

    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_next_externo_se_ignora(client):
    respuesta = client.post(
        "/login?next=https://ejemplo.cl",
        data={"username": "tester", "password": "secret"},
    )

    assert respuesta.status_code == 302
    assert respuesta.headers["Location"].endswith("/")
