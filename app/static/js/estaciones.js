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

  function mostrarIndicadorConsulta(texto) {
    var indicador = document.getElementById("consulta-ondas-indicador");
    if (!indicador) {
      return;
    }
    var textoEl = document.getElementById("consulta-ondas-texto");
    if (textoEl) {
      textoEl.textContent = texto || "Consultando formas de onda…";
    }
    indicador.classList.remove("d-none");
  }

  function ocultarIndicadorConsulta() {
    var indicador = document.getElementById("consulta-ondas-indicador");
    if (indicador) {
      indicador.classList.add("d-none");
    }
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
    if (clase === "alert-info") {
      mostrarIndicadorConsulta(texto);
    } else {
      ocultarIndicadorConsulta();
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
  var VS_PROPAGACION = 3.5;
  var DURACION_PROPAGACION = 15;
  var propagacionMostrarP = true;
  var propagacionMostrarS = true;

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

  function radioEnvolvente(knots, tiempo, velocidad) {
    var vp = velocidad || VP_PROPAGACION;
    if (!Number.isFinite(tiempo) || tiempo <= 0) {
      return 0;
    }
    if (!knots || knots.length < 2) {
      return vp * tiempo;
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
        : vp;
    if (!(pendiente > 0)) {
      pendiente = vp;
    }
    return ultimo.r + pendiente * (tiempo - ultimo.t);
  }

  function tiempoParaDistancia(knots, distancia, velocidad) {
    var vp = velocidad || VP_PROPAGACION;
    if (!Number.isFinite(distancia) || distancia <= 0) {
      return 0;
    }
    if (!knots || knots.length < 2) {
      return distancia / vp;
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
        : vp;
    if (!(pendiente > 0)) {
      pendiente = vp;
    }
    return ultimo.t + (distancia - ultimo.r) / pendiente;
  }

  function estadoOndasPunto(punto) {
    if (punto.estado_ondas) {
      return punto.estado_ondas;
    }
    if (punto.tipo === "arribo") {
      return "observada";
    }
    if (punto.disponible === "Sí") {
      return "disponible";
    }
    if (punto.disponible === "No") {
      return "sin_datos";
    }
    return "sin_consultar";
  }

  function actualizarResumenEstados(puntos) {
    var resumen = document.getElementById("resumen-estados-estaciones");
    var propagacion = document.getElementById("propagacion-estimadas");
    if (!resumen && !propagacion) {
      return;
    }
    var lista = puntos || [];
    var observadas = 0;
    var sinConsultar = 0;
    var sinDatos = 0;
    var disponibles = 0;
    lista.forEach(function (punto) {
      var estado = estadoOndasPunto(punto);
      if (estado === "observada") {
        observadas += 1;
      } else if (estado === "sin_datos") {
        sinDatos += 1;
      } else if (estado === "disponible") {
        disponibles += 1;
      } else {
        sinConsultar += 1;
      }
    });
    var texto = lista.length
      ? "En el mapa: " +
        observadas +
        " observadas · " +
        sinConsultar +
        " sin consultar · " +
        sinDatos +
        " sin datos · " +
        disponibles +
        " disponibles no usadas"
      : "Sin estaciones en el mapa.";
    if (resumen) {
      resumen.textContent = texto;
    }
    if (propagacion) {
      propagacion.textContent = texto;
    }
  }

  function mostrarLeyendaEstados(mostrar) {
    var leyenda = document.getElementById("leyenda-estados-estaciones");
    if (!leyenda) {
      return;
    }
    leyenda.classList.toggle("d-none", !mostrar);
    leyenda.classList.toggle("d-flex", mostrar);
  }

  function actualizarResumenFrentes(estaciones) {
    var nodo = document.getElementById("propagacion-alcanzadas");
    if (!nodo) {
      return;
    }
    var alcanzadasP = 0;
    var alcanzadasS = 0;
    var pendientes = 0;
    (estaciones || []).forEach(function (estacion) {
      if (estacion.p_estado !== "pendiente") {
        alcanzadasP += 1;
      }
      if (estacion.s_estado !== "pendiente") {
        alcanzadasS += 1;
      }
      if (
        estacion.p_estado === "pendiente" &&
        estacion.s_estado === "pendiente"
      ) {
        pendientes += 1;
      }
    });
    nodo.textContent =
      "P alcanzadas: " +
      alcanzadasP +
      " · S alcanzadas: " +
      alcanzadasS +
      " · pendientes: " +
      pendientes;
  }

  function esFaseP(fase) {
    return /^P/i.test(String(fase || "").trim());
  }

  function esFaseS(fase) {
    return /^S/i.test(String(fase || "").trim());
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
    var primerosP = {};
    var primerosS = {};
    arribos.forEach(function (arribo) {
      var fase = String(arribo.fase || "");
      var clave = claveEstacion(arribo);
      var segundos = Number(arribo.segundos);
      var destino = null;
      if (esFaseP(fase)) {
        destino = primerosP;
      } else if (esFaseS(fase)) {
        destino = primerosS;
      }
      if (!destino) {
        return;
      }
      if (!(clave in destino) || segundos < destino[clave].segundos) {
        destino[clave] = {
          segundos: segundos,
          distancia_km: Number(arribo.distancia_km),
          fase: fase,
          modo: arribo.modo || "",
        };
      }
    });
    function primeroDeFases(fases, probar) {
      var validas = (fases || [])
        .filter(function (fase) {
          return (
            probar(fase.fase) &&
            Number.isFinite(Number(fase.segundos))
          );
        })
        .sort(function (a, b) {
          return Number(a.segundos) - Number(b.segundos);
        });
      if (!validas.length) {
        return null;
      }
      return {
        segundos: Number(validas[0].segundos),
        distancia_km: null,
        fase: validas[0].fase || "",
        modo: validas[0].modo || "",
      };
    }
    var estaciones = puntos
      .filter(function (punto) {
        return (
          Number.isFinite(Number(punto.lat)) &&
          Number.isFinite(Number(punto.lon))
        );
      })
      .map(function (punto) {
        var clave = claveEstacion(punto);
        var primeroP =
          primerosP[clave] || primeroDeFases(punto.fases, esFaseP);
        var primeroS =
          primerosS[clave] || primeroDeFases(punto.fases, esFaseS);
        var distancia = Number(punto.distancia_km);
        if (!Number.isFinite(distancia) && primeroP) {
          distancia = Number(primeroP.distancia_km);
        }
        if (!Number.isFinite(distancia) && primeroS) {
          distancia = Number(primeroS.distancia_km);
        }
        var pObservado = Boolean(
          primeroP &&
            Number.isFinite(Number(primeroP.segundos)) &&
            Number.isFinite(distancia)
        );
        var sObservado = Boolean(
          primeroS &&
            Number.isFinite(Number(primeroS.segundos)) &&
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
          estado_ondas: estadoOndasPunto(punto),
          streams: punto.streams || "",
          fases: punto.fases || [],
          p_observado: pObservado,
          p_tiempo: pObservado ? Number(primeroP.segundos) : null,
          s_observado: sObservado,
          s_tiempo: sObservado ? Number(primeroS.segundos) : null,
          observado: pObservado || sObservado,
          tiempo: pObservado
            ? Number(primeroP.segundos)
            : sObservado
              ? Number(primeroS.segundos)
              : null,
        };
      });
    var observadosP = Object.keys(primerosP).map(function (clave) {
      return primerosP[clave];
    });
    var observadosS = Object.keys(primerosS).map(function (clave) {
      return primerosS[clave];
    });
    if (!observadosP.length) {
      observadosP = estaciones
        .filter(function (estacion) {
          return estacion.p_observado;
        })
        .map(function (estacion) {
          return {
            segundos: estacion.p_tiempo,
            distancia_km: estacion.distancia_km,
          };
        });
    }
    if (!observadosS.length) {
      observadosS = estaciones
        .filter(function (estacion) {
          return estacion.s_observado;
        })
        .map(function (estacion) {
          return {
            segundos: estacion.s_tiempo,
            distancia_km: estacion.distancia_km,
          };
        });
    }
    observadosP.sort(function (a, b) {
      return Number(a.segundos) - Number(b.segundos);
    });
    observadosS.sort(function (a, b) {
      return Number(a.segundos) - Number(b.segundos);
    });
    var knotsP = crearEnvolvente(observadosP);
    var knotsS = crearEnvolvente(observadosS);
    var distancias = estaciones
      .map(function (estacion) {
        return estacion.distancia_km;
      })
      .filter(Number.isFinite);
    var maxDistancia = distancias.length
      ? Math.max.apply(null, distancias)
      : 0;
    var maxTP = observadosP.length
      ? Number(observadosP[observadosP.length - 1].segundos)
      : 0;
    var maxTS = observadosS.length
      ? Number(observadosS[observadosS.length - 1].segundos)
      : 0;
    if (!(maxTP > 0)) {
      maxTP = maxDistancia / VP_PROPAGACION;
    }
    if (!(maxTS > 0)) {
      maxTS = maxDistancia / VS_PROPAGACION;
    }
    if (maxDistancia > 0) {
      maxTP = Math.max(
        maxTP,
        tiempoParaDistancia(
          knotsP,
          maxDistancia,
          VP_PROPAGACION
        )
      );
      maxTS = Math.max(
        maxTS,
        tiempoParaDistancia(
          knotsS,
          maxDistancia,
          VS_PROPAGACION
        )
      );
    }
    var maxTiempo = Math.max(maxTP, maxTS);
    maxTiempo = maxTiempo > 0 ? maxTiempo * 1.1 : 10;
    return {
      evento: { lat: latEvento, lon: lonEvento },
      estaciones: estaciones,
      knotsP: knotsP,
      knotsS: knotsS,
      vp: VP_PROPAGACION,
      vs: VS_PROPAGACION,
      maxT: maxTiempo,
      fuenteP: observadosP.length ? "observado" : "estimado",
      fuenteS: observadosS.length ? "observado" : "estimado",
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
    var radioP = radioEnvolvente(
      datos.knotsP,
      propagacionTiempo,
      datos.vp
    );
    var radioS = radioEnvolvente(
      datos.knotsS,
      propagacionTiempo,
      datos.vs
    );
    var estaciones = datos.estaciones.map(function (estacion) {
      var pTiempo = estacion.p_observado
        ? estacion.p_tiempo
        : Number.isFinite(estacion.distancia_km)
          ? tiempoParaDistancia(
              datos.knotsP,
              estacion.distancia_km,
              datos.vp
            )
          : null;
      var sTiempo = estacion.s_observado
        ? estacion.s_tiempo
        : Number.isFinite(estacion.distancia_km)
          ? tiempoParaDistancia(
              datos.knotsS,
              estacion.distancia_km,
              datos.vs
            )
          : null;
      var pAlcanzada =
        Number.isFinite(pTiempo) && propagacionTiempo >= pTiempo;
      var sAlcanzada =
        Number.isFinite(sTiempo) && propagacionTiempo >= sTiempo;
      var pEstado = pAlcanzada
        ? estacion.p_observado
          ? "observada"
          : "estimada"
        : "pendiente";
      var sEstado = sAlcanzada
        ? estacion.s_observado
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
        est_lista: estacion.est_lista,
        est_vigencia: estacion.est_vigencia,
        software: estacion.software,
        fases: estacion.fases,
        p_observado: estacion.p_observado,
        p_tiempo: pTiempo,
        p_estado: pEstado,
        p_pulso:
          pAlcanzada &&
          Number.isFinite(pTiempo) &&
          propagacionTiempo - pTiempo <= 1.5,
        s_observado: estacion.s_observado,
        s_tiempo: sTiempo,
        s_estado: sEstado,
        s_pulso:
          sAlcanzada &&
          Number.isFinite(sTiempo) &&
          propagacionTiempo - sTiempo <= 1.5,
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
    var instantanea = {
      epicentro: datos.evento,
      estaciones: estaciones,
      frentes: {
        p: {
          radio_km: radioP,
          mostrar: propagacionMostrarP,
          fuente: datos.fuenteP,
        },
        s: {
          radio_km: radioS,
          mostrar: propagacionMostrarS,
          fuente: datos.fuenteS,
        },
      },
      tiempo: propagacionTiempo,
    };
    api.mostrarPropagacion(instantanea);
    if (typeof api.mostrarPropagacionPerfil === "function") {
      api.mostrarPropagacionPerfil(instantanea);
    }
    actualizarResumenEstados(estaciones);
    actualizarResumenFrentes(estaciones);
    var reloj = document.getElementById("propagacion-reloj");
    if (reloj) {
      reloj.textContent = "t = " + propagacionTiempo.toFixed(1) + " s";
    }
    var distancia = document.getElementById("propagacion-distancia");
    if (distancia) {
      var partes = [];
      if (propagacionMostrarP) {
        partes.push("P " + radioP.toFixed(0) + " km");
      }
      if (propagacionMostrarS) {
        partes.push("S " + radioS.toFixed(0) + " km");
      }
      distancia.textContent = partes.length
        ? partes.join(" · ")
        : "Frentes ocultos";
    }
    var fuente = document.getElementById("propagacion-fuente");
    if (fuente) {
      fuente.textContent =
        "P " +
        (datos.fuenteP === "observado" ? "observado" : "estimado") +
        " · S " +
        (datos.fuenteS === "observado" ? "observado" : "estimado");
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
      if (
        window.RCSMapaDetalle &&
        window.RCSMapaDetalle.ocultarEstacionesPerfil
      ) {
        window.RCSMapaDetalle.ocultarEstacionesPerfil();
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
    mostrarLeyendaEstados(true);
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
    if (
      window.RCSMapaDetalle &&
      window.RCSMapaDetalle.ocultarPropagacionPerfil
    ) {
      window.RCSMapaDetalle.ocultarPropagacionPerfil();
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
    if (!mapaEstacionesActivo) {
      mostrarLeyendaEstados(false);
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
    var puntos = puntosMapaVisibles();
    api.mostrarEstaciones(puntos);
    if (typeof api.mostrarEstacionesPerfil === "function") {
      api.mostrarEstacionesPerfil(puntos);
    }
    actualizarResumenEstados(puntos);
    var boton = document.getElementById("btn-estaciones-mapa");
    if (boton) {
      boton.textContent = "Ocultar estaciones";
    }
    var opciones = document.getElementById("mapa-estaciones-opciones");
    if (opciones) {
      opciones.classList.remove("d-none");
    }
    mostrarLeyendaEstados(true);
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
    if (
      window.RCSMapaDetalle &&
      window.RCSMapaDetalle.ocultarEstacionesPerfil
    ) {
      window.RCSMapaDetalle.ocultarEstacionesPerfil();
    }
    var boton = document.getElementById("btn-estaciones-mapa");
    if (boton) {
      boton.textContent = "Estaciones en el mapa";
    }
    var opciones = document.getElementById("mapa-estaciones-opciones");
    if (opciones && !propagacionActiva) {
      opciones.classList.add("d-none");
    }
    if (!propagacionActiva) {
      mostrarLeyendaEstados(false);
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
    var xEtiquetaP = Math.min(maxTChart * vp * 0.82, maxKm * 0.9);
    var yEtiquetaP = xEtiquetaP / vp;
    var xEtiquetaS = Math.min(maxTChart * vs * 0.72, maxKm * 0.9);
    var yEtiquetaS = xEtiquetaS / vs;
    var tiempoActual = propagacionActiva ? propagacionTiempo : 0;
    var trazas = [
      {
        type: "scatter",
        mode: "lines",
        name: "Referencia P (" + vp.toFixed(1) + " km/s)",
        x: [0, maxKm],
        y: [0, maxKm / vp],
        line: { color: "#4c6ef5", dash: "dash", width: 1.5 },
        hoverinfo: "skip",
      },
      {
        type: "scatter",
        mode: "lines",
        name: "Referencia S (" + vs.toFixed(1) + " km/s)",
        x: [0, maxKm],
        y: [0, maxKm / vs],
        line: { color: "#f08c00", dash: "dot", width: 1.5 },
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
        annotations: [
          {
            x: xEtiquetaP,
            y: yEtiquetaP,
            text: "P",
            showarrow: false,
            xanchor: "center",
            yanchor: "bottom",
            font: { color: "#4c6ef5", size: 12 },
            bgcolor: "rgba(255,255,255,0.85)",
            borderpad: 1,
          },
          {
            x: xEtiquetaS,
            y: yEtiquetaS,
            text: "S",
            showarrow: false,
            xanchor: "center",
            yanchor: "top",
            font: { color: "#f08c00", size: 12 },
            bgcolor: "rgba(255,255,255,0.85)",
            borderpad: 1,
          },
        ],
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
    var mostrarP = document.getElementById("propagacion-mostrar-p");
    if (mostrarP) {
      mostrarP.addEventListener("change", function () {
        propagacionMostrarP = mostrarP.checked;
        actualizarPropagacion();
      });
    }
    var mostrarS = document.getElementById("propagacion-mostrar-s");
    if (mostrarS) {
      mostrarS.addEventListener("change", function () {
        propagacionMostrarS = mostrarS.checked;
        actualizarPropagacion();
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
    document.addEventListener("rcs:perfil-redibujado", function () {
      if (mapaEstacionesActivo) {
        dibujarMapaEstaciones();
      } else if (propagacionActiva) {
        actualizarPropagacion();
      }
    });
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
