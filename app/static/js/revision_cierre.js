// Cierre de solicitudes: la URL solo se exige si el evento cambió y sigue publicado.
(function () {
  "use strict";

  document.querySelectorAll("[data-cambio-evento]").forEach(function (casilla) {
    const fila = casilla.closest("tr");
    const url = fila ? fila.querySelector('input[type="url"]') : null;
    const despublicado = fila
      ? fila.querySelector("[data-despublicado-evento]")
      : null;
    if (!url) {
      return;
    }

    function sincronizar() {
      const requiereUrl =
        casilla.checked && !(despublicado && despublicado.checked);
      url.disabled = !requiereUrl;
      url.required = requiereUrl;
      if (!requiereUrl) {
        url.value = "";
      }
    }

    casilla.addEventListener("change", sincronizar);
    if (despublicado) {
      despublicado.addEventListener("change", sincronizar);
    }
    sincronizar();
  });
})();
