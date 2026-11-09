/* Consulta de disponibilidad de formas de onda en el detalle del evento. */
(function () {
  "use strict";

  var panel = null;
  var contenedor = null;
  var sondeo = null;
  var limite = null;
  var consultando = false;
  var inicio = 0;
  var totalConsulta = 0;
  var consultadasConsulta = 0;
  var omitidasConsulta = 0;

  function activarTabDesdeHash() {
    if (window.location.hash !== "#sin-arribos") {
      return;
    }
    var boton = document.getElementById("tab-sin-arribos");
    if (boton && window.bootstrap && window.bootstrap.Tab) {
      window.bootstrap.Tab.getOrCreateInstance(boton).show();
    }
  }

  function iniciarModalStreams() {
    var modal = document.getElementById("modal-streams");
    if (!modal || modal.dataset.iniciado === "1") {
      return;
    }
    modal.dataset.iniciado = "1";
    modal.addEventListener("show.bs.modal", function (evento) {
      var boton = evento.relatedTarget;
      if (!boton) {
        return;
      }
      var estacion = (boton.dataset.station || "").trim() || "Estación";
      var streams = (boton.dataset.streams || "")
        .split(";")
        .filter(function (item) {
          return item.trim() !== "";
        });
      var titulo = document.getElementById("modal-streams-titulo");
      var lista = document.getElementById("modal-streams-lista");
      if (titulo) {
        titulo.textContent = "Streams de " + estacion;
      }
      if (lista) {
        lista.textContent = streams.join("\n");
      }
    });
  }

  function estadoElemento() {
    return document.getElementById("disponibilidad-estado");
  }

  function mostrarEstado(texto, clase) {
    var aviso = estadoElemento();
    if (aviso) {
      aviso.className = "alert small py-2 " + (clase || "alert-light border");
      aviso.textContent = texto;
      aviso.classList.remove("d-none");
    }
    var propagacion = document.getElementById(
      "propagacion-consulta-estado"
    );
    if (propagacion) {
      var color = "text-secondary";
      if (clase === "alert-danger") {
        color = "text-danger";
      } else if (clase === "alert-warning") {
        color = "text-warning";
      } else if (clase === "alert-success") {
        color = "text-success";
      }
      propagacion.className = "small " + color;
      propagacion.textContent = texto;
    }
  }

  function bloquearBotonesConsulta(activo) {
    [
      "btn-disponibilidad",
      "btn-disponibilidad-todas",
      "btn-propagacion-consultar",
    ].forEach(function (id) {
      var boton = document.getElementById(id);
      if (boton) {
        boton.disabled = activo;
      }
    });
  }

  function segundos() {
    return inicio ? Math.floor((Date.now() - inicio) / 1000) : 0;
  }

  function textoEnCurso() {
    if (totalConsulta > 0) {
      return (
        "Consultando " +
        consultadasConsulta +
        " de " +
        totalConsulta +
        " estaciones… (" +
        segundos() +
        " s)"
      );
    }
    return "Consulta en curso… (" + segundos() + " s)";
  }

  function detener() {
    if (sondeo !== null) {
      window.clearInterval(sondeo);
      sondeo = null;
    }
    if (limite !== null) {
      window.clearTimeout(limite);
      limite = null;
    }
    consultando = false;
  }

  function terminarConError(mensaje) {
    detener();
    if (contenedor) {
      contenedor.dataset.tarea = "";
      contenedor.dataset.error = "1";
    }
    bloquearBotonesConsulta(false);
    mostrarEstado(mensaje, "alert-danger");
  }

  function mostrarToast(mensaje, clase) {
    var destino = document.getElementById("toasts");
    if (!destino || !window.bootstrap || !window.bootstrap.Toast) {
      return;
    }
    var elemento = document.createElement("div");
    elemento.className =
      "toast align-items-center border-0 " +
      (clase || "text-bg-success");
    elemento.setAttribute("role", "status");
    elemento.innerHTML =
      '<div class="d-flex">' +
      '<div class="toast-body"></div>' +
      '<button type="button" class="btn-close btn-close-white me-2 m-auto"' +
      ' data-bs-dismiss="toast" aria-label="Cerrar"></button>' +
      "</div>";
    elemento.querySelector(".toast-body").textContent = mensaje;
    elemento.addEventListener("hidden.bs.toast", function () {
      elemento.remove();
    });
    destino.appendChild(elemento);
    new window.bootstrap.Toast(elemento, { delay: 4000 }).show();
  }

  function actualizarPanel(html) {
    if (!contenedor || !html) {
      return false;
    }
    contenedor.outerHTML = html;
    contenedor = document.getElementById("panel-sin-arribos-contenido");
    iniciarModalStreams();
    iniciarFiltrosSinArribos();
    if (mapaEstacionesActivo) {
      dibujarMapaEstaciones();
    } else if (propagacionActiva) {
      prepararPropagacion();
      actualizarPropagacion();
    }
    return Boolean(contenedor);
  }

  function formatoNumero(valor) {
    if (!Number.isFinite(valor)) {
      return "";
    }
    return Number(valor).toString();
  }

  function iniciarFiltrosSinArribos() {
    var contenedorActual = document.getElementById(
      "panel-sin-arribos-contenido"
    );
    var form = document.getElementById("filtros-sin-arribos");
    if (!contenedorActual || !form) {
      return;
    }
    var radio = document.getElementById("filtro-radio");
    var cerca = document.getElementById("filtro-cerca");
    var solo = document.getElementById("filtro-solo");
    var sinLimite = document.getElementById("filtro-sin-limite");
    var estado = document.getElementById("filtros-estado");
    var leyenda = document.getElementById("leyenda-cerca");
    var avisoRadio = document.getElementById("filtro-radio-aviso");
    var tabla = contenedorActual.querySelector("table");
    var botonEnviar = form.querySelector('button[type="submit"]');
    var descarga = contenedorActual.querySelector(
      'a[download][href*="sin-arribos.csv"]'
    );
    if (!radio || !cerca || !solo || !sinLimite) {
      return;
    }
    var exportado = parseFloat(contenedorActual.dataset.radioExportado);
    var temporizador = null;
    var ampliando = false;
    var sondeoAmpliar = null;
    var limiteAmpliar = null;
    var inicioAmpliar = 0;
    var consultandoAmpliar = false;

    function leerNumero(input, defecto) {
      var valor = parseFloat((input.value || "").replace(",", "."));
      return Number.isFinite(valor) && valor > 0 ? valor : defecto;
    }

    function aplicar() {
      var radioVal = leerNumero(radio, exportado);
      var aviso = false;
      if (
        Number.isFinite(exportado) &&
        Number.isFinite(radioVal) &&
        radioVal > exportado
      ) {
        radioVal = exportado;
        aviso = true;
      }
      var cercaVal = leerNumero(cerca, 50);
      var soloVal = solo.checked;
      if (avisoRadio) {
        if (aviso) {
          avisoRadio.textContent =
            "El radio máximo exportado es " +
            formatoNumero(exportado) +
            " km. Para ver estaciones más lejanas, marque Sin límite y pulse Aplicar.";
          avisoRadio.classList.remove("d-none");
        } else {
          avisoRadio.classList.add("d-none");
        }
      }

      var filas = tabla
        ? tabla.querySelectorAll("tbody tr[data-distancia]")
        : [];
      var mostradas = 0;
      var resaltadas = 0;
      filas.forEach(function (fila) {
        var distancia = parseFloat(fila.dataset.distancia);
        var categoria = fila.dataset.categoria || "normal";
        var esCerca =
          Number.isFinite(distancia) && distancia <= cercaVal;
        var visible = soloVal
          ? esCerca
          : !Number.isFinite(distancia) ||
            !Number.isFinite(radioVal) ||
            distancia <= radioVal;
        fila.classList.toggle("d-none", !visible);
        if (visible) {
          mostradas++;
          if (esCerca) {
            resaltadas++;
          }
        }
        fila.classList.remove(
          "no-picada-verificada",
          "no-picada-verificada-lejos",
          "no-picada-indicio",
          "no-picada-indicio-lejos",
          "no-picada-sin-evidencia"
        );
        if (categoria === "verificado") {
          fila.classList.add(
            esCerca ? "no-picada-verificada" : "no-picada-verificada-lejos"
          );
        } else if (categoria === "indicio") {
          fila.classList.add(
            esCerca ? "no-picada-indicio" : "no-picada-indicio-lejos"
          );
        } else if (categoria === "sin_evidencia" && esCerca) {
          fila.classList.add("no-picada-sin-evidencia");
        }
      });

      if (leyenda) {
        leyenda.textContent = formatoNumero(cercaVal);
      }
      if (estado) {
        var total = filas.length;
        if (total === 0) {
          estado.textContent = "Sin estaciones sin arribos para este evento.";
        } else if (soloVal) {
          estado.textContent =
            "Mostrando " +
            mostradas +
            " de " +
            total +
            " estaciones (solo ≤ " +
            formatoNumero(cercaVal) +
            " km) · " +
            resaltadas +
            " resaltadas como cerca.";
        } else if (Number.isFinite(radioVal)) {
          estado.textContent =
            "Mostrando " +
            mostradas +
            " de " +
            total +
            " estaciones (≤ " +
            formatoNumero(radioVal) +
            " km) · " +
            resaltadas +
            " resaltadas como cerca (≤ " +
            formatoNumero(cercaVal) +
            " km).";
        } else {
          estado.textContent =
            "Mostrando " +
            mostradas +
            " de " +
            total +
            " estaciones (sin tope) · " +
            resaltadas +
            " resaltadas como cerca (≤ " +
            formatoNumero(cercaVal) +
            " km).";
        }
      }

      if (descarga) {
        var url = new URL(descarga.href, window.location.origin);
        if (Number.isFinite(radioVal)) {
          url.searchParams.set("radio_km", formatoNumero(radioVal));
        } else {
          url.searchParams.delete("radio_km");
        }
        url.searchParams.set("cerca_km", formatoNumero(cercaVal));
        if (soloVal) {
          url.searchParams.set("solo_cercanas", "1");
        } else {
          url.searchParams.delete("solo_cercanas");
        }
        descarga.href = url.toString();
      }

      var actual = new URL(window.location.href);
      if (Number.isFinite(radioVal)) {
        actual.searchParams.set("radio_km", formatoNumero(radioVal));
      } else {
        actual.searchParams.delete("radio_km");
      }
      actual.searchParams.set("cerca_km", formatoNumero(cercaVal));
      if (soloVal) {
        actual.searchParams.set("solo_cercanas", "1");
      } else {
        actual.searchParams.delete("solo_cercanas");
      }
      window.history.replaceState({}, "", actual.toString());

      if (mapaEstacionesActivo) {
        dibujarMapaEstaciones();
      } else if (propagacionActiva) {
        prepararPropagacion();
        actualizarPropagacion();
      }
    }

    function segundosAmpliar() {
      return inicioAmpliar
        ? Math.floor((Date.now() - inicioAmpliar) / 1000)
        : 0;
    }

    function detenerAmpliacion() {
      if (sondeoAmpliar !== null) {
        window.clearInterval(sondeoAmpliar);
        sondeoAmpliar = null;
      }
      if (limiteAmpliar !== null) {
        window.clearTimeout(limiteAmpliar);
        limiteAmpliar = null;
      }
      consultandoAmpliar = false;
      ampliando = false;
    }

    function bloquearAmpliacion(activo) {
      [radio, cerca, solo, sinLimite].forEach(function (elemento) {
        if (elemento) {
          elemento.disabled = activo;
        }
      });
      if (botonEnviar) {
        botonEnviar.disabled = activo;
      }
      if (!activo && radio) {
        radio.disabled = Boolean(sinLimite && sinLimite.checked);
      }
    }

    function terminarErrorAmpliacion(mensaje) {
      detenerAmpliacion();
      bloquearAmpliacion(false);
      mostrarEstado(mensaje, "alert-danger");
    }

    function consultarAmpliacion(taskId) {
      if (consultandoAmpliar) {
        return;
      }
      consultandoAmpliar = true;
      var base = contenedorActual.dataset.urlAmpliarEstado.replace(
        "__TASK__",
        encodeURIComponent(taskId)
      );
      var url = new URL(base, window.location.origin);
      if (contenedorActual.dataset.volver) {
        url.searchParams.set("volver", contenedorActual.dataset.volver);
      }
      window
        .fetch(url.toString(), { headers: { Accept: "application/json" } })
        .then(function (respuesta) {
          return respuesta.json();
        })
        .then(function (datos) {
          consultandoAmpliar = false;
          if (datos.estado === "ok") {
            detenerAmpliacion();
            window.location.href = datos.url;
            return;
          }
          if (datos.estado === "error") {
            terminarErrorAmpliacion(
              datos.mensaje || "No se pudo ampliar contra la base."
            );
            return;
          }
          mostrarEstado(
            "Consultando la base de SeisComp… (" +
              segundosAmpliar() +
              " s)",
            "alert-info"
          );
        })
        .catch(function () {
          consultandoAmpliar = false;
          terminarErrorAmpliacion(
            "No se pudo consultar el estado de la ampliación."
          );
        });
    }

    function ampliar() {
      if (ampliando) {
        return;
      }
      ampliando = true;
      bloquearAmpliacion(true);
      inicioAmpliar = Date.now();
      mostrarEstado("Consultando la base de SeisComp…", "alert-info");
      var cuerpo = new URLSearchParams();
      cuerpo.set("sin_limite", sinLimite.checked ? "1" : "0");
      if (!sinLimite.checked) {
        cuerpo.set("radio_km", radio.value || "");
      }
      window
        .fetch(contenedorActual.dataset.urlAmpliar, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-CSRFToken":
              (document.querySelector('meta[name="csrf-token"]') || {})
                .content || "",
          },
          body: cuerpo.toString(),
        })
        .then(function (respuesta) {
          return respuesta.json().then(function (datos) {
            return { ok: respuesta.ok, datos: datos };
          });
        })
        .then(function (resultado) {
          if (!resultado.ok || resultado.datos.estado === "error") {
            throw new Error(
              resultado.datos.mensaje || "No se pudo ampliar."
            );
          }
          if (!resultado.datos.task_id) {
            throw new Error("No se pudo iniciar la ampliación.");
          }
          consultarAmpliacion(resultado.datos.task_id);
          sondeoAmpliar = window.setInterval(function () {
            consultarAmpliacion(resultado.datos.task_id);
          }, 1500);
          limiteAmpliar = window.setTimeout(function () {
            terminarErrorAmpliacion(
              "La ampliación tardó demasiado. Revise el estado del worker e intente nuevamente."
            );
          }, 150000);
        })
        .catch(function (error) {
          terminarErrorAmpliacion(
            error.message || "No se pudo iniciar la ampliación."
          );
        });
    }

    function decidir() {
      var valor = parseFloat((radio.value || "").replace(",", "."));
      if (
        sinLimite.checked ||
        (Number.isFinite(valor) &&
          Number.isFinite(exportado) &&
          valor > exportado)
      ) {
        ampliar();
      } else {
        aplicar();
      }
    }

    function programar() {
      if (temporizador !== null) {
        window.clearTimeout(temporizador);
      }
      temporizador = window.setTimeout(aplicar, 200);
    }

    radio.addEventListener("input", programar);
    cerca.addEventListener("input", programar);
    solo.addEventListener("change", aplicar);
    sinLimite.addEventListener("change", function () {
      radio.disabled = sinLimite.checked;
      if (sinLimite.checked) {
        mostrarEstado(
          "Se consultará la base de SeisComp sin límite. Pulse Aplicar.",
          "alert-info"
        );
      } else {
        aplicar();
      }
    });
    form.addEventListener("submit", function (evento) {
      evento.preventDefault();
      decidir();
    });
    radio.disabled = sinLimite.checked;
    aplicar();
  }

  function consultarEstado(taskId) {
    if (consultando || !contenedor) {
      return;
    }
    consultando = true;
    var base = contenedor.dataset.urlEstado.replace(
      "__TASK__",
      encodeURIComponent(taskId)
    );
    var url = new URL(base, window.location.origin);
    if (contenedor.dataset.volver) {
      url.searchParams.set("volver", contenedor.dataset.volver);
    }
    if (contenedor.dataset.noUsadas === "1") {
      url.searchParams.set("no_usadas", "1");
    }
    if (contenedor.dataset.disponibles === "1") {
      url.searchParams.set("disponibles", "1");
    }
    var radio = document.getElementById("filtro-radio");
    var cerca = document.getElementById("filtro-cerca");
    var solo = document.getElementById("filtro-solo");
    if (radio && radio.value.trim()) {
      url.searchParams.set("radio_km", radio.value.trim());
    }
    if (cerca && cerca.value.trim()) {
      url.searchParams.set("cerca_km", cerca.value.trim());
    }
    if (solo && solo.checked) {
      url.searchParams.set("solo_cercanas", "1");
    }
    window
      .fetch(url.toString(), { headers: { Accept: "application/json" } })
      .then(function (respuesta) {
        return respuesta.json();
      })
      .then(function (datos) {
        consultando = false;
        if (datos.estado === "ok") {
          detener();
          if (actualizarPanel(datos.html)) {
            mostrarToast("Disponibilidad actualizada");
            bloquearBotonesConsulta(false);
            mostrarEstado(
              "Disponibilidad actualizada.",
              "alert-success"
            );
            if (omitidasConsulta > 0) {
              mostrarEstado(
                "Se consultaron " +
                  consultadasConsulta +
                  " de " +
                  totalConsulta +
                  " estaciones. " +
                  omitidasConsulta +
                  " quedaron sin consultar; use Consultar todas o reduzca el radio.",
                "alert-warning"
              );
            }
          } else {
            window.location.reload();
          }
          return;
        }
        if (datos.estado === "error") {
          terminarConError(datos.mensaje || "No se pudo consultar.");
          return;
        }
        mostrarEstado(textoEnCurso(), "alert-info");
      })
      .catch(function () {
        consultando = false;
        terminarConError("No se pudo consultar el estado de la tarea.");
      });
  }

  function iniciarSondeo(taskId) {
    detener();
    if (contenedor) {
      contenedor.dataset.tarea = taskId;
    }
    inicio = Date.now();
    mostrarEstado(textoEnCurso(), "alert-info");
    consultarEstado(taskId);
    sondeo = window.setInterval(function () {
      consultarEstado(taskId);
    }, 1500);
    limite = window.setTimeout(function () {
      terminarConError(
        "La consulta tardó demasiado. Revise el estado del worker e intente nuevamente."
      );
    }, 300000);
  }

  function encolar(todas) {
    if (!contenedor) {
      return;
    }
    if (
      todas &&
      !window.confirm(
        "Consultar todas las estaciones puede tardar varios minutos. ¿Continuar?"
      )
    ) {
      return;
    }
    contenedor.dataset.error = "";
    bloquearBotonesConsulta(true);
    mostrarEstado("Enviando consulta…", "alert-info");
    var cuerpo = new URLSearchParams();
    var radio = document.getElementById("filtro-radio");
    var cerca = document.getElementById("filtro-cerca");
    var solo = document.getElementById("filtro-solo");
    if (radio && radio.value.trim()) {
      cuerpo.set("radio_km", radio.value.trim());
    }
    if (cerca && cerca.value.trim()) {
      cuerpo.set("cerca_km", cerca.value.trim());
    }
    if (solo && solo.checked) {
      cuerpo.set("solo_cercanas", "1");
    }
    if (contenedor.dataset.disponibles === "1") {
      cuerpo.set("disponibles", "1");
    }
    if (contenedor.dataset.ampliado) {
      cuerpo.set("ampliado", contenedor.dataset.ampliado);
    }
    if (todas) {
      cuerpo.set("todas", "1");
    }
    window
      .fetch(contenedor.dataset.urlEncolar, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded",
          "X-CSRFToken":
            (document.querySelector('meta[name="csrf-token"]') || {})
              .content || "",
        },
        body: cuerpo.toString(),
      })
      .then(function (respuesta) {
        return respuesta.json().then(function (datos) {
          return { ok: respuesta.ok, datos: datos };
        });
      })
      .then(function (resultado) {
        if (!resultado.ok || resultado.datos.estado === "error") {
          throw new Error(
            resultado.datos.mensaje || "No se pudo encolar la consulta."
          );
        }
        totalConsulta = Number(resultado.datos.total || 0);
        consultadasConsulta = Number(resultado.datos.consultadas || 0);
        omitidasConsulta = Number(resultado.datos.omitidas || 0);
        if (!resultado.datos.task_id) {
          throw new Error("No se pudo iniciar la consulta.");
        }
        iniciarSondeo(resultado.datos.task_id);
      })
      .catch(function (error) {
        terminarConError(
          error.message || "No se pudo iniciar la consulta."
        );
      });
  }

  function autoConsultar() {
    if (!contenedor) {
      return;
    }
    if (contenedor.dataset.error === "1") {
      return;
    }
    if (contenedor.dataset.tarea) {
      iniciarSondeo(contenedor.dataset.tarea);
      return;
    }
    if (
      contenedor.dataset.puedeConsultar === "1" &&
      contenedor.dataset.consultada !== "1"
    ) {
      encolar(false);
    }
  }

  var mapaEstacionesActivo = false;
  var mapaTiemposIniciado = false;
  var propagacionActiva = false;
  var propagacionReproduciendo = false;
  var propagacionVelocidad = 1;
  var propagacionTiempo = 0;
  var propagacionMax = 0;
  var propagacionDatos = null;
  var propagacionAnimacion = null;
  var propagacionUltimo = 0;
  var propagacionUltimoDibujo = 0;
  var VP_PROPAGACION = 6.0;
  var DURACION_PROPAGACION = 15;

  function datosEstacionesMapa() {
    var nodo = document.getElementById("estaciones-mapa-datos");
    if (!nodo) {
      return [];
    }
    try {
      return JSON.parse(nodo.textContent || "[]");
    } catch (error) {
      return [];
    }
  }

  function datosTiemposLlegada() {
    var nodo = document.getElementById("tiempos-llegada-datos");
    if (!nodo) {
      return {};
    }
    try {
      return JSON.parse(nodo.textContent || "{}");
    } catch (error) {
      return {};
    }
  }

  function puntosMapaVisibles() {
    var datos = datosEstacionesMapa();
    var radio = parseFloat(
      ((document.getElementById("filtro-radio") || {}).value || "").replace(
        ",",
        "."
      )
    );
    var cerca = parseFloat(
      ((document.getElementById("filtro-cerca") || {}).value || "").replace(
        ",",
        "."
      )
    );
    var solo = Boolean(
      (document.getElementById("filtro-solo") || {}).checked
    );
    var todas = Boolean(
      (document.getElementById("mapa-estaciones-todas") || {}).checked
    );
    if (!Number.isFinite(cerca)) {
      cerca = 50;
    }
    var arribos = datos.filter(function (punto) {
      return punto.tipo === "arribo";
    });
    var sinArribos = datos.filter(function (punto) {
      if (punto.tipo === "arribo") {
        return false;
      }
      var distancia = Number(punto.distancia_km);
      if (solo) {
        return Number.isFinite(distancia) && distancia <= cerca;
      }
      if (Number.isFinite(radio)) {
        return !Number.isFinite(distancia) || distancia <= radio;
      }
      return true;
    });
    if (!todas) {
      sinArribos = sinArribos.slice(0, 20);
    }
    return arribos.concat(sinArribos);
  }

  function claveEstacion(punto) {
    return (punto.red || "") + "|" + (punto.estacion || "");
  }

  function crearEnvolvente(observados) {
    var porTiempo = {};
    observados.forEach(function (observado) {
      var tiempo = Number(observado.segundos);
      var distancia = Number(observado.distancia_km);
      if (!Number.isFinite(tiempo) || !Number.isFinite(distancia)) {
        return;
      }
      if (tiempo <= 0) {
        return;
      }
      porTiempo[tiempo] = Math.max(porTiempo[tiempo] || 0, distancia);
    });
    var tiempos = Object.keys(porTiempo)
      .map(Number)
      .sort(function (a, b) {
        return a - b;
      });
    var knots = [{ t: 0, r: 0 }];
    var maxRadio = 0;
    tiempos.forEach(function (tiempo) {
      maxRadio = Math.max(maxRadio, porTiempo[tiempo]);
      knots.push({ t: tiempo, r: maxRadio });
    });
    return knots;
  }

  function radioEnvolvente(knots, tiempo) {
    if (!Number.isFinite(tiempo) || tiempo <= 0) {
      return 0;
    }
    if (!knots || knots.length < 2) {
      return VP_PROPAGACION * tiempo;
    }
    for (var indice = 1; indice < knots.length; indice += 1) {
      if (tiempo <= knots[indice].t) {
        var anterior = knots[indice - 1];
        var actual = knots[indice];
        var delta = actual.t - anterior.t;
        if (delta <= 0) {
          return actual.r;
        }
        return (
          anterior.r +
          ((actual.r - anterior.r) * (tiempo - anterior.t)) / delta
        );
      }
    }
    var ultimo = knots[knots.length - 1];
    var previo = knots[knots.length - 2];
    var deltaUltimo = ultimo.t - previo.t;
    var pendiente =
      deltaUltimo > 0
        ? (ultimo.r - previo.r) / deltaUltimo
        : VP_PROPAGACION;
    if (!(pendiente > 0)) {
      pendiente = VP_PROPAGACION;
    }
    return ultimo.r + pendiente * (tiempo - ultimo.t);
  }

  function tiempoParaDistancia(knots, distancia) {
    if (!Number.isFinite(distancia) || distancia <= 0) {
      return 0;
    }
    if (!knots || knots.length < 2) {
      return distancia / VP_PROPAGACION;
    }
    for (var indice = 1; indice < knots.length; indice += 1) {
      if (distancia <= knots[indice].r) {
        var anterior = knots[indice - 1];
        var actual = knots[indice];
        var deltaRadio = actual.r - anterior.r;
        if (deltaRadio <= 0) {
          return actual.t;
        }
        return (
          anterior.t +
          ((actual.t - anterior.t) * (distancia - anterior.r)) / deltaRadio
        );
      }
    }
    var ultimo = knots[knots.length - 1];
    var previo = knots[knots.length - 2];
    var deltaRadio = ultimo.r - previo.r;
    var deltaTiempo = ultimo.t - previo.t;
    var pendiente =
      deltaTiempo > 0
        ? deltaRadio / deltaTiempo
        : VP_PROPAGACION;
    if (!(pendiente > 0)) {
      pendiente = VP_PROPAGACION;
    }
    return ultimo.t + (distancia - ultimo.r) / pendiente;
  }

  function actualizarResumenEstimadas(datos) {
    var nodo = document.getElementById("propagacion-estimadas");
    if (!nodo || !datos) {
      return;
    }
    var estimadas = (datos.estaciones || []).filter(function (estacion) {
      return estacion.tipo !== "arribo";
    });
    if (!estimadas.length) {
      nodo.textContent = "Sin estaciones estimadas en el mapa.";
      return;
    }
    var sinConsultar = 0;
    var sinDatos = 0;
    var disponibles = 0;
    estimadas.forEach(function (estacion) {
      if (estacion.estado_ondas === "sin_datos") {
        sinDatos += 1;
      } else if (estacion.estado_ondas === "disponible") {
        disponibles += 1;
      } else {
        sinConsultar += 1;
      }
    });
    nodo.textContent =
      "Estimadas: " +
      estimadas.length +
      " · sin consultar: " +
      sinConsultar +
      " · sin datos: " +
      sinDatos +
      " · disponibles no usadas: " +
      disponibles;
  }

  function datosPropagacion() {
    var puntos = puntosMapaVisibles();
    var tiempos = datosTiemposLlegada();
    var evento = tiempos.evento || {};
    var latEvento = Number(evento.lat);
    var lonEvento = Number(evento.lon);
    if (!Number.isFinite(latEvento) || !Number.isFinite(lonEvento)) {
      return null;
    }
    var arribos = (tiempos.arribos || []).filter(function (arribo) {
      return (
        Number.isFinite(Number(arribo.segundos)) &&
        Number.isFinite(Number(arribo.distancia_km))
      );
    });
    var primeros = {};
    arribos.forEach(function (arribo) {
      var clave = claveEstacion(arribo);
      var segundos = Number(arribo.segundos);
      if (!(clave in primeros) || segundos < primeros[clave].segundos) {
        primeros[clave] = {
          segundos: segundos,
          distancia_km: Number(arribo.distancia_km),
          fase: arribo.fase || "",
          modo: arribo.modo || "",
        };
      }
    });
    var estaciones = puntos
      .filter(function (punto) {
        return (
          Number.isFinite(Number(punto.lat)) &&
          Number.isFinite(Number(punto.lon))
        );
      })
      .map(function (punto) {
        var clave = claveEstacion(punto);
        var primero = primeros[clave];
        if (!primero && punto.fases && punto.fases.length) {
          var validas = punto.fases
            .filter(function (fase) {
              return Number.isFinite(Number(fase.segundos));
            })
            .sort(function (a, b) {
              return Number(a.segundos) - Number(b.segundos);
            });
          if (validas.length) {
            primero = {
              segundos: Number(validas[0].segundos),
              distancia_km: Number(punto.distancia_km),
              fase: validas[0].fase || "",
              modo: validas[0].modo || "",
            };
          }
        }
        var distancia = Number(punto.distancia_km);
        if (!Number.isFinite(distancia) && primero) {
          distancia = Number(primero.distancia_km);
        }
        var observado = Boolean(
          primero &&
            Number.isFinite(Number(primero.segundos)) &&
            Number.isFinite(distancia)
        );
        return {
          red: punto.red || "",
          estacion: punto.estacion || "",
          lat: Number(punto.lat),
          lon: Number(punto.lon),
          distancia_km: Number.isFinite(distancia) ? distancia : null,
          tipo: punto.tipo || "sin_arribo",
          categoria: punto.categoria || "normal",
          evidencia: punto.evidencia || "",
          formas_onda: punto.formas_onda || "",
          disponible: punto.disponible || "",
          estado_ondas:
            punto.disponible === "Sí"
              ? "disponible"
              : punto.disponible === "No"
                ? "sin_datos"
                : "sin_consultar",
          streams: punto.streams || "",
          fases: punto.fases || [],
          observado: observado,
          tiempo: observado ? Number(primero.segundos) : null,
        };
      });
    var observados = Object.keys(primeros).map(function (clave) {
      return primeros[clave];
    });
    if (!observados.length) {
      observados = estaciones
        .filter(function (estacion) {
          return estacion.observado;
        })
        .map(function (estacion) {
          return {
            segundos: estacion.tiempo,
            distancia_km: estacion.distancia_km,
          };
        });
    }
    observados.sort(function (a, b) {
      return Number(a.segundos) - Number(b.segundos);
    });
    var knots = crearEnvolvente(observados);
    var maxTiempo = observados.length
      ? Number(observados[observados.length - 1].segundos)
      : 0;
    var distancias = estaciones
      .map(function (estacion) {
        return estacion.distancia_km;
      })
      .filter(Number.isFinite);
    var maxDistancia = distancias.length
      ? Math.max.apply(null, distancias)
      : 0;
    if (!(maxTiempo > 0)) {
      maxTiempo = maxDistancia / VP_PROPAGACION;
    }
    if (maxDistancia > 0) {
      maxTiempo = Math.max(
        maxTiempo,
        tiempoParaDistancia(knots, maxDistancia)
      );
    }
    maxTiempo = maxTiempo > 0 ? maxTiempo * 1.1 : 10;
    return {
      evento: { lat: latEvento, lon: lonEvento },
      estaciones: estaciones,
      knots: knots,
      vp: VP_PROPAGACION,
      maxT: maxTiempo,
      fuente: observados.length ? "observado" : "estimado",
    };
  }

  function prepararPropagacion() {
    propagacionDatos = datosPropagacion();
    if (!propagacionDatos) {
      propagacionMax = 0;
      return false;
    }
    propagacionMax = propagacionDatos.maxT;
    if (propagacionTiempo > propagacionMax) {
      propagacionTiempo = propagacionMax;
    }
    var slider = document.getElementById("propagacion-tiempo");
    if (slider) {
      slider.max = String(propagacionMax);
      slider.value = String(propagacionTiempo);
    }
    var play = document.getElementById("btn-propagacion-play");
    if (play) {
      play.disabled = !(propagacionMax > 0);
    }
    return true;
  }

  function actualizarCursorTiempos(tiempo) {
    var grafico = document.getElementById("grafico-tiempos");
    if (!grafico || !window.Plotly || !grafico.data) {
      return;
    }
    var indice = -1;
    grafico.data.forEach(function (traza, posicion) {
      if (traza.name === "Tiempo actual") {
        indice = posicion;
      }
    });
    if (indice < 0) {
      return;
    }
    window.Plotly.restyle(grafico, { y: [[tiempo, tiempo]] }, [indice]);
  }

  function actualizarPropagacion() {
    if (!propagacionActiva) {
      return;
    }
    if (!propagacionDatos && !prepararPropagacion()) {
      mostrarEstado(
        "No hay datos suficientes para propagar las ondas.",
        "alert-warning"
      );
      return;
    }
    var datos = propagacionDatos;
    var radio = radioEnvolvente(datos.knots, propagacionTiempo);
    var estaciones = datos.estaciones.map(function (estacion) {
      var llegada = estacion.observado
        ? estacion.tiempo
        : tiempoParaDistancia(datos.knots, estacion.distancia_km);
      var alcanzada =
        Number.isFinite(llegada) && propagacionTiempo >= llegada;
      var estado = alcanzada
        ? estacion.observado
          ? "observada"
          : "estimada"
        : "pendiente";
      return {
        red: estacion.red,
        estacion: estacion.estacion,
        lat: estacion.lat,
        lon: estacion.lon,
        distancia_km: estacion.distancia_km,
        tipo: estacion.tipo,
        categoria: estacion.categoria,
        evidencia: estacion.evidencia,
        formas_onda: estacion.formas_onda,
        disponible: estacion.disponible,
        estado_ondas: estacion.estado_ondas,
        streams: estacion.streams,
        fases: estacion.fases,
        observado: estacion.observado,
        llegada: llegada,
        estado: estado,
        pulso:
          alcanzada &&
          Number.isFinite(llegada) &&
          propagacionTiempo - llegada <= 1.5,
      };
    });
    var api = window.RCSMapaDetalle;
    if (!api || typeof api.mostrarPropagacion !== "function") {
      mostrarEstado(
        "El mapa interactivo no está disponible para la propagación.",
        "alert-warning"
      );
      return;
    }
    api.mostrarPropagacion({
      epicentro: datos.evento,
      estaciones: estaciones,
      radio_km: radio,
      tiempo: propagacionTiempo,
      fuente: datos.fuente,
    });
    actualizarResumenEstimadas(datos);
    var reloj = document.getElementById("propagacion-reloj");
    if (reloj) {
      reloj.textContent = "t = " + propagacionTiempo.toFixed(1) + " s";
    }
    var distancia = document.getElementById("propagacion-distancia");
    if (distancia) {
      distancia.textContent = "Frente: " + radio.toFixed(0) + " km";
    }
    var fuente = document.getElementById("propagacion-fuente");
    if (fuente) {
      fuente.textContent =
        datos.fuente === "observado"
          ? "Frente observado"
          : "Frente estimado (Vp " +
            VP_PROPAGACION.toFixed(1) +
            " km/s)";
    }
    var slider = document.getElementById("propagacion-tiempo");
    if (slider) {
      slider.value = String(propagacionTiempo);
    }
    actualizarCursorTiempos(propagacionTiempo);
  }

  function irAlMapa() {
    var mapa = document.getElementById("mapa-detalle");
    if (mapa) {
      mapa.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }

  function actualizarBotonPlay() {
    var boton = document.getElementById("btn-propagacion-play");
    if (!boton) {
      return;
    }
    boton.textContent = propagacionReproduciendo
      ? "Pausar"
      : "Reproducir";
    boton.classList.toggle("btn-primary", propagacionReproduciendo);
    boton.classList.toggle(
      "btn-outline-primary",
      !propagacionReproduciendo
    );
  }

  function pausarPropagacion() {
    propagacionReproduciendo = false;
    if (propagacionAnimacion !== null) {
      window.cancelAnimationFrame(propagacionAnimacion);
      propagacionAnimacion = null;
    }
    actualizarBotonPlay();
  }

  function tickPropagacion(ahora) {
    if (!propagacionActiva || !propagacionReproduciendo) {
      return;
    }
    var delta = (ahora - propagacionUltimo) / 1000;
    if (!Number.isFinite(delta) || delta < 0) {
      delta = 0;
    }
    delta = Math.min(delta, 0.25);
    propagacionUltimo = ahora;
    var avance =
      (propagacionMax / DURACION_PROPAGACION) * propagacionVelocidad;
    propagacionTiempo += delta * avance;
    if (propagacionTiempo >= propagacionMax) {
      propagacionTiempo = propagacionMax;
      actualizarPropagacion();
      pausarPropagacion();
      return;
    }
    if (ahora - propagacionUltimoDibujo >= 50) {
      propagacionUltimoDibujo = ahora;
      actualizarPropagacion();
    }
    propagacionAnimacion = window.requestAnimationFrame(tickPropagacion);
  }

  function reproducirPropagacion() {
    if (!propagacionActiva) {
      abrirPropagacion();
    }
    if (!propagacionActiva || !(propagacionMax > 0)) {
      return;
    }
    if (propagacionTiempo >= propagacionMax) {
      propagacionTiempo = 0;
      actualizarPropagacion();
    }
    propagacionReproduciendo = true;
    propagacionUltimo = window.performance
      ? window.performance.now()
      : Date.now();
    propagacionUltimoDibujo = 0;
    actualizarBotonPlay();
    propagacionAnimacion = window.requestAnimationFrame(tickPropagacion);
  }

  function reiniciarPropagacion() {
    pausarPropagacion();
    propagacionTiempo = 0;
    actualizarPropagacion();
  }

  function abrirPropagacion() {
    if (propagacionActiva) {
      return;
    }
    if (mapaEstacionesActivo) {
      mapaEstacionesActivo = false;
      if (window.RCSMapaDetalle && window.RCSMapaDetalle.ocultarEstaciones) {
        window.RCSMapaDetalle.ocultarEstaciones();
      }
      var botonEstaciones = document.getElementById("btn-estaciones-mapa");
      if (botonEstaciones) {
        botonEstaciones.textContent = "Estaciones en el mapa";
      }
    }
    propagacionActiva = true;
    propagacionTiempo = 0;
    if (!prepararPropagacion()) {
      propagacionActiva = false;
      mostrarEstado(
        "No hay datos suficientes para propagar las ondas.",
        "alert-warning"
      );
      return;
    }
    var controles = document.getElementById("propagacion-controles");
    if (controles) {
      controles.classList.remove("d-none");
      controles.classList.add("d-flex");
    }
    var opciones = document.getElementById("mapa-estaciones-opciones");
    if (opciones) {
      opciones.classList.remove("d-none");
    }
    var boton = document.getElementById("btn-propagacion");
    if (boton) {
      boton.textContent = "Ocultar propagación";
    }
    var leyenda = document.getElementById("leyenda-estaciones-mapa");
    if (leyenda) {
      leyenda.textContent =
        "▲ observada · △ sin consultar · △× sin datos · △• disponible no usada";
    }
    actualizarPropagacion();
    irAlMapa();
  }

  function cerrarPropagacion() {
    if (!propagacionActiva) {
      return;
    }
    pausarPropagacion();
    propagacionActiva = false;
    if (window.RCSMapaDetalle && window.RCSMapaDetalle.ocultarPropagacion) {
      window.RCSMapaDetalle.ocultarPropagacion();
    }
    var controles = document.getElementById("propagacion-controles");
    if (controles) {
      controles.classList.add("d-none");
      controles.classList.remove("d-flex");
    }
    var boton = document.getElementById("btn-propagacion");
    if (boton) {
      boton.textContent = "Propagación";
    }
    var opciones = document.getElementById("mapa-estaciones-opciones");
    if (opciones && !mapaEstacionesActivo) {
      opciones.classList.add("d-none");
    }
    var leyenda = document.getElementById("leyenda-estaciones-mapa");
    if (leyenda) {
      leyenda.textContent = "▲ pick observado · △ sin arribo";
    }
  }

  function alternarPropagacion() {
    if (propagacionActiva) {
      cerrarPropagacion();
    } else {
      abrirPropagacion();
    }
  }

  function dibujarMapaEstaciones() {
    if (!mapaEstacionesActivo) {
      return;
    }
    var api = window.RCSMapaDetalle;
    if (!api || typeof api.mostrarEstaciones !== "function") {
      mostrarEstado(
        "El mapa interactivo no está disponible para agregar estaciones.",
        "alert-warning"
      );
      return;
    }
    api.mostrarEstaciones(puntosMapaVisibles());
    var boton = document.getElementById("btn-estaciones-mapa");
    if (boton) {
      boton.textContent = "Ocultar estaciones";
    }
    var opciones = document.getElementById("mapa-estaciones-opciones");
    if (opciones) {
      opciones.classList.remove("d-none");
    }
    var leyenda = document.getElementById("leyenda-estaciones-mapa");
    if (leyenda) {
      leyenda.textContent = "▲ pick observado · △ sin arribo";
    }
  }

  function alternarMapaEstaciones() {
    if (!mapaEstacionesActivo) {
      if (propagacionActiva) {
        cerrarPropagacion();
      }
      mapaEstacionesActivo = true;
      dibujarMapaEstaciones();
      irAlMapa();
      return;
    }
    mapaEstacionesActivo = false;
    if (window.RCSMapaDetalle && window.RCSMapaDetalle.ocultarEstaciones) {
      window.RCSMapaDetalle.ocultarEstaciones();
    }
    var boton = document.getElementById("btn-estaciones-mapa");
    if (boton) {
      boton.textContent = "Estaciones en el mapa";
    }
    var opciones = document.getElementById("mapa-estaciones-opciones");
    if (opciones && !propagacionActiva) {
      opciones.classList.add("d-none");
    }
    var leyenda = document.getElementById("leyenda-estaciones-mapa");
    if (leyenda) {
      leyenda.textContent = "▲ pick observado · △ sin arribo";
    }
  }

  function dibujarTiemposLlegada() {
    var datos = datosTiemposLlegada();
    var contenedorGrafico = document.getElementById("grafico-tiempos");
    if (!contenedorGrafico) {
      return;
    }
    if (!window.Plotly) {
      contenedorGrafico.innerHTML =
        '<div class="text-secondary small p-3">No se pudo cargar el gráfico.</div>';
      return;
    }
    var vp = parseFloat(
      ((document.getElementById("tiempos-vp") || {}).value || "6").replace(
        ",",
        "."
      )
    );
    var vs = parseFloat(
      ((document.getElementById("tiempos-vs") || {}).value || "3.5").replace(
        ",",
        "."
      )
    );
    if (!Number.isFinite(vp) || vp <= 0) {
      vp = 6.0;
    }
    if (!Number.isFinite(vs) || vs <= 0) {
      vs = 3.5;
    }
    var arribos = (datos.arribos || []).filter(function (arribo) {
      return (
        Number.isFinite(Number(arribo.distancia_km)) &&
        Number.isFinite(Number(arribo.segundos))
      );
    });
    var clavesArribo = {};
    arribos.forEach(function (arribo) {
      clavesArribo[(arribo.red || "") + "|" + (arribo.estacion || "")] = true;
    });
    var estaciones = (datos.estaciones || [])
      .filter(function (estacion) {
        var clave = (estacion.red || "") + "|" + (estacion.estacion || "");
        return (
          Number.isFinite(Number(estacion.distancia_km)) &&
          !clavesArribo[clave]
        );
      })
      .slice(0, 20);
    var distancias = arribos
      .map(function (arribo) { return Number(arribo.distancia_km); })
      .concat(
        estaciones.map(function (estacion) {
          return Number(estacion.distancia_km);
        })
      );
    var maxKm = Math.max.apply(null, [100].concat(distancias || []));
    var tiemposGrafico = arribos
      .map(function (arribo) {
        return Number(arribo.segundos);
      })
      .concat(
        estaciones.map(function (estacion) {
          return Number(estacion.distancia_km) / vp;
        })
      );
    var maxTChart = Math.max.apply(null, [10].concat(tiemposGrafico || []));
    maxTChart = maxTChart * 1.08;
    var tiempoActual = propagacionActiva ? propagacionTiempo : 0;
    var trazas = [
      {
        type: "scatter",
        mode: "lines",
        name: "Referencia P (" + vp.toFixed(1) + " km/s)",
        x: [0, maxKm],
        y: [0, maxKm / vp],
        line: { color: "#adb5bd", dash: "dot", width: 1 },
        hoverinfo: "skip",
      },
      {
        type: "scatter",
        mode: "lines",
        name: "Referencia S (" + vs.toFixed(1) + " km/s)",
        x: [0, maxKm],
        y: [0, maxKm / vs],
        line: { color: "#ced4da", dash: "dot", width: 1 },
        hoverinfo: "skip",
      },
      {
        type: "scatter",
        mode: "markers",
        name: "Picks observados",
        x: arribos.map(function (arribo) {
          return Number(arribo.distancia_km);
        }),
        y: arribos.map(function (arribo) {
          return Number(arribo.segundos);
        }),
        text: arribos.map(function (arribo) {
          return (
            (arribo.red || "") +
            " " +
            (arribo.estacion || "") +
            " · " +
            (arribo.fase || "") +
            " · " +
            (arribo.modo || "")
          );
        }),
        marker: {
          size: 9,
          color: arribos.map(function (arribo) {
            return (arribo.modo || "").toLowerCase() === "manual"
              ? "#0b7285"
              : "#ffffff";
          }),
          symbol: "triangle-up",
          line: {
            color: arribos.map(function (arribo) {
              return (arribo.modo || "").toLowerCase() === "manual"
                ? "#ffffff"
                : "#0b7285";
            }),
            width: 1.2,
          },
        },
        hovertemplate: "%{text}<br>%{x:.1f} km · %{y:.1f} s<extra></extra>",
      },
    ];
    if (estaciones.length) {
      trazas.push({
        type: "scatter",
        mode: "markers",
        name: "Sin arribos (P estimada)",
        x: estaciones.map(function (estacion) {
          return Number(estacion.distancia_km);
        }),
        y: estaciones.map(function (estacion) {
          return Number(estacion.distancia_km) / vp;
        }),
        text: estaciones.map(function (estacion) {
          return (estacion.red || "") + " " + (estacion.estacion || "");
        }),
        marker: {
          size: 7,
          color: "#ffffff",
          symbol: "triangle-up",
          line: { color: "#adb5bd", width: 1.2 },
        },
        hovertemplate: "%{text}<br>P estimada · %{y:.1f} s<extra></extra>",
      });
    }
    trazas.push({
      type: "scatter",
      mode: "lines",
      name: "Tiempo actual",
      x: [0, maxKm],
      y: [tiempoActual, tiempoActual],
      line: { color: "#0b7285", width: 1.5, dash: "dash" },
      hoverinfo: "skip",
      showlegend: false,
    });
    window.Plotly.newPlot(
      contenedorGrafico,
      trazas,
      {
        margin: { l: 60, r: 20, t: 100, b: 55 },
        xaxis: {
          title: { text: "Distancia (km)", standoff: 10 },
        },
        yaxis: {
          title: { text: "Tiempo desde el origen (s)" },
          range: [0, maxTChart],
        },
        hovermode: "closest",
        legend: {
          orientation: "h",
          x: 0,
          xanchor: "left",
          y: 1.02,
          yanchor: "bottom",
          font: { size: 11 },
        },
      },
      { responsive: true, displaylogo: false }
    );
  }

  function abrirTiemposLlegada() {
    var modal = document.getElementById("modal-tiempos");
    if (!modal) {
      return;
    }
    if (!window.bootstrap || !window.bootstrap.Modal) {
      return;
    }
    var instancia = window.bootstrap.Modal.getOrCreateInstance(modal);
    if (modal.classList.contains("show")) {
      dibujarTiemposLlegada();
      return;
    }
    modal.addEventListener("shown.bs.modal", dibujarTiemposLlegada, {
      once: true,
    });
    instancia.show();
  }

  function iniciarMapaTiempos() {
    if (mapaTiemposIniciado) {
      return;
    }
    mapaTiemposIniciado = true;
    var botonMapa = document.getElementById("btn-estaciones-mapa");
    if (botonMapa) {
      botonMapa.addEventListener("click", function (evento) {
        evento.preventDefault();
        alternarMapaEstaciones();
      });
    }
    var botonTiempos = document.getElementById("btn-tiempos-llegada");
    if (botonTiempos) {
      botonTiempos.addEventListener("click", function (evento) {
        evento.preventDefault();
        abrirTiemposLlegada();
      });
    }
    var botonPropagacion = document.getElementById("btn-propagacion");
    if (botonPropagacion) {
      botonPropagacion.addEventListener("click", function (evento) {
        evento.preventDefault();
        alternarPropagacion();
      });
    }
    var botonPlay = document.getElementById("btn-propagacion-play");
    if (botonPlay) {
      botonPlay.addEventListener("click", function (evento) {
        evento.preventDefault();
        if (propagacionReproduciendo) {
          pausarPropagacion();
        } else {
          reproducirPropagacion();
        }
      });
    }
    var sliderPropagacion = document.getElementById("propagacion-tiempo");
    if (sliderPropagacion) {
      sliderPropagacion.addEventListener("input", function () {
        pausarPropagacion();
        var valor = parseFloat(sliderPropagacion.value);
        if (!Number.isFinite(valor)) {
          return;
        }
        propagacionTiempo = Math.min(
          Math.max(valor, 0),
          propagacionMax
        );
        actualizarPropagacion();
      });
    }
    var velocidad = document.getElementById("propagacion-velocidad");
    if (velocidad) {
      velocidad.addEventListener("change", function () {
        var valor = parseFloat(velocidad.value);
        propagacionVelocidad =
          Number.isFinite(valor) && valor > 0 ? valor : 1;
      });
    }
    var reiniciar = document.getElementById("btn-propagacion-reiniciar");
    if (reiniciar) {
      reiniciar.addEventListener("click", function (evento) {
        evento.preventDefault();
        reiniciarPropagacion();
      });
    }
    var consultarPropagacion = document.getElementById(
      "btn-propagacion-consultar"
    );
    if (consultarPropagacion) {
      consultarPropagacion.addEventListener("click", function (evento) {
        evento.preventDefault();
        encolar(false);
      });
    }
    var botonActualizar = document.getElementById("btn-tiempos-actualizar");
    if (botonActualizar) {
      botonActualizar.addEventListener("click", function (evento) {
        evento.preventDefault();
        dibujarTiemposLlegada();
      });
    }
    var todas = document.getElementById("mapa-estaciones-todas");
    if (todas) {
      todas.addEventListener("change", function () {
        if (mapaEstacionesActivo) {
          dibujarMapaEstaciones();
        } else if (propagacionActiva) {
          prepararPropagacion();
          actualizarPropagacion();
        }
      });
    }
  }

  function iniciarPanel() {
    panel = document.getElementById("panel-sin-arribos");
    contenedor = document.getElementById("panel-sin-arribos-contenido");
    if (!panel || !contenedor) {
      return;
    }
    iniciarModalStreams();
    iniciarFiltrosSinArribos();
    panel.addEventListener("click", function (evento) {
      var botonTodas = evento.target.closest("#btn-disponibilidad-todas");
      if (botonTodas) {
        evento.preventDefault();
        encolar(true);
        return;
      }
      var boton = evento.target.closest("#btn-disponibilidad");
      if (!boton) {
        return;
      }
      evento.preventDefault();
      encolar(false);
    });

    if (contenedor.dataset.tarea) {
      iniciarSondeo(contenedor.dataset.tarea);
    }

    var tab = document.getElementById("tab-sin-arribos");
    if (tab) {
      tab.addEventListener("shown.bs.tab", function () {
        autoConsultar();
      });
    }
    if (window.location.hash === "#sin-arribos") {
      autoConsultar();
    }
  }

  window.addEventListener("DOMContentLoaded", function () {
    activarTabDesdeHash();
    iniciarMapaTiempos();
    iniciarPanel();
  });
})();
