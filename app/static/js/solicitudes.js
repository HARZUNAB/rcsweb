// Reloj de las solicitudes de catálogos.
(function () {
  "use strict";

  function formato(segundos) {
    const total = Math.max(0, Math.floor(segundos));
    const horas = Math.floor(total / 3600);
    const minutos = Math.floor((total % 3600) / 60);
    const seg = total % 60;
    return (
      String(horas).padStart(2, "0") + ":" +
      String(minutos).padStart(2, "0") + ":" +
      String(seg).padStart(2, "0")
    );
  }

  function actualizar() {
    document.querySelectorAll("[data-solicitud-inicio]").forEach(function (el) {
      const inicio = Date.parse(el.dataset.solicitudInicio || "");
      if (!Number.isFinite(inicio)) {
        return;
      }
      const finTexto = el.dataset.solicitudFin || "";
      const fin = finTexto ? Date.parse(finTexto) : null;
      const ahora = fin !== null && Number.isFinite(fin) ? fin : Date.now();
      el.textContent = formato((ahora - inicio) / 1000);
    });
  }

  actualizar();
  window.setInterval(actualizar, 1000);
  document.body.addEventListener("htmx:afterSwap", actualizar);
})();
