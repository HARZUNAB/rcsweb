"""Pruebas de la bandeja temporal de revisión."""

from __future__ import annotations

import json

from app.services import review_drafts


class FakeRedis:
    def __init__(self):
        self.datos = {}

    def get(self, clave):
        return self.datos.get(clave)

    def set(self, clave, valor, ex=None):
        self.datos[clave] = valor

    def delete(self, clave):
        self.datos.pop(clave, None)

    def expire(self, clave, ttl):
        return clave in self.datos

    def ttl(self, clave):
        return 43200


def _fake(app, monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(review_drafts, "_redis", lambda: fake)
    return fake


def test_bandeja_agrega_reemplaza_y_quita(app, monkeypatch):
    _fake(app, monkeypatch)
    with app.app_context():
        review_drafts.agregar(
            "job",
            1,
            {
                "fila": {"fuente": "seiscomp", "evento": "seiscomp:000001"},
                "assigned_to_id": 2,
                "kind": "solucion",
            },
        )
        review_drafts.agregar(
            "job",
            1,
            {
                "fila": {"fuente": "seiscomp", "evento": "seiscomp:000001"},
                "assigned_to_id": 2,
                "kind": "publicacion",
            },
        )
        items = review_drafts.listar("job", 1)
        assert len(items) == 1
        assert items[0]["kind"] == "publicacion"

        review_drafts.agregar(
            "job",
            1,
            {
                "fila": {"fuente": "seiscomp", "evento": "seiscomp:000002"},
                "assigned_to_id": 3,
                "kind": "solucion",
            },
        )
        assert len(review_drafts.listar("job", 1)) == 2

        review_drafts.quitar("job", 1, "seiscomp", "seiscomp:000001")
        items = review_drafts.listar("job", 1)
        assert [item["fila"]["evento"] for item in items] == [
            "seiscomp:000002"
        ]

        review_drafts.vaciar("job", 1)
        assert review_drafts.listar("job", 1) == []


def test_bandeja_guarda_ttl(app, monkeypatch):
    fake = _fake(app, monkeypatch)
    with app.app_context():
        review_drafts.agregar(
            "job",
            1,
            {
                "fila": {"fuente": "seiscomp", "evento": "seiscomp:000001"},
                "assigned_to_id": 2,
                "kind": "solucion",
            },
        )
    clave = review_drafts.clave("job", 1)
    assert json.loads(fake.datos[clave])[0]["fila"]["evento"] == (
        "seiscomp:000001"
    )


def test_bandeja_marca_enviando_y_restaura(app, monkeypatch):
    _fake(app, monkeypatch)
    with app.app_context():
        review_drafts.agregar(
            "job",
            1,
            {
                "fila": {"fuente": "seiscomp", "evento": "seiscomp:000001"},
                "assigned_to_id": 2,
                "kind": "solucion",
            },
        )
        review_drafts.marcar_enviando(
            "job",
            1,
            {("seiscomp", "seiscomp:000001")},
            "report-1",
        )
        items = review_drafts.listar("job", 1)
        assert items[0]["estado"] == "enviando"
        assert items[0]["report_id"] == "report-1"

        review_drafts.restaurar("job", 1, "report-1")
        items = review_drafts.listar("job", 1)
        assert items[0]["estado"] == "pendiente"
        assert "report_id" not in items[0]

        review_drafts.marcar_enviando(
            "job",
            1,
            {("seiscomp", "seiscomp:000001")},
            "report-2",
        )
        review_drafts.quitar_enviados("job", 1, "report-2")
        assert review_drafts.listar("job", 1) == []
