// Selección persistente y descarga de filas marcadas en las tablas.
// La clave de localStorage incluye trabajo + tabla + opción para no mezclar
// selecciones entre listados distintos.
(function () {
  "use strict";

  const tabla = document.querySelector(".tabla-resultados[data-seleccion-clave]");
  if (!tabla) {
    return;
  }

  const clave = "rcs-seleccion:" + tabla.dataset.seleccionClave;
  const urlSeleccionados = tabla.dataset.urlSeleccionados;
  const boton = document.querySelector("[data-descargar-seleccionados]");
  const limpiar = document.querySelector("[data-limpiar-seleccion]");
  const seleccionarTodos = tabla.querySelector("[data-seleccionar-todos]");
  const casillas = function () {
    return Array.from(tabla.querySelectorAll(".seleccion-evento"));
  };

  // Se guardan los índices originales ``_fila`` para conservar la selección
  // al cambiar de página, de filtro o de orden.
  let seleccion = new Set();
  try {
    const guardadas = JSON.parse(window.localStorage.getItem(clave) || "[]");
    if (Array.isArray(guardadas)) {
      seleccion = new Set(guardadas.map(String));
    }
  } catch (error) {
    seleccion = new Set();
  }

  function guardar() {
    try {
      window.localStorage.setItem(
        clave,
        JSON.stringify(Array.from(seleccion))
      );
    } catch (error) {
      // Sin almacenamiento disponible: la selección sigue en memoria.
    }
  }

  function actualizar() {
    if (boton) {
      const cantidad = seleccion.size;
      boton.disabled = cantidad === 0;
      boton.textContent = cantidad
        ? "Descargar seleccionados (" + cantidad + ")"
        : "Descargar seleccionados";
    }
    if (seleccionarTodos) {
      const visibles = casillas();
      const marcadas = visibles.filter(function (caja) {
        return caja.checked;
      }).length;
      seleccionarTodos.checked =
        visibles.length > 0 && marcadas === visibles.length;
      seleccionarTodos.indeterminate =
        marcadas > 0 && marcadas < visibles.length;
    }
  }

  function sincronizar() {
    casillas().forEach(function (caja) {
      caja.checked = seleccion.has(String(caja.value));
    });
    actualizar();
  }

  tabla.addEventListener("change", function (evento) {
    const caja = evento.target.closest(".seleccion-evento");
    if (!caja) {
      return;
    }
    const valor = String(caja.value);
    if (caja.checked) {
      seleccion.add(valor);
    } else {
      seleccion.delete(valor);
    }
    guardar();
    actualizar();
  });

  if (seleccionarTodos) {
    seleccionarTodos.addEventListener("change", function () {
      casillas().forEach(function (caja) {
        caja.checked = seleccionarTodos.checked;
        const valor = String(caja.value);
        if (seleccionarTodos.checked) {
          seleccion.add(valor);
        } else {
          seleccion.delete(valor);
        }
      });
      guardar();
      actualizar();
    });
  }

  if (limpiar) {
    limpiar.addEventListener("click", function () {
      seleccion.clear();
      guardar();
      sincronizar();
    });
  }

  if (boton) {
    boton.addEventListener("click", function () {
      if (!seleccion.size || !urlSeleccionados) {
        return;
      }
      // Descarga por POST con el token CSRF de la página.
      const formulario = document.createElement("form");
      formulario.method = "post";
      formulario.action = urlSeleccionados;
      formulario.style.display = "none";

      const meta = document.querySelector('meta[name="csrf-token"]');
      if (meta) {
        const csrf = document.createElement("input");
        csrf.type = "hidden";
        csrf.name = "csrf_token";
        csrf.value = meta.getAttribute("content") || "";
        formulario.appendChild(csrf);
      }
      seleccion.forEach(function (valor) {
        const campo = document.createElement("input");
        campo.type = "hidden";
        campo.name = "filas";
        campo.value = valor;
        formulario.appendChild(campo);
      });
      document.body.appendChild(formulario);
      formulario.submit();
    });
  }

  sincronizar();
})();
