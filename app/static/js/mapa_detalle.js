// Mapa interactivo del detalle: Leaflet online y Plotly offline/perfil.
(function () {
  "use strict";

  const datos = document.getElementById("mapa-datos");
  const contenedor = document.getElementById("mapa-detalle");
  const perfil = document.getElementById("perfil-detalle");
  const panelContenido = document.getElementById("detalle-evento-contenido");
  const cerrarDetalle = document.getElementById("cerrar-detalle-evento");
  if (!datos || !contenedor) {
    return;
  }

  let puntos = [];
  try {
    puntos = JSON.parse(datos.textContent || "[]");
  } catch (error) {
    puntos = [];
  }
  if (!puntos.length) {
    return;
  }

  let seleccionado = null;
  let temporizadorPrevio = null;
  const TEXTO_SIN_SELECCION =
    '<div class="small text-secondary">' +
    "Pase el cursor por un evento para previsualizarlo; " +
    "haga clic para fijarlo." +
    "</div>";

  const perfilDatosEl = document.getElementById("perfil-datos");
  let perfilDatos = null;
  try {
    perfilDatos = perfilDatosEl ? JSON.parse(perfilDatosEl.textContent || "null") : null;
  } catch (error) {
    perfilDatos = null;
  }

  const historicoEl = document.getElementById("historico-datos");
  let historicoDatos = null;
  try {
    historicoDatos = historicoEl ? JSON.parse(historicoEl.textContent || "null") : null;
  } catch (error) {
    historicoDatos = null;
  }

  const modo = contenedor.dataset.modo || "offline";
  const aviso = document.getElementById("mapa-aviso");
  const avisoLink = document.getElementById("mapa-aviso-link");

  // Vista inicial de la planta: si el evento o el grupo están muy
  // concentrados, se abre con contexto regional en vez de zoom de ciudad.
  const ZOOM_INICIAL_MAX = 7;
  const SPAN_MIN_LON = 8.0;
  const SPAN_MIN_LAT = 3.0;
  const SPAN_MIN_LAT_PLOTLY = 5.0;
  const FACTOR_SPAN = 1.2;

  const historicoCheck = document.getElementById("mostrar-historico");
  const historicoLabel = document.getElementById("historico-label");
  const historicoTexto = document.getElementById("historico-texto");
  const enlaceModo = document.getElementById("enlace-mapa-modo");
  const urlHistorico = contenedor.dataset.urlHistorico || "";
  let historicoCache = historicoDatos;
  let historicoActivo = !!(historicoCheck && historicoCheck.checked);

  function esc(valor) {
    return String(valor === null || valor === undefined ? "" : valor).replace(
      /[&<>"']/g,
      function (caracter) {
        return {
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[caracter];
      }
    );
  }

  function valor(valor, sufijo) {
    if (valor === null || valor === undefined || valor === "") {
      return "—";
    }
    return esc(valor) + (sufijo || "");
  }

  function detalleHtml(punto) {
    const filas = [
      ["Fecha", valor(punto.fecha)],
      ["Fuente", valor(punto.etiqueta)],
      ["Latitud", valor(punto.lat, "°")],
      ["Longitud", valor(punto.lon, "°")],
      ["Profundidad", valor(punto.prof, " km")],
      ["Magnitud", valor(punto.mag)],
      ["Tipo mag.", valor(punto.tipo)],
      [punto.analista_etiqueta || "Analista", valor(punto.analista)],
    ];
    if (punto.comparacion) {
      filas.push([
        "Distancia",
        punto.referencia
          ? "0 km (referencia)"
          : valor(punto.dist_km, " km"),
      ]);
    }
    filas.push(
      ["Frontera", valor(punto.frontera)],
      ["Sospechoso", punto.sospechoso ? "Sí" : ""],
      ["Estado", valor(punto.estado)],
    );
    let html = '<div class="small"><dl class="row mb-0 g-0">';
    filas.forEach(function (fila) {
      if (fila[1] === "—") {
        return;
      }
      html +=
        '<dt class="col-5 fw-normal text-secondary">' +
        fila[0] +
        '</dt><dd class="col-7 mb-1">' +
        fila[1] +
        "</dd>";
    });
    html += "</dl>";
    if (punto.url) {
      html +=
        '<a class="btn btn-sm btn-outline-primary mt-2" href="' +
        esc(punto.url) +
        '">Abrir detalle</a>';
    }
    return html + "</div>";
  }

  function mostrarSeleccion(punto, ancla) {
    if (panelContenido) {
      panelContenido.innerHTML = detalleHtml(punto);
      return;
    }
    if (!window.RCSVineta) {
      return;
    }
    window.RCSVineta.mostrar(detalleHtml(punto), {
      ancla: ancla,
      evitar: [contenedor, perfil].filter(Boolean),
    });
  }

  // El panel fijo recibe la vista previa sin abrir etiquetas flotantes que
  // tapen los marcadores vecinos.
  function mostrarPrevio(punto) {
    if (!panelContenido || !punto) {
      return;
    }
    window.clearTimeout(temporizadorPrevio);
    temporizadorPrevio = null;
    panelContenido.innerHTML = detalleHtml(punto);
  }

  function restaurarPrevio() {
    if (!panelContenido) {
      return;
    }
    window.clearTimeout(temporizadorPrevio);
    temporizadorPrevio = window.setTimeout(function () {
      temporizadorPrevio = null;
      panelContenido.innerHTML = seleccionado
        ? detalleHtml(seleccionado)
        : TEXTO_SIN_SELECCION;
    }, 60);
  }

  let plantaTipo = "plotly";
  let marcadoresLeaflet = [];
  let perfilEventos = [];
  let perfilTrazaIdx = null;

  const urlRegiones = contenedor.dataset.urlRegiones || "";
  let regionesChile = null;

  function dibujarRegiones() {
    if (
      plantaTipo !== "plotly" ||
      !regionesChile ||
      !window.RCSRegiones
    ) {
      return;
    }
    window.RCSRegiones.dibujar(contenedor, regionesChile, {
      contorno_color: "#1f3a5f",
      contorno_ancho: "1.8",
      regiones_color: "#52606d",
      regiones_ancho: "1.2",
      regiones_dash: "4 2",
    });
  }

  function programarRegiones() {
    window.requestAnimationFrame(dibujarRegiones);
  }

  function cargarRegiones() {
    if (!urlRegiones || !window.RCSRegiones || regionesChile) {
      return;
    }
    window.RCSRegiones.cargar(urlRegiones).then(function (datos) {
      regionesChile = datos;
      programarRegiones();
    });
  }

  function claveDe(punto) {
    if (punto && punto.clave) {
      return punto.clave;
    }
    function numero(valor, decimales) {
      if (valor === null || valor === undefined || valor === "") {
        return "";
      }
      const convertido = Number(valor);
      return Number.isFinite(convertido) ? convertido.toFixed(decimales) : "";
    }
    return [
      punto && punto.fuente ? punto.fuente : "",
      numero(punto && punto.lat, 5),
      numero(punto && punto.lon, 5),
      numero(punto && punto.prof, 1),
    ].join("|");
  }

  function buscarIndice(lista, punto) {
    const clave = claveDe(punto);
    for (let i = 0; i < lista.length; i += 1) {
      if (claveDe(lista[i]) === clave) {
        return i;
      }
    }
    if (punto && punto.url) {
      for (let i = 0; i < lista.length; i += 1) {
        if (lista[i].url && lista[i].url === punto.url) {
          return i;
        }
      }
    }
    return -1;
  }

  // Paleta del proyecto base: amarillo local/no percibido, rojo si la fuente
  // percibido, blanco/negro para publicado, violeta para sospechoso.
  function colorPunto(punto) {
    if (punto.color) {
      return punto.color;
    }
    if (punto.rol === "publicado") {
      return "#ffffff";
    }
    return "#ffff00";
  }

  function bordePunto(punto) {
    if (punto.rol === "publicado") {
      return { color: "#000000", width: 2 };
    }
    if (punto.sospechoso) {
      return { color: "#7b1196", width: 3 };
    }
    return { color: "#000000", width: 1.2 };
  }

  // Superposición: misma ubicación redondeada y fuentes distintas. Se dibuja
  // como un aro magenta independiente de los marcadores de eventos.
  function claveSuperpuesto(punto, enPerfil) {
    if (enPerfil) {
      if (
        punto.along_km === null ||
        punto.along_km === undefined ||
        punto.prof === null ||
        punto.prof === undefined
      ) {
        return null;
      }
      return (
        Number(punto.along_km).toFixed(1) +
        "|" +
        Number(punto.prof).toFixed(1)
      );
    }
    return (
      Number(punto.lat).toFixed(3) + "|" + Number(punto.lon).toFixed(3)
    );
  }

  function trazaSuperpuestos(lista, enPerfil) {
    const grupos = new Map();
    lista.forEach(function (punto) {
      const clave = claveSuperpuesto(punto, enPerfil);
      if (clave === null) {
        return;
      }
      if (!grupos.has(clave)) {
        grupos.set(clave, new Set());
      }
      grupos.get(clave).add(punto.fuente || "");
    });
    const marcados = lista.filter(function (punto) {
      const clave = claveSuperpuesto(punto, enPerfil);
      const fuentes = clave === null ? null : grupos.get(clave);
      return fuentes && fuentes.size > 1;
    });
    if (!marcados.length) {
      return null;
    }
    const traza = {
      type: enPerfil ? "scatter" : "scattergeo",
      mode: "markers",
      marker: {
        size: 18,
        color: "rgba(0,0,0,0)",
        line: { color: "#ff00ff", width: 2 },
      },
      hoverinfo: "skip",
      showlegend: false,
      name: "Soluciones superpuestas",
    };
    if (enPerfil) {
      traza.x = marcados.map(function (punto) {
        return punto.along_km;
      });
      traza.y = marcados.map(function (punto) {
        return -punto.prof;
      });
    } else {
      traza.lon = marcados.map(function (punto) {
        return punto.lon;
      });
      traza.lat = marcados.map(function (punto) {
        return punto.lat;
      });
    }
    return traza;
  }

  function resaltarPlanta(indice) {
    if (plantaTipo === "leaflet") {
      marcadoresLeaflet.forEach(function (marcador, i) {
        const punto = puntos[i] || {};
        const elegido = i === indice;
        const borde = bordePunto(punto);
        marcador.setStyle({
          radius: elegido ? 12 : 8,
          weight: elegido ? 2.5 : borde.width,
          color: elegido ? "#000080" : borde.color,
        });
      });
      return;
    }
    if (!window.Plotly || !contenedor || !contenedor.data) {
      return;
    }
    const tamanios = puntos.map(function (_punto, i) {
      return i === indice ? 15 : 11;
    });
    const anchos = puntos.map(function (punto, i) {
      return i === indice ? 2.5 : bordePunto(punto).width;
    });
    const colores = puntos.map(function (punto, i) {
      return i === indice ? "#000080" : bordePunto(punto).color;
    });
    window.Plotly.restyle(
      contenedor,
      {
        "marker.size": [tamanios],
        "marker.line.width": [anchos],
        "marker.line.color": [colores],
      },
      [0]
    );
  }

  function resaltarPerfil(indice) {
    if (!perfilEventos.length || perfilTrazaIdx === null ||
        !window.Plotly || !perfil || !perfil.data) {
      return;
    }
    const tamanios = perfilEventos.map(function (_punto, i) {
      return i === indice ? 15 : 11;
    });
    const anchos = perfilEventos.map(function (punto, i) {
      return i === indice ? 2.5 : bordePunto(punto).width;
    });
    const colores = perfilEventos.map(function (punto, i) {
      return i === indice ? "#000080" : bordePunto(punto).color;
    });
    window.Plotly.restyle(
      perfil,
      {
        "marker.size": [tamanios],
        "marker.line.width": [anchos],
        "marker.line.color": [colores],
      },
      [perfilTrazaIdx]
    );
  }

  function seleccionar(punto, ancla) {
    if (!punto) {
      return;
    }
    seleccionado = punto;
    window.clearTimeout(temporizadorPrevio);
    temporizadorPrevio = null;
    mostrarSeleccion(punto, ancla);
    resaltarPlanta(buscarIndice(puntos, punto));
    resaltarPerfil(buscarIndice(perfilEventos, punto));
  }

  function limpiarSeleccion() {
    seleccionado = null;
    window.clearTimeout(temporizadorPrevio);
    temporizadorPrevio = null;
    resaltarPlanta(-1);
    resaltarPerfil(-1);
    if (panelContenido) {
      panelContenido.innerHTML = TEXTO_SIN_SELECCION;
    }
    if (window.RCSVineta) {
      window.RCSVineta.ocultar();
    }
  }

  if (cerrarDetalle) {
    cerrarDetalle.addEventListener("click", limpiarSeleccion);
  }
  document.addEventListener("rcs:vineta-cerrada", limpiarSeleccion);

  function anclaDeEvento(evento, nodo) {
    if (evento && evento.event &&
        Number.isFinite(evento.event.clientX) &&
        Number.isFinite(evento.event.clientY)) {
      return { x: evento.event.clientX, y: evento.event.clientY };
    }
    if (window.RCSVineta) {
      return window.RCSVineta.anclaDeNodo(nodo || contenedor);
    }
    return null;
  }

  function mostrarAvisoOffline() {
    if (aviso) {
      aviso.classList.remove("d-none");
    }
    if (avisoLink && contenedor.dataset.offlineUrl) {
      avisoLink.href = contenedor.dataset.offlineUrl;
    }
  }

  function rangoConMargen(minimo, maximo, margenMinimo, porcentaje) {
    if (minimo === undefined || maximo === undefined) {
      return undefined;
    }
    const margen = Math.max(
      margenMinimo,
      Math.abs(maximo - minimo) * porcentaje
    );
    return [minimo - margen, maximo + margen];
  }

  function dibujarPerfilCompleto(datos) {
    const eventos = (datos.eventos || []).filter(function (evento) {
      return evento.along_km !== null && evento.along_km !== undefined &&
        evento.prof !== null && evento.prof !== undefined;
    });
    if (!window.Plotly || !perfil) {
      return;
    }
    const trazas = [];
    const historicoPerfil = historicoDatos && historicoDatos.perfil;
    if (historicoPerfil && (historicoPerfil.along || []).length) {
      trazas.push({
        type: "scatter",
        mode: "markers",
        x: historicoPerfil.along,
        y: historicoPerfil.prof,
        marker: { size: 3, color: "#8c8c8c", opacity: 0.35 },
        hoverinfo: "skip",
        showlegend: false,
        name: "Sismicidad histórica",
      });
    }
    if ((datos.topo_p || []).length) {
      trazas.push({
        type: "scatter",
        mode: "lines",
        x: datos.topo_p,
        y: (datos.topo_alt || []).map(function (valor) {
          return valor === null || valor === undefined ? null : valor / 1000.0;
        }),
        line: { color: "#b8a37a", width: 1 },
        fill: "tozeroy",
        fillcolor: "rgba(232, 220, 194, 0.55)",
        hoverinfo: "skip",
        name: "Topografía",
      });
    }
    if ((datos.slab_p || []).length) {
      trazas.push({
        type: "scatter",
        mode: "lines",
        x: datos.slab_p,
        y: (datos.slab_depth || []).map(function (valor) {
          return valor === null || valor === undefined ? null : -valor;
        }),
        line: { color: "#1f1f1f", width: 2 },
        hoverinfo: "skip",
        name: "Slab",
      });
    }
    perfilEventos = eventos;
    perfilTrazaIdx = trazas.length;
    trazas.push({
      type: "scatter",
      mode: "markers",
      x: eventos.map(function (evento) {
        return evento.along_km;
      }),
      y: eventos.map(function (evento) {
        return -evento.prof;
      }),
      text: eventos.map(function (evento) {
        return evento.etiqueta + " · " + evento.fecha;
      }),
      customdata: eventos,
      marker: {
        size: 11,
        color: eventos.map(colorPunto),
        line: {
          color: eventos.map(function (evento) {
            return bordePunto(evento).color;
          }),
          width: eventos.map(function (evento) {
            return bordePunto(evento).width;
          }),
        },
      },
      hoverinfo: "none",
      name: "Eventos",
    });
    const superpuestosPerfil = trazaSuperpuestos(eventos, true);
    if (superpuestosPerfil) {
      trazas.push(superpuestosPerfil);
    }
    const xs = [];
    const ys = [];
    (datos.topo_p || []).concat(datos.slab_p || []).concat(
      eventos.map(function (evento) { return evento.along_km; })
    ).forEach(function (valor) {
      if (typeof valor === "number" && Number.isFinite(valor)) xs.push(valor);
    });
    (datos.topo_alt || []).forEach(function (valor) {
      if (typeof valor === "number" && Number.isFinite(valor)) ys.push(valor / 1000.0);
    });
    (datos.slab_depth || []).forEach(function (valor) {
      if (typeof valor === "number" && Number.isFinite(valor)) ys.push(-valor);
    });
    eventos.forEach(function (evento) { ys.push(-evento.prof); });
    // La capa histórica no participa del rango: si sus profundidades entraran
    // en el mínimo/máximo, el perfil se achataba al activar la casilla.
    const xMin = xs.length ? Math.min.apply(null, xs) : undefined;
    const xMax = xs.length ? Math.max.apply(null, xs) : undefined;
    const yMin = ys.length ? Math.min.apply(null, ys) : undefined;
    const yMax = ys.length ? Math.max.apply(null, ys) : undefined;
    const layout = {
      margin: { l: 60, r: 15, t: 15, b: 45 },
      xaxis: {
        title: "Distancia a lo largo del perfil (km)",
        range: rangoConMargen(xMin, xMax, 10, 0.03),
        zeroline: false,
      },
      yaxis: {
        title: "Elevación / Profundidad (km)",
        range: rangoConMargen(yMin, yMax, 8, 0.08),
        zeroline: true,
      },
      shapes: [{
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        y0: 0,
        y1: 0,
        line: { color: "#adb5bd", width: 1, dash: "dot" },
      }],
      showlegend: false,
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      uirevision: datos.id || "perfil",
    };
    window.Plotly.newPlot(perfil, trazas, layout, {
      responsive: true,
      displaylogo: false,
    }).then(function () {
      perfil.on("plotly_click", function (evento) {
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== perfilTrazaIdx) {
          return;
        }
        const punto = seleccion.customdata;
        if (punto) {
          seleccionar(punto, anclaDeEvento(evento, perfil));
        }
      });
      perfil.on("plotly_hover", function (evento) {
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== perfilTrazaIdx) {
          return;
        }
        const punto = seleccion.customdata;
        if (punto) {
          mostrarPrevio(punto);
        }
      });
      perfil.on("plotly_unhover", restaurarPrevio);
    });
  }

  function actualizarEtiquetaHistorico(datos, error) {
    if (!historicoLabel || !historicoTexto) {
      return;
    }
    if (error) {
      historicoTexto.textContent = error;
      historicoLabel.classList.remove("d-none", "text-secondary");
      historicoLabel.classList.add("text-danger");
      return;
    }
    if (datos && datos.label) {
      const total = (datos.perfil && datos.perfil.total) || 0;
      historicoTexto.textContent =
        datos.label + " · " + total + " puntos";
      historicoLabel.classList.remove("d-none", "text-danger");
      historicoLabel.classList.add("text-secondary");
      return;
    }
    historicoTexto.textContent = "";
    historicoLabel.classList.add("d-none");
    historicoLabel.classList.remove("text-danger");
    historicoLabel.classList.add("text-secondary");
  }

  function actualizarUrlHistorico(activo) {
    const url = new URL(window.location.href);
    if (activo) {
      url.searchParams.set("historico", "1");
    } else {
      url.searchParams.delete("historico");
    }
    window.history.replaceState(null, "", url.toString());
  }

  function actualizarEnlaceModo() {
    if (!enlaceModo) {
      return;
    }
    const base = modo === "online"
      ? contenedor.dataset.offlineUrl
      : contenedor.dataset.onlineUrl;
    if (!base) {
      return;
    }
    const url = new URL(base, window.location.origin);
    if (historicoActivo) {
      url.searchParams.set("historico", "1");
    } else {
      url.searchParams.delete("historico");
    }
    enlaceModo.href = url.pathname + url.search;
  }

  function aplicarHistorico(datos) {
    historicoDatos = datos;
    historicoActivo = !!datos;
    if (historicoCheck) {
      historicoCheck.checked = historicoActivo;
    }
    actualizarEtiquetaHistorico(datos);
    actualizarUrlHistorico(historicoActivo);
    actualizarEnlaceModo();
    if (perfilDatos) {
      dibujarPerfilCompleto(perfilDatos);
    }
  }

  function cargarHistorico() {
    if (!historicoCheck) {
      return;
    }
    // Sin perfil o sin endpoint utilizable se conserva el envío del formulario.
    if (!perfilDatos || !perfilDatos.id || !urlHistorico) {
      if (historicoCheck.form) {
        historicoCheck.form.submit();
      }
      return;
    }
    if (!historicoCheck.checked) {
      aplicarHistorico(null);
      return;
    }
    if (historicoCache) {
      aplicarHistorico(historicoCache);
      return;
    }
    historicoCheck.disabled = true;
    fetch(
      urlHistorico.replace("__PERFIL__", encodeURIComponent(perfilDatos.id)),
      { headers: { Accept: "application/json" } }
    )
      .then(function (respuesta) {
        if (!respuesta.ok) {
          throw new Error("historico");
        }
        return respuesta.json();
      })
      .then(function (datos) {
        historicoCache = datos;
        aplicarHistorico(datos);
      })
      .catch(function () {
        historicoCheck.checked = false;
        historicoActivo = false;
        actualizarEtiquetaHistorico(
          null,
          "No se pudo cargar la sismicidad histórica."
        );
        actualizarUrlHistorico(false);
        actualizarEnlaceModo();
      })
      .finally(function () {
        historicoCheck.disabled = false;
      });
  }

  function dibujarPerfil() {
    if (!perfil || !perfilDatos) {
      // Sin perfil asignado: el template muestra "Perfil no disponible".
      return;
    }
    dibujarPerfilCompleto(perfilDatos);
  }

  function dibujarPlotly() {
    plantaTipo = "plotly";
    if (!window.Plotly) {
      contenedor.innerHTML =
        '<div class="text-secondary small p-3">No se pudo cargar el mapa offline.</div>';
      return;
    }
    const trazas = [];
    const traza = {
      type: "scattergeo",
      mode: "markers",
      lat: puntos.map(function (punto) {
        return punto.lat;
      }),
      lon: puntos.map(function (punto) {
        return punto.lon;
      }),
      text: puntos.map(function (punto) {
        return punto.etiqueta + " · " + punto.fecha;
      }),
      customdata: puntos,
      marker: {
        size: 11,
        color: puntos.map(colorPunto),
        line: {
          color: puntos.map(function (punto) {
            return bordePunto(punto).color;
          }),
          width: puntos.map(function (punto) {
            return bordePunto(punto).width;
          }),
        },
      },
      hoverinfo: "none",
    };
    trazas.push(traza);
    const superpuestosMapa = trazaSuperpuestos(puntos, false);
    if (superpuestosMapa) {
      trazas.push(superpuestosMapa);
    }
    const latitudes = puntos.map(function (punto) { return punto.lat; });
    const longitudes = puntos.map(function (punto) { return punto.lon; });
    const latMin = Math.min.apply(null, latitudes);
    const latMax = Math.max.apply(null, latitudes);
    const lonMin = Math.min.apply(null, longitudes);
    const lonMax = Math.max.apply(null, longitudes);
    const latSpan = Math.max(
      (latMax - latMin) * FACTOR_SPAN,
      SPAN_MIN_LAT_PLOTLY
    );
    const lonSpan = Math.max(
      (lonMax - lonMin) * FACTOR_SPAN,
      SPAN_MIN_LON
    );
    const latCentro = (latMin + latMax) / 2;
    const lonCentro = (lonMin + lonMax) / 2;
    const layout = {
      margin: { l: 0, r: 0, t: 0, b: 0 },
      geo: {
        showland: true,
        landcolor: "#f1f3f5",
        showcountries: true,
        countrycolor: "#ced4da",
        showcoastlines: true,
        coastlinecolor: "#adb5bd",
        projection: { type: "mercator" },
        lonaxis: { range: [lonCentro - lonSpan / 2, lonCentro + lonSpan / 2] },
        lataxis: { range: [latCentro - latSpan / 2, latCentro + latSpan / 2] },
      },
      showlegend: false,
      paper_bgcolor: "#ffffff",
    };
    window.Plotly.newPlot(contenedor, trazas, layout, {
      responsive: true,
      displaylogo: false,
      scrollZoom: true,
      topojsonURL: contenedor.dataset.topojsonUrl || undefined,
    }).then(function () {
      cargarRegiones();
      programarRegiones();
      if (!contenedor._regionesEventos) {
        contenedor._regionesEventos = true;
        contenedor.on("plotly_relayout", programarRegiones);
        contenedor.on("plotly_afterplot", programarRegiones);
        window.addEventListener("resize", programarRegiones);
      }
      contenedor.on("plotly_click", function (evento) {
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== 0) {
          return;
        }
        const punto = seleccion.customdata;
        if (punto) {
          seleccionar(punto, anclaDeEvento(evento, contenedor));
        }
      });
      contenedor.on("plotly_hover", function (evento) {
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== 0) {
          return;
        }
        const punto = seleccion.customdata;
        if (punto) {
          mostrarPrevio(punto);
        }
      });
      contenedor.on("plotly_unhover", restaurarPrevio);
    });

    window.RCSMapaDetalle = {
      tipo: "plotly",
      mostrarEstaciones: function (puntos) {
        if (!window.Plotly || !puntos || !puntos.length) {
          return;
        }
        window.RCSMapaDetalle.ocultarEstaciones();
        const grupos = {
          "Arribos P": [],
          "Arribos S": [],
          "Arribos otras": [],
          "Sin arribos": [],
        };
        puntos.forEach(function (punto) {
          if (!Number.isFinite(punto.lat) || !Number.isFinite(punto.lon)) {
            return;
          }
          if (punto.tipo === "arribo") {
            const fase = (punto.fase || "").toUpperCase();
            if (fase.startsWith("P")) {
              grupos["Arribos P"].push(punto);
            } else if (fase.startsWith("S")) {
              grupos["Arribos S"].push(punto);
            } else {
              grupos["Arribos otras"].push(punto);
            }
          } else {
            grupos["Sin arribos"].push(punto);
          }
        });
        const colores = {
          "Arribos P": "#1f77b4",
          "Arribos S": "#ff7f0e",
          "Arribos otras": "#6c757d",
          "Sin arribos": "#9a6a00",
        };
        const trazas = [];
        Object.keys(grupos).forEach(function (nombre) {
          const lista = grupos[nombre];
          if (!lista.length) {
            return;
          }
          const esSinArribos = nombre === "Sin arribos";
          trazas.push({
            type: "scattergeo",
            mode: "markers",
            name: "Estaciones · " + nombre,
            lat: lista.map(function (punto) {
              return punto.lat;
            }),
            lon: lista.map(function (punto) {
              return punto.lon;
            }),
            text: lista.map(function (punto) {
              const base =
                (punto.red || "") + " " + (punto.estacion || "");
              if (esSinArribos) {
                return base;
              }
              const fases = (punto.fases || [])
                .map(function (fase) {
                  let texto = fase.fase || "";
                  if (fase.segundos != null) {
                    texto += " " + Number(fase.segundos).toFixed(1) + " s";
                  }
                  if (fase.modo) {
                    texto += " · " + fase.modo;
                  }
                  return texto.trim();
                })
                .filter(function (texto) {
                  return texto !== "";
                });
              return fases.length
                ? base + "<br>" + fases.join("<br>")
                : base;
            }),
            customdata: lista,
            marker: {
              size: esSinArribos ? 5 : 7,
              color: esSinArribos
                ? lista.map(function (punto) {
                    if (punto.categoria === "verificado") {
                      return "#1a7f37";
                    }
                    if (punto.categoria === "indicio") {
                      return "#9a6a00";
                    }
                    return "#6c757d";
                  })
                : colores[nombre],
              symbol: esSinArribos ? "circle" : "diamond",
              line: { color: "#ffffff", width: 0.5 },
            },
            hoverinfo: "text",
          });
        });
        if (trazas.length) {
          window.Plotly.addTraces(contenedor, trazas);
        }
      },
      ocultarEstaciones: function () {
        if (!window.Plotly || !contenedor || !contenedor.data) {
          return;
        }
        const indices = [];
        contenedor.data.forEach(function (traza, indice) {
          if ((traza.name || "").indexOf("Estaciones ·") === 0) {
            indices.push(indice);
          }
        });
        if (indices.length) {
          window.Plotly.deleteTraces(contenedor, indices);
        }
      },
    };
  }

  function limitesIniciales(coordenadas) {
    const validas = coordenadas.filter(function (punto) {
      return Number.isFinite(punto[0]) && Number.isFinite(punto[1]);
    });
    if (!validas.length) {
      return null;
    }
    const latitudes = validas.map(function (punto) {
      return punto[0];
    });
    const longitudes = validas.map(function (punto) {
      return punto[1];
    });
    const latMin = Math.min.apply(null, latitudes);
    const latMax = Math.max.apply(null, latitudes);
    const lonMin = Math.min.apply(null, longitudes);
    const lonMax = Math.max.apply(null, longitudes);
    const latSpan = Math.max((latMax - latMin) * FACTOR_SPAN, SPAN_MIN_LAT);
    const lonSpan = Math.max((lonMax - lonMin) * FACTOR_SPAN, SPAN_MIN_LON);
    const latCentro = (latMin + latMax) / 2;
    const lonCentro = (lonMin + lonMax) / 2;
    return [
      [latCentro - latSpan / 2, lonCentro - lonSpan / 2],
      [latCentro + latSpan / 2, lonCentro + lonSpan / 2],
    ];
  }

  function dibujarLeaflet() {
    plantaTipo = "leaflet";
    marcadoresLeaflet = [];
    if (window.RCSRegiones) {
      window.RCSRegiones.ocultar(contenedor);
    }
    if (!window.L) {
      dibujarPlotly();
      return;
    }
    const mapa = window.L.map(contenedor, {
      scrollWheelZoom: true,
    });
    const capa = window.L.tileLayer(
      "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap",
      }
    ).addTo(mapa);
    let errores = 0;
    capa.on("tileerror", function () {
      errores += 1;
      if (errores >= 2) {
        mostrarAvisoOffline();
      }
    });
    const coordenadas = [];
    puntos.forEach(function (punto) {
      const borde = bordePunto(punto);
      const marcador = window.L.circleMarker([punto.lat, punto.lon], {
        radius: 8,
        color: borde.color,
        fillColor: colorPunto(punto),
        fillOpacity: 0.85,
        weight: borde.width,
      }).addTo(mapa);
      // El hover actualiza el panel fijo, sin tooltip pegado al cursor.
      marcador.on("mouseover", function () {
        mostrarPrevio(punto);
      });
      marcador.on("mouseout", restaurarPrevio);
      marcador.on("click", function (evento) {
        const original = evento.originalEvent;
        let ancla = null;
        if (original && Number.isFinite(original.clientX) &&
            Number.isFinite(original.clientY)) {
          ancla = { x: original.clientX, y: original.clientY };
        } else if (window.RCSVineta) {
          ancla = window.RCSVineta.anclaDeNodo(contenedor);
        }
        seleccionar(punto, ancla);
      });
      marcadoresLeaflet.push(marcador);
      coordenadas.push([punto.lat, punto.lon]);
    });
    const limites = limitesIniciales(coordenadas);
    if (limites) {
      mapa.fitBounds(limites, { padding: [30, 30], animate: false });
      // En mapas anchos un área mínima puede elegir un zoom mayor; se limita
      // para que el evento siempre se ubique en un contexto regional.
      if (mapa.getZoom() > ZOOM_INICIAL_MAX) {
        mapa.setZoom(ZOOM_INICIAL_MAX, { animate: false });
      }
    }

    let capaEstaciones = null;
    window.RCSMapaDetalle = {
      tipo: "leaflet",
      mostrarEstaciones: function (puntos) {
        if (capaEstaciones) {
          mapa.removeLayer(capaEstaciones);
          capaEstaciones = null;
        }
        if (!puntos || !puntos.length) {
          return;
        }
        capaEstaciones = window.L.layerGroup();
        puntos.forEach(function (punto) {
          if (!Number.isFinite(punto.lat) || !Number.isFinite(punto.lon)) {
            return;
          }
          const esArribo = punto.tipo === "arribo";
          let color = "#6c757d";
          if (esArribo) {
            const fase = (punto.fase || "").toUpperCase();
            if (fase.startsWith("P")) {
              color = "#1f77b4";
            } else if (fase.startsWith("S")) {
              color = "#ff7f0e";
            }
          } else if (punto.categoria === "verificado") {
            color = "#1a7f37";
          } else if (punto.categoria === "indicio") {
            color = "#9a6a00";
          }
          const marcador = window.L.circleMarker([punto.lat, punto.lon], {
            radius: esArribo ? 5 : 4,
            color: color,
            fillColor: color,
            fillOpacity: 0.85,
            weight: 1,
          });
          const partes = [
            "<strong>" +
              esc((punto.red || "") + " " + (punto.estacion || "")) +
              "</strong>",
          ];
          if (punto.distancia_km != null) {
            partes.push("Distancia: " + esc(punto.distancia_km) + " km");
          }
          if (esArribo) {
            const fases = punto.fases || [];
            fases.forEach(function (fase) {
              const detalles = [];
              if (fase.fase) {
                detalles.push(esc(fase.fase));
              }
              if (fase.llegada) {
                detalles.push(esc(fase.llegada));
              }
              if (fase.segundos != null) {
                detalles.push(Number(fase.segundos).toFixed(1) + " s");
              }
              if (fase.modo) {
                detalles.push(esc(fase.modo));
              }
              if (fase.usada) {
                detalles.push("usada: " + esc(fase.usada));
              }
              if (detalles.length) {
                partes.push(detalles.join(" · "));
              }
            });
          } else {
            if (punto.evidencia) {
              partes.push("Evidencia: " + esc(punto.evidencia));
            }
            if (punto.formas_onda) {
              partes.push("Formas de onda: " + esc(punto.formas_onda));
            }
            if (punto.disponible) {
              partes.push("Disponible y no usada: " + esc(punto.disponible));
            }
            if (punto.streams) {
              partes.push("Streams: " + esc(punto.streams));
            }
          }
          marcador.bindPopup(partes.join("<br>"));
          marcador.addTo(capaEstaciones);
        });
        capaEstaciones.addTo(mapa);
      },
      ocultarEstaciones: function () {
        if (capaEstaciones) {
          mapa.removeLayer(capaEstaciones);
          capaEstaciones = null;
        }
      },
    };
  }

  if (historicoCheck) {
    historicoCheck.addEventListener("change", cargarHistorico);
  }

  if (modo === "online") {
    dibujarLeaflet();
  } else {
    dibujarPlotly();
  }
  dibujarPerfil();

})();
