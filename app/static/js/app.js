// Utilidades compartidas por todas las páginas.
(function () {
  "use strict";

  // Fechas dd/mm/aaaa con calendario local (Flatpickr).
  if (window.flatpickr) {
    if (window.flatpickr.l10ns && window.flatpickr.l10ns.es) {
      window.flatpickr.localize(window.flatpickr.l10ns.es);
    }
    window.flatpickr("[data-datepicker]", {
      dateFormat: "d/m/Y",
      allowInput: true,
      locale: "es",
    });
  }

  // Sincroniza checkboxes de fuentes con archivos y fuente principal.
  function sincronizarFuentes(form) {
    const radios = Array.from(
      form.querySelectorAll('input[name="primary_source"]')
    );
    if (!radios.length) {
      return;
    }
    [
      ["incluir_seiscomp", "seiscomp"],
      ["incluir_seisan", "seisan"],
    ].forEach(function (par) {
      const check = form.querySelector("#" + par[0]);
      if (!check) {
        return;
      }
      const archivo = form.querySelector("#" + par[1]);
      if (archivo) {
        archivo.disabled = !check.checked;
        archivo.required = check.checked;
      }
    });
    radios.forEach(function (radio) {
      const check = form.querySelector("#incluir_" + radio.value);
      radio.disabled = check ? !check.checked : false;
    });
    const habilitados = radios.filter(function (radio) {
      return !radio.disabled;
    });
    if (habilitados.length && !habilitados.some(function (radio) {
      return radio.checked;
    })) {
      habilitados[0].checked = true;
    }
  }

  function sincronizarTodos() {
    document.querySelectorAll("form").forEach(function (form) {
      if (form.querySelector('input[name="primary_source"]')) {
        sincronizarFuentes(form);
      }
    });
  }

  document.addEventListener("DOMContentLoaded", sincronizarTodos);
  document.body.addEventListener("htmx:afterSwap", sincronizarTodos);
  document.body.addEventListener("change", function (evento) {
    const objetivo = evento.target;
    if (objetivo.matches && objetivo.matches('input[id^="incluir_"]')) {
      sincronizarFuentes(objetivo.form);
    }
  });

  // Filas de tabla que abren un detalle (sin botón redundante).
  document.body.addEventListener("click", function (evento) {
    const objetivo = evento.target;
    if (!objetivo.closest || objetivo.closest("a, button")) {
      return;
    }
    const fila = objetivo.closest("tr[data-href]");
    if (fila) {
      window.location = fila.dataset.href;
    }
  });
  document.body.addEventListener("keydown", function (evento) {
    const objetivo = evento.target;
    if (!objetivo.closest) {
      return;
    }
    const fila = objetivo.closest("tr[data-href]");
    if (fila && (evento.key === "Enter" || evento.key === " ")) {
      evento.preventDefault();
      window.location = fila.dataset.href;
    }
  });

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

  // Modal de eliminación: completar período y acción según el botón.
  document.querySelectorAll("#modalEliminar").forEach(function (modal) {
    modal.addEventListener("show.bs.modal", function (evento) {
      const boton = evento.relatedTarget;
      if (!boton) {
        return;
      }
      const form = modal.querySelector("#form-eliminar");
      if (form && boton.dataset.jobUrl) {
        form.action = boton.dataset.jobUrl;
      }
      const periodo = modal.querySelector("#eliminar-periodo");
      if (periodo) {
        periodo.textContent = boton.dataset.jobPeriod || "";
      }
    });
  });

  // Mostrar/ocultar contraseñas: el botón declara el id del campo.
  document.addEventListener("click", function (evento) {
    const boton = evento.target.closest("[data-toggle-password]");
    if (!boton) {
      return;
    }
    const campo = document.getElementById(boton.dataset.togglePassword);
    if (!campo) {
      return;
    }
    const mostrar = campo.type === "password";
    campo.type = mostrar ? "text" : "password";
    boton.textContent = mostrar ? "Ocultar" : "Ver";
    boton.setAttribute("aria-pressed", String(mostrar));
  });

  // Miniaturas de los listados: apagadas por defecto, se piden al mostrarlas.
  function cargarMiniaturas(contenedor) {
    contenedor.querySelectorAll("img[data-src]").forEach(function (img) {
      if (!img.getAttribute("src")) {
        img.src = img.dataset.src;
      }
    });
  }

  function aplicarMiniaturas(tabla, activo) {
    tabla.classList.toggle("con-miniaturas", activo);
    if (activo) {
      cargarMiniaturas(tabla);
    }
    document.querySelectorAll("[data-toggle-miniaturas]").forEach(function (caja) {
      caja.checked = activo;
    });
  }

  const tablaMiniaturas = document.querySelector(".tabla-resultados");
  const interruptorMiniaturas = document.querySelector("[data-toggle-miniaturas]");
  if (tablaMiniaturas && interruptorMiniaturas) {
    let activo = false;
    try {
      activo = window.localStorage.getItem("rcs.miniaturas") === "1";
    } catch (error) {
      activo = false;
    }
    aplicarMiniaturas(tablaMiniaturas, activo);
    interruptorMiniaturas.addEventListener("change", function () {
      activo = interruptorMiniaturas.checked;
      try {
        window.localStorage.setItem("rcs.miniaturas", activo ? "1" : "0");
      } catch (error) {
        // Sin localStorage se mantiene solo durante esta página.
      }
      aplicarMiniaturas(tablaMiniaturas, activo);
    });
  }

  document.querySelectorAll("[data-toggle-miniaturas-fila]").forEach(function (boton) {
    boton.addEventListener("click", function () {
      const celda = boton.closest("td");
      const caja = celda && celda.querySelector("[data-miniaturas-fila]");
      if (!caja) {
        return;
      }
      const abrir = !caja.classList.contains("abierta");
      caja.classList.toggle("abierta", abrir);
      boton.textContent = abrir ? "Ocultar miniaturas" : "Ver miniaturas";
      boton.setAttribute("aria-expanded", String(abrir));
      if (abrir) {
        cargarMiniaturas(caja);
      }
    });
  });
})();
