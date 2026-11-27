/* Copias y adjunto en los formularios de notificación de revisión. */
(function () {
  "use strict";

  document.querySelectorAll("[data-notificacion-envio]").forEach(function (raiz) {
    var formulario = raiz.closest("form");
    if (!formulario) {
      return;
    }
    var toggle = raiz.querySelector("[data-toggle-copias]");
    var campos = raiz.querySelector("[data-cc-campos]");
    var selectores = Array.prototype.slice.call(
      raiz.querySelectorAll("[data-cc-select]")
    );
    var resumen = raiz.querySelector("[data-cc-resumen]");
    var adjuntar = formulario.querySelector('input[name="adjuntar_pdf"]');
    var radios = formulario.querySelectorAll('input[name="notificar"]');
    var modo = (raiz.dataset.modo || "correo").toLowerCase();
    var obligatorias = raiz.dataset.copiasObligatorias === "1";

    function notificar() {
      var marcado = formulario.querySelector(
        'input[name="notificar"]:checked'
      );
      return marcado ? marcado.value === "1" : false;
    }

    function agregandoCopias() {
      if (obligatorias) {
        return true;
      }
      return toggle ? toggle.checked : false;
    }

    function actualizar() {
      var agregar = agregandoCopias();
      if (campos) {
        campos.classList.toggle("d-none", !agregar);
      }

      var correos = [];
      var vistos = {};
      if (agregar) {
        selectores.forEach(function (selector) {
          var opcion = selector.options[selector.selectedIndex];
          var correo = opcion ? (opcion.dataset.email || "").trim() : "";
          var clave = correo.toLowerCase();
          if (!correo || vistos[clave]) {
            return;
          }
          vistos[clave] = true;
          correos.push(correo);
        });
      }
      if (resumen) {
        resumen.textContent = correos.length
          ? "Se enviará copia a: " + correos.join(", ")
          : "El correo irá solo al analista asignado.";
      }

      if (adjuntar) {
        var obligatorio = modo === "correo" && notificar();
        adjuntar.required = obligatorio;
        adjuntar.setAttribute(
          "aria-required",
          obligatorio ? "true" : "false"
        );
      }

      if (selectores.length) {
        var disponibles = Math.max(0, selectores[0].options.length - 1);
        var requeridas =
          obligatorias && agregar && notificar()
            ? Math.min(2, disponibles)
            : 0;
        selectores.forEach(function (selector, indice) {
          selector.required = indice < requeridas;
        });
      }
    }

    if (toggle && obligatorias) {
      toggle.checked = true;
      toggle.disabled = true;
    }
    if (toggle) {
      toggle.addEventListener("change", actualizar);
    }
    selectores.forEach(function (selector) {
      selector.addEventListener("change", actualizar);
    });
    radios.forEach(function (radio) {
      radio.addEventListener("change", actualizar);
    });
    actualizar();
  });
})();
