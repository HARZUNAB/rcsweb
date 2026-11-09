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
    if (!aviso) {
      return;
    }
    aviso.className = "alert small py-2 " + (clase || "alert-light border");
    aviso.textContent = texto;
    aviso.classList.remove("d-none");
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
    var boton = document.getElementById("btn-disponibilidad");
    if (boton) {
      boton.disabled = false;
    }
    var botonTodas = document.getElementById("btn-disponibilidad-todas");
    if (botonTodas) {
      botonTodas.disabled = false;
    }
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
    var todasMapa = document.getElementById("mapa-estaciones-todas");
    if (todasMapa) {
      todasMapa.addEventListener("change", function () {
        if (mapaEstacionesActivo) {
          dibujarMapaEstaciones();
        }
      });
    }
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
    var boton = document.getElementById("btn-disponibilidad");
    if (boton) {
      boton.disabled = true;
    }
    var botonTodas = document.getElementById("btn-disponibilidad-todas");
    if (botonTodas) {
      botonTodas.disabled = true;
    }
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
    var puntos = datos.filter(function (punto) {
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
      puntos = puntos.slice(0, 20);
    }
    return puntos;
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
  }

  function alternarMapaEstaciones() {
    if (!mapaEstacionesActivo) {
      mapaEstacionesActivo = true;
      dibujarMapaEstaciones();
      var mapa = document.getElementById("mapa-detalle");
      if (mapa) {
        mapa.scrollIntoView({ behavior: "smooth", block: "center" });
      }
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
    if (opciones) {
      opciones.classList.add("d-none");
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
    var estaciones = (datos.estaciones || [])
      .filter(function (estacion) {
        return Number.isFinite(Number(estacion.distancia_km));
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
    var trazas = [
      {
        type: "scatter",
        mode: "lines",
        name: "P estimada (" + vp.toFixed(1) + " km/s)",
        x: [0, maxKm],
        y: [0, maxKm / vp],
        line: { color: "#1f77b4", dash: "dash" },
        hoverinfo: "skip",
      },
      {
        type: "scatter",
        mode: "lines",
        name: "S estimada (" + vs.toFixed(1) + " km/s)",
        x: [0, maxKm],
        y: [0, maxKm / vs],
        line: { color: "#ff7f0e", dash: "dash" },
        hoverinfo: "skip",
      },
      {
        type: "scatter",
        mode: "markers",
        name: "Picks reales",
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
          size: 8,
          color: arribos.map(function (arribo) {
            var fase = (arribo.fase || "").toUpperCase();
            if (fase.startsWith("P")) {
              return "#1f77b4";
            }
            if (fase.startsWith("S")) {
              return "#ff7f0e";
            }
            return "#6c757d";
          }),
          symbol: arribos.map(function (arribo) {
            return (arribo.modo || "").toLowerCase() === "manual"
              ? "circle"
              : "diamond";
          }),
          line: { color: "#ffffff", width: 0.5 },
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
          size: 6,
          color: "#adb5bd",
          symbol: "circle-open",
        },
        hovertemplate: "%{text}<br>P estimada · %{y:.1f} s<extra></extra>",
      });
    }
    window.Plotly.newPlot(
      contenedorGrafico,
      trazas,
      {
        margin: { l: 60, r: 20, t: 20, b: 55 },
        xaxis: { title: "Distancia (km)" },
        yaxis: { title: "Tiempo desde el origen (s)" },
        hovermode: "closest",
        legend: { orientation: "h" },
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

  function iniciarPanel() {
    panel = document.getElementById("panel-sin-arribos");
    contenedor = document.getElementById("panel-sin-arribos-contenido");
    if (!panel || !contenedor) {
      return;
    }
    iniciarModalStreams();
    iniciarFiltrosSinArribos();
    panel.addEventListener("click", function (evento) {
      var botonMapa = evento.target.closest("#btn-estaciones-mapa");
      if (botonMapa) {
        evento.preventDefault();
        alternarMapaEstaciones();
        return;
      }
      var botonTiempos = evento.target.closest("#btn-tiempos-llegada");
      if (botonTiempos) {
        evento.preventDefault();
        abrirTiemposLlegada();
        return;
      }
      var botonActualizar = evento.target.closest("#btn-tiempos-actualizar");
      if (botonActualizar) {
        evento.preventDefault();
        dibujarTiemposLlegada();
        return;
      }
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
    iniciarPanel();
  });
})();
