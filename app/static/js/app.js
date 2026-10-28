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

  // Mantener el log del trabajo al final, también tras cada refresco de HTMX.
  function bajarLog() {
    document.querySelectorAll(".log-panel").forEach(function (panel) {
      panel.scrollTop = panel.scrollHeight;
    });
  }
  document.addEventListener("DOMContentLoaded", bajarLog);
  document.body.addEventListener("htmx:afterSwap", bajarLog);

  // No enviar filtros vacíos: mantiene la URL corta y legible.
  document.querySelectorAll('form#tabla-filtros').forEach(function (form) {
    form.addEventListener("submit", function () {
      form.querySelectorAll('input[name^="f_"]').forEach(function (input) {
        if (!input.value.trim()) {
          input.disabled = true;
        }
      });
    });
  });
})();
