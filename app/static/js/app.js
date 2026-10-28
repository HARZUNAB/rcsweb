// Utilidades compartidas por todas las páginas.
(function () {
  "use strict";

  // HTMX: enviar el token CSRF en cada petición no-GET.
  document.body.addEventListener("htmx:configRequest", function (evento) {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) {
      evento.detail.headers["X-CSRFToken"] = meta.getAttribute("content");
    }
  });

  // Cerrar automáticamente los avisos después de unos segundos.
  document.querySelectorAll(".alert-dismissible").forEach(function (alerta) {
    window.setTimeout(function () {
      if (window.bootstrap && window.bootstrap.Alert) {
        window.bootstrap.Alert.getOrCreateInstance(alerta).close();
      }
    }, 6000);
  });
})();
