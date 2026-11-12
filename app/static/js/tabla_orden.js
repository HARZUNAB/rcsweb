// Ordenamiento de tablas de indicios en el navegador, sin recargar.

(function () {
  "use strict";

  function valorCelda(celda, tipo) {
    const dato = celda.dataset.sortValue;
    const texto = dato !== undefined ? dato : celda.textContent.trim();
    if (tipo === "number" || tipo === "order") {
      const limpio = String(texto)
        .replace(/[<>=+\s]/g, "")
        .replace(",", ".");
      const numero = parseFloat(limpio);
      return Number.isFinite(numero) ? numero : null;
    }
    return String(texto).toLocaleLowerCase("es");
  }

  function comparar(a, b, tipo) {
    if (a === null && b === null) return 0;
    if (a === null) return 1;
    if (b === null) return -1;
    if (tipo === "number" || tipo === "order") return a - b;
    return String(a).localeCompare(String(b), "es", {
      numeric: true,
      sensitivity: "base",
    });
  }

  function ordenar(tabla, encabezado, indice) {
    const tipo = encabezado.dataset.sortType || "text";
    const cuerpo = tabla.tBodies[0];
    if (!cuerpo) return;
    const filas = Array.from(cuerpo.rows).map((fila, posicion) => ({
      fila,
      posicion,
      valor: valorCelda(fila.cells[indice], tipo),
    }));
    const direccion =
      encabezado.dataset.sortDir === "asc" ? "desc" : "asc";
    filas.sort((a, b) => {
      const resultado = comparar(a.valor, b.valor, tipo);
      return (
        (direccion === "asc" ? resultado : -resultado) ||
        a.posicion - b.posicion
      );
    });
    for (const item of filas) {
      cuerpo.appendChild(item.fila);
    }
    for (const otro of tabla.querySelectorAll("th[data-sort-key]")) {
      otro.removeAttribute("data-sort-dir");
      otro.setAttribute("aria-sort", "none");
      const indicador = otro.querySelector(".orden-flecha");
      if (indicador) indicador.textContent = "";
    }
    encabezado.dataset.sortDir = direccion;
    encabezado.setAttribute(
      "aria-sort",
      direccion === "asc" ? "ascending" : "descending"
    );
    let indicador = encabezado.querySelector(".orden-flecha");
    if (!indicador) {
      indicador = document.createElement("span");
      indicador.className = "orden-flecha ms-1";
      encabezado.appendChild(indicador);
    }
    indicador.textContent = direccion === "asc" ? "↑" : "↓";
  }

  function iniciar() {
    document.querySelectorAll("table[data-sortable]").forEach((tabla) => {
      const encabezados = Array.from(
        tabla.querySelectorAll("thead th")
      );
      encabezados.forEach((encabezado, indice) => {
        if (!encabezado.dataset.sortKey) return;
        encabezado.style.cursor = "pointer";
        encabezado.setAttribute("tabindex", "0");
        if (!encabezado.hasAttribute("aria-sort")) {
          encabezado.setAttribute("aria-sort", "none");
        }
        const activar = () => ordenar(tabla, encabezado, indice);
        encabezado.addEventListener("click", activar);
        encabezado.addEventListener("keydown", (evento) => {
          if (evento.key === "Enter" || evento.key === " ") {
            evento.preventDefault();
            activar();
          }
        });
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
