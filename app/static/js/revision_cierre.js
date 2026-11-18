// Cierre de solicitudes: habilita la URL solo cuando el evento cambió.
(function () {
  "use strict";

  document.querySelectorAll("[data-cambio-evento]").forEach(function (casilla) {
    const fila = casilla.closest("tr");
    const url = fila ? fila.querySelector('input[type="url"]') : null;
    if (!url) {
      return;
    }

    function sincronizar() {
      url.disabled = !casilla.checked;
      url.required = casilla.checked;
      if (!casilla.checked) {
        url.value = "";
      }
    }

    casilla.addEventListener("change", sincronizar);
    sincronizar();
  });
})();
