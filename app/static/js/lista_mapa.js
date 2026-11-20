// Sincroniza la selección entre el mapa interactivo y su listado de eventos.
// El mapa emite rcs:punto-seleccionado / rcs:punto-deseleccionado; el listado
// emite rcs:seleccionar-punto. Cualquier tabla con data-lista-mapa y filas con
// data-clave participa sin código adicional por página.
(function () {
  "use strict";

  const listas = document.querySelectorAll("[data-lista-mapa]");
  if (!listas.length) {
    return;
  }

  function filas() {
    return Array.from(
      document.querySelectorAll("[data-lista-mapa] [data-clave]")
    );
  }

  function marcar(clave) {
    const objetivo = clave === undefined || clave === null
      ? ""
      : String(clave);
    const todas = filas();
    todas.forEach(function (fila) {
      fila.classList.toggle(
        "table-active",
        Boolean(objetivo) && fila.dataset.clave === objetivo
      );
    });
    if (!objetivo) {
      return;
    }
    const fila = todas.find(function (item) {
      return item.dataset.clave === objetivo;
    });
    if (fila) {
      fila.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  document.addEventListener("rcs:punto-seleccionado", function (evento) {
    marcar(evento.detail && evento.detail.clave);
  });
  document.addEventListener("rcs:punto-deseleccionado", function () {
    marcar(null);
  });

  listas.forEach(function (lista) {
    lista.addEventListener("click", function (evento) {
      if (
        evento.target.closest(
          "a, button, input, select, textarea, label, form"
        )
      ) {
        return;
      }
      const fila = evento.target.closest("[data-clave]");
      if (!fila || !lista.contains(fila)) {
        return;
      }
      // Si la fila ya navega a un detalle, se respeta ese comportamiento.
      if (fila.hasAttribute("data-href")) {
        return;
      }
      const clave = fila.getAttribute("data-clave");
      if (!clave) {
        return;
      }
      document.dispatchEvent(
        new CustomEvent("rcs:seleccionar-punto", {
          detail: { clave: clave },
        })
      );
    });
  });
})();
