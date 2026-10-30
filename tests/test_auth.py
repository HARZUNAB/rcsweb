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


def test_perfil_requiere_login(client):
    respuesta = client.get("/perfil")

    assert respuesta.status_code == 302
    assert "/login" in respuesta.headers["Location"]


def test_perfil_muestra_usuario_y_formulario(client, login):
    login()

    html = client.get("/perfil").get_data(as_text=True)

    assert "Mi perfil" in html
    assert "tester" in html
    assert "Cambiar contraseña" in html
    assert 'data-toggle-password="new_password"' in html


def test_cambio_contrasena_rechaza_la_actual(client, login):
    login()

    html = client.post(
        "/perfil",
        data={
            "current_password": "incorrecta",
            "new_password": "nueva-clave",
            "confirm_password": "nueva-clave",
        },
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "La contraseña actual no es correcta." in html
    client.post("/logout")
    assert client.post(
        "/login", data={"username": "tester", "password": "secret"}
    ).status_code == 302


def test_cambio_contrasena_ok(client, login):
    login()

    html = client.post(
        "/perfil",
        data={
            "current_password": "secret",
            "new_password": "nueva-clave",
            "confirm_password": "nueva-clave",
        },
        follow_redirects=True,
    ).get_data(as_text=True)

    assert "Contraseña actualizada." in html

    client.post("/logout")
    assert client.post(
        "/login", data={"username": "tester", "password": "nueva-clave"}
    ).status_code == 302

    client.post("/logout")
    assert client.post(
        "/login", data={"username": "tester", "password": "secret"}
    ).status_code == 200


def test_cambio_contrasena_valida_confirmacion(client, login):
    login()

    html = client.post(
        "/perfil",
        data={
            "current_password": "secret",
            "new_password": "nueva-clave",
            "confirm_password": "otra-clave",
        },
    ).get_data(as_text=True)

    assert "Las contraseñas nuevas no coinciden." in html


def test_navbar_tiene_menu_de_perfil(client, login):
    login()

    html = client.get("/").get_data(as_text=True)

    assert "Mi perfil" in html
    assert "Cambiar contraseña" in html
    assert "dropdown-item" in html
