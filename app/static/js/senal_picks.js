/* Análisis bajo demanda de la señal de estaciones sin aportar. */
(function () {
  "use strict";

  var raiz = document.getElementById("senal-picks");
  if (!raiz) {
    return;
  }

  var barra = document.getElementById("senal-picks-barra");
  var estado = document.getElementById("senal-picks-estado");
  var botonSeleccionados = document.getElementById("btn-senal-seleccionados");
  var seleccionarTodos = document.getElementById("senal-seleccionar-todos");
  var temporizador = null;
  var intentos = 0;
  var enCurso = false;
  var MAX_INTENTOS = 600;

  function texto(mensaje, clase) {
    if (!estado) {
      return;
    }
    estado.className = "small mt-1 " + (clase || "text-secondary");
    estado.textContent = mensaje;
  }

  function progreso(porcentaje, mensaje) {
    if (barra) {
      var valor = Math.max(0, Math.min(100, porcentaje));
      barra.style.width = valor + "%";
      barra.textContent = Math.round(valor) + "%";
    }
    if (mensaje) {
      texto(mensaje, "text-secondary");
    }
  }

  function terminar() {
    if (temporizador) {
      window.clearInterval(temporizador);
      temporizador = null;
    }
    enCurso = false;
    document
      .querySelectorAll(".senal-picks-form button")
      .forEach(function (boton) {
        boton.disabled = false;
      });
    actualizarBotonSeleccionados();
  }

  function actualizarBotonSeleccionados() {
    if (!botonSeleccionados) {
      return;
    }
    var marcados = document.querySelectorAll(".senal-seleccion:checked");
    botonSeleccionados.disabled = enCurso || marcados.length === 0;
  }

  function resumen(resultado) {
    var eventos = resultado.eventos || 0;
    var conSenal = resultado.con_senal || 0;
    var sinSenal = resultado.sin_senal || 0;
    var sinDatos = resultado.sin_datos || 0;
    var errores = resultado.errores || 0;
    var partes = [
      "Listo: " + eventos + " eventos",
      conSenal + " con señal",
      sinSenal + " sin señal clara",
      sinDatos + " sin datos",
    ];
    if (errores) {
      partes.push(errores + " con error");
    }
    return partes.join(" · ");
  }

  function mostrarActualizar() {
    if (!estado) {
      return;
    }
    estado.className = "small mt-1 text-success";
    estado.textContent = estado.textContent.replace(/\s*\[Actualizar lista\]$/, "");
    var enlace = document.createElement("a");
    enlace.href = window.location.href;
    enlace.className = "ms-2";
    enlace.textContent = "[Actualizar lista]";
    estado.appendChild(enlace);
  }

  function consultar(url) {
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (respuesta) {
        return respuesta.json();
      })
      .then(function (datos) {
        if (datos.estado === "ok") {
          var resultado = datos.resultado || {};
          progreso(100, resumen(resultado));
          mostrarActualizar();
          terminar();
          return;
        }
        if (datos.estado === "error") {
          texto(datos.mensaje || "No se pudo analizar la señal.", "text-danger");
          terminar();
          return;
        }
        intentos += 1;
        if (intentos > MAX_INTENTOS) {
          texto(
            "El análisis sigue en curso. Recargue la página más tarde.",
            "text-warning"
          );
          terminar();
          return;
        }
        var total = datos.total || 0;
        var procesados = datos.procesados || 0;
        if (total > 0) {
          progreso(
            (procesados / total) * 100,
            "Procesando " + procesados + " de " + total +
              (datos.evento ? ": " + datos.evento : "")
          );
        } else {
          texto(datos.fase || "Analizando señal…", "text-secondary");
        }
      })
      .catch(function () {
        texto("No se pudo consultar el estado del análisis.", "text-danger");
        terminar();
      });
  }

  function iniciar(url) {
    intentos = 0;
    progreso(0, "Analizando señal…");
    consultar(url);
    temporizador = window.setInterval(function () {
      consultar(url);
    }, 1500);
  }

  function enviar(datos) {
    if (enCurso) {
      return;
    }
    enCurso = true;
    document
      .querySelectorAll(".senal-picks-form button")
      .forEach(function (boton) {
        boton.disabled = true;
      });
    texto("Encolando el análisis…", "text-secondary");
    fetch(raiz.dataset.url, {
      method: "POST",
      body: datos,
      headers: { Accept: "application/json" },
    })
      .then(function (respuesta) {
        return respuesta.json().then(function (contenido) {
          return { ok: respuesta.ok, datos: contenido };
        });
      })
      .then(function (resultado) {
        var contenido = resultado.datos || {};
        if (!resultado.ok || contenido.estado === "error") {
          texto(
            contenido.mensaje || "No se pudo encolar el análisis.",
            "text-danger"
          );
          terminar();
          return;
        }
        if (!contenido.task_id) {
          texto("El análisis no devolvió una tarea.", "text-danger");
          terminar();
          return;
        }
        var plantilla = raiz.dataset.estadoUrl || "";
        iniciar(plantilla.replace("__TASK__", contenido.task_id));
      })
      .catch(function () {
        texto("No se pudo encolar el análisis.", "text-danger");
        terminar();
      });
  }

  document.querySelectorAll(".senal-picks-form").forEach(function (formulario) {
    formulario.addEventListener("submit", function (evento) {
      evento.preventDefault();
      enviar(new FormData(formulario));
    });
  });

  if (seleccionarTodos) {
    seleccionarTodos.addEventListener("change", function () {
      document.querySelectorAll(".senal-seleccion").forEach(function (casilla) {
        casilla.checked = seleccionarTodos.checked;
      });
      actualizarBotonSeleccionados();
    });
  }

  document.querySelectorAll(".senal-seleccion").forEach(function (casilla) {
    casilla.addEventListener("change", actualizarBotonSeleccionados);
  });

  if (botonSeleccionados) {
    botonSeleccionados.addEventListener("click", function () {
      var marcados = Array.prototype.map.call(
        document.querySelectorAll(".senal-seleccion:checked"),
        function (casilla) {
          return casilla.value;
        }
      );
      if (!marcados.length) {
        return;
      }
      var meta = document.querySelector('meta[name="csrf-token"]');
      var datos = new FormData();
      datos.append(
        "csrf_token",
        meta ? meta.getAttribute("content") || "" : ""
      );
      datos.append("fuente", raiz.dataset.fuente || "");
      marcados.forEach(function (evento) {
        datos.append("eventos", evento);
      });
      enviar(datos);
    });
  }

  actualizarBotonSeleccionados();
})();
