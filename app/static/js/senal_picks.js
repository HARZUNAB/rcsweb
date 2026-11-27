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
  var botonRevision = document.getElementById(
    "btn-senal-revision-seleccionados"
  );
  var botonCorrida = document.getElementById("btn-senal-corrida");
  var botonReanalizarSinDatos = document.getElementById(
    "btn-senal-reanalizar-sin-datos"
  );
  var botonReanalizarTodo = document.getElementById(
    "btn-senal-reanalizar-todo"
  );
  var botonPausar = document.getElementById("btn-senal-pausar");
  var botonReanudar = document.getElementById("btn-senal-reanudar");
  var botonCancelar = document.getElementById("btn-senal-cancelar");
  var controles = document.getElementById("senal-run-controles");
  var runResumen = document.getElementById("senal-run-resumen");
  var seleccionarTodos = document.getElementById("senal-seleccionar-todos");
  var temporizador = null;
  var runTimer = null;
  var runActual = "";
  var intentos = 0;
  var enCurso = false;
  var MAX_INTENTOS = 600;

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") || "" : "";
  }

  function texto(mensaje, clase) {
    if (!estado) {
      return;
    }
    estado.className = "small mt-1 " + (clase || "text-secondary");
    estado.textContent = mensaje;
  }

  function progreso(porcentaje, mensaje, clase) {
    if (barra) {
      var valor = Math.max(0, Math.min(100, porcentaje));
      barra.style.width = valor + "%";
      barra.textContent = Math.round(valor) + "%";
    }
    if (mensaje) {
      texto(mensaje, clase || "text-secondary");
    }
  }

  function bloquearBotones(bloqueado) {
    document
      .querySelectorAll(".senal-picks-form button")
      .forEach(function (boton) {
        boton.disabled = bloqueado;
      });
    [botonCorrida, botonReanalizarSinDatos, botonReanalizarTodo].forEach(
      function (boton) {
        if (boton) {
          boton.disabled = bloqueado;
        }
      }
    );
    actualizarBotonSeleccionados();
  }

  function terminar() {
    if (temporizador) {
      window.clearInterval(temporizador);
      temporizador = null;
    }
    if (runTimer) {
      window.clearInterval(runTimer);
      runTimer = null;
    }
    enCurso = false;
    bloquearBotones(false);
  }

  function seleccionRevisionPendiente() {
    return Array.prototype.filter.call(
      document.querySelectorAll(".seleccion-revision:checked"),
      function (casilla) {
        return casilla.dataset.senalPendiente === "1" && casilla.dataset.evento;
      }
    );
  }

  function actualizarBotonRevision() {
    if (!botonRevision) {
      return;
    }
    var total = seleccionRevisionPendiente().length;
    botonRevision.disabled = enCurso || total === 0;
    botonRevision.textContent = total
      ? "Analizar señal (" + total + ")"
      : "Analizar señal";
  }

  function actualizarBotonSeleccionados() {
    if (botonSeleccionados) {
      var marcados = document.querySelectorAll(".senal-seleccion:checked");
      botonSeleccionados.disabled = enCurso || marcados.length === 0;
    }
    actualizarBotonRevision();
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

  /* ---------- Lote corto ---------- */

  function consultar(url) {
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (respuesta) {
        return respuesta.json();
      })
      .then(function (datos) {
        if (datos.estado === "ok") {
          var resultado = datos.resultado || {};
          progreso(100, resumen(resultado), "text-success");
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
    bloquearBotones(true);
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

  /* ---------- Corrida larga ---------- */

  function urlRun(plantilla, runId) {
    return (plantilla || "").replace("__RUN__", runId);
  }

  function resumenCorrida(datos) {
    var partes = [
      "Corrida: " + (datos.procesados || 0) + " de " + (datos.total || 0),
      (datos.con_senal || 0) + " con señal",
      (datos.sin_senal || 0) + " sin señal clara",
      (datos.sin_datos || 0) + " sin datos",
    ];
    if (datos.errores) {
      partes.push(datos.errores + " con error");
    }
    if (datos.pendientes) {
      partes.push(datos.pendientes + " pendientes");
    }
    return partes.join(" · ");
  }

  function mostrarControles(datos) {
    if (!controles) {
      return;
    }
    controles.classList.remove("d-none");
    if (botonPausar) {
      botonPausar.classList.toggle("d-none", !datos.puede_pausar);
    }
    if (botonReanudar) {
      botonReanudar.classList.toggle("d-none", !datos.puede_reanudar);
    }
    if (botonCancelar) {
      botonCancelar.classList.toggle("d-none", !datos.puede_cancelar);
    }
  }

  function ocultarControles() {
    if (controles) {
      controles.classList.add("d-none");
    }
  }

  function finalizarCorrida(datos) {
    if (runTimer) {
      window.clearInterval(runTimer);
      runTimer = null;
    }
    enCurso = false;
    bloquearBotones(false);
    ocultarControles();
    runActual = "";
    if (runResumen && datos) {
      runResumen.textContent = resumenCorrida(datos);
    }
  }

  function pintarCorrida(datos) {
    var total = datos.total || 0;
    var procesados = datos.procesados || 0;
    if (total > 0) {
      progreso(
        (procesados / total) * 100,
        "Corrida " + procesados + " de " + total +
          (datos.evento ? ": " + datos.evento : ""),
        "text-secondary"
      );
    }
    if (runResumen) {
      runResumen.textContent = resumenCorrida(datos);
    }
    mostrarControles(datos);
  }

  function consultarCorrida(runId) {
    fetch(urlRun(raiz.dataset.runEstadoUrl, runId), {
      headers: { Accept: "application/json" },
    })
      .then(function (respuesta) {
        return respuesta.json();
      })
      .then(function (datos) {
        pintarCorrida(datos);
        if (datos.estado === "done") {
          texto("Corrida completada.", "text-success");
          mostrarActualizar();
          finalizarCorrida(datos);
          return;
        }
        if (datos.estado === "cancelled") {
          texto("Corrida cancelada.", "text-secondary");
          finalizarCorrida(datos);
          return;
        }
        if (datos.estado === "error") {
          texto(datos.mensaje || "La corrida falló.", "text-danger");
          finalizarCorrida(datos);
          return;
        }
        if (datos.estado === "paused") {
          texto(datos.mensaje || "Corrida pausada.", "text-warning");
          if (runTimer) {
            window.clearInterval(runTimer);
            runTimer = null;
          }
          enCurso = true;
          bloquearBotones(true);
          mostrarControles(datos);
        }
      })
      .catch(function () {
        texto("No se pudo consultar el estado de la corrida.", "text-danger");
        finalizarCorrida(null);
      });
  }

  function iniciarCorrida(runId) {
    runActual = runId;
    enCurso = true;
    bloquearBotones(true);
    if (runTimer) {
      window.clearInterval(runTimer);
    }
    consultarCorrida(runId);
    runTimer = window.setInterval(function () {
      consultarCorrida(runId);
    }, 2000);
  }

  function crearCorrida(modo) {
    if (enCurso) {
      return;
    }
    enCurso = true;
    bloquearBotones(true);
    texto("Creando corrida…", "text-secondary");
    var parametros = new URLSearchParams(window.location.search);
    var datos = new FormData();
    datos.append("csrf_token", csrfToken());
    datos.append("fuente", raiz.dataset.fuente || "");
    datos.append("orden", parametros.get("orden") || "recomendado");
    datos.append("modo", modo || "pendientes");
    fetch(raiz.dataset.runUrl, {
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
            contenido.mensaje || "No se pudo crear la corrida.",
            "text-danger"
          );
          terminar();
          return;
        }
        if (!contenido.run_id) {
          texto("La corrida no devolvió identificador.", "text-danger");
          terminar();
          return;
        }
        iniciarCorrida(contenido.run_id);
      })
      .catch(function () {
        texto("No se pudo crear la corrida.", "text-danger");
        terminar();
      });
  }

  function accionCorrida(accion) {
    if (!runActual) {
      return;
    }
    var plantillas = {
      pausar: raiz.dataset.runPausarUrl,
      reanudar: raiz.dataset.runReanudarUrl,
      cancelar: raiz.dataset.runCancelarUrl,
    };
    var plantilla = plantillas[accion];
    if (!plantilla) {
      return;
    }
    var datos = new FormData();
    datos.append("csrf_token", csrfToken());
    fetch(urlRun(plantilla, runActual), {
      method: "POST",
      body: datos,
      headers: { Accept: "application/json" },
    })
      .then(function (respuesta) {
        return respuesta.json();
      })
      .then(function (contenido) {
        if (contenido.estado === "error") {
          texto(contenido.mensaje || "No se pudo completar la acción.", "text-danger");
          return;
        }
        if (accion === "reanudar") {
          iniciarCorrida(runActual);
        } else {
          consultarCorrida(runActual);
        }
      })
      .catch(function () {
        texto("No se pudo completar la acción.", "text-danger");
      });
  }

  /* ---------- Eventos de la interfaz ---------- */

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

  document.addEventListener("change", function (evento) {
    var casilla = evento.target;
    if (!casilla || !casilla.classList) {
      return;
    }
    if (
      casilla.classList.contains("seleccion-revision") ||
      casilla.id === "seleccionar-todos-revision"
    ) {
      actualizarBotonRevision();
    }
  });

  if (botonRevision) {
    botonRevision.addEventListener("click", function () {
      var marcados = seleccionRevisionPendiente();
      if (!marcados.length) {
        return;
      }
      var datos = new FormData();
      datos.append("csrf_token", csrfToken());
      datos.append("fuente", raiz.dataset.fuente || "");
      marcados.forEach(function (casilla) {
        datos.append("eventos", casilla.dataset.evento);
      });
      enviar(datos);
    });
  }

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
      var datos = new FormData();
      datos.append("csrf_token", csrfToken());
      datos.append("fuente", raiz.dataset.fuente || "");
      marcados.forEach(function (evento) {
        datos.append("eventos", evento);
      });
      enviar(datos);
    });
  }

  if (botonCorrida) {
    botonCorrida.addEventListener("click", function () {
      crearCorrida("pendientes");
    });
  }
  if (botonReanalizarSinDatos) {
    botonReanalizarSinDatos.addEventListener("click", function () {
      crearCorrida("sin_datos");
    });
  }
  if (botonReanalizarTodo) {
    botonReanalizarTodo.addEventListener("click", function () {
      var textoConfirmacion =
        "Se analizarán de nuevo todos los eventos con cobertura de picks. " +
        "Esto puede tardar mucho. ¿Continuar?";
      if (window.confirm(textoConfirmacion)) {
        crearCorrida("todo");
      }
    });
  }
  if (botonPausar) {
    botonPausar.addEventListener("click", function () {
      accionCorrida("pausar");
    });
  }
  if (botonReanudar) {
    botonReanudar.addEventListener("click", function () {
      accionCorrida("reanudar");
    });
  }
  if (botonCancelar) {
    botonCancelar.addEventListener("click", function () {
      accionCorrida("cancelar");
    });
  }

  actualizarBotonRevision();
  // La selección de la bandeja se restaura al ejecutarse su propio script.
  window.setTimeout(actualizarBotonRevision, 0);

  var corridaInicial = raiz.dataset.runId || "";
  if (corridaInicial) {
    iniciarCorrida(corridaInicial);
  } else {
    actualizarBotonSeleccionados();
  }
})();
