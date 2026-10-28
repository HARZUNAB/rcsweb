"""Pruebas del endpoint de salud."""

from __future__ import annotations


def test_health_responde_ok(client):
    respuesta = client.get("/health")

    assert respuesta.status_code == 200
    datos = respuesta.get_json()
    assert datos["status"] == "ok"
    assert datos["database"] == "ok"
    assert "version" in datos
    assert "workspace_escribible" in datos
