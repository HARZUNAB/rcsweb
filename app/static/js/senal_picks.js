/* Análisis bajo demanda de la señal de estaciones sin aportar. */
(function () {
  "use strict";

  var raiz = document.getElementById("senal-picks");
  if (!raiz) {
    return;
  }

  var formulario = raiz.querySelector("form");
  var boton = document.getElementById("btn-analizar-senal");
  var estado = document.getElementById("senal-picks-estado");
  var temporizador = null;
  var intentos = 0;
  var MAX_INTENTOS = 300;

  function texto(mensaje, clase) {
    if (!estado) {
      return;
    }
    estado.className = "small " + (clase || "text-secondary");
    estado.textContent = mensaje;
  }

  function terminar() {
    if (temporizador) {
      window.clearInterval(temporizador);
      temporizador = null;
    }
    if (boton) {
      boton.disabled = false;
    }
  }

  function consultar(url) {
    fetch(url, { headers: { Accept: "application/json" } })
      .then(function (respuesta) {
        return respuesta.json();
      })
      .then(function (datos) {
        if (datos.estado === "ok") {
          var resultado = datos.resultado || {};
          texto(
            "Listo: " +
              (resultado.eventos || 0) +
              " eventos, " +
              (resultado.con_senal || 0) +
              " con señal clara. Actualizando…",
            "text-success"
          );
          terminar();
          window.setTimeout(function () {
            window.location.reload();
          }, 1200);
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
        texto(datos.fase || "Analizando señal…", "text-secondary");
      })
      .catch(function () {
        texto("No se pudo consultar el estado del análisis.", "text-danger");
        terminar();
      });
  }

  function iniciar(url) {
    intentos = 0;
    consultar(url);
    temporizador = window.setInterval(function () {
      consultar(url);
    }, 2000);
  }

  if (formulario) {
    formulario.addEventListener("submit", function (evento) {
      evento.preventDefault();
      if (boton) {
        boton.disabled = true;
      }
      texto("Encolando el análisis…", "text-secondary");
      fetch(raiz.dataset.url, {
        method: "POST",
        body: new FormData(formulario),
        headers: { Accept: "application/json" },
      })
        .then(function (respuesta) {
          return respuesta.json().then(function (datos) {
            return { ok: respuesta.ok, datos: datos };
          });
        })
        .then(function (resultado) {
          var datos = resultado.datos || {};
          if (!resultado.ok || datos.estado === "error") {
            texto(datos.mensaje || "No se pudo encolar el análisis.", "text-danger");
            terminar();
            return;
          }
          if (!datos.task_id) {
            texto("El análisis no devolvió una tarea.", "text-danger");
            terminar();
            return;
          }
          var plantilla = raiz.dataset.estadoUrl || "";
          iniciar(plantilla.replace("__TASK__", datos.task_id));
        })
        .catch(function () {
          texto("No se pudo encolar el análisis.", "text-danger");
          terminar();
        });
    });
  }
})();
