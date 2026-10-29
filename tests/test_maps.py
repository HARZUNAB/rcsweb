"""Pruebas del selector de modo de mapa."""

from __future__ import annotations

from app.services import maps


def test_modo_mapa_respeta_override(monkeypatch):
    monkeypatch.setenv("MAPS_MODE", "offline")
    assert maps.modo_mapa() == "offline"
    assert maps.modo_mapa("online") == "online"


def test_modo_mapa_auto_usa_conectividad(monkeypatch):
    monkeypatch.delenv("MAPS_MODE", raising=False)
    monkeypatch.setattr(maps, "internet_disponible", lambda: False)
    assert maps.modo_mapa() == "offline"
    monkeypatch.setattr(maps, "internet_disponible", lambda: True)
    assert maps.modo_mapa() == "online"
