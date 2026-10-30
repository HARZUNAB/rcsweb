// Mapa interactivo del detalle: Leaflet online y Plotly offline/perfil.
(function () {
  "use strict";

  const datos = document.getElementById("mapa-datos");
  const contenedor = document.getElementById("mapa-detalle");
  const perfil = document.getElementById("perfil-detalle");
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
      ["Analista", valor(punto.analista)],
      ["Distancia", valor(punto.dist_km, " km")],
      ["Frontera", valor(punto.frontera)],
      ["Sospechoso", punto.sospechoso ? "Sí" : ""],
      ["Estado", valor(punto.estado)],
    ];
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
    if (!window.RCSVineta) {
      return;
    }
    window.RCSVineta.mostrar(detalleHtml(punto), {
      ancla: ancla,
      evitar: [contenedor, perfil].filter(Boolean),
    });
  }

  let plantaTipo = "plotly";
  let marcadoresLeaflet = [];
  let perfilEventos = [];
  let perfilTrazaIdx = null;

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

  // Paleta del proyecto base: amarillo local/no percibido, rojo Eventquery
  // percibido, blanco/negro para publicado, violeta para sospechoso.
  function colorPunto(punto) {
    if (punto.color) {
      return punto.color;
    }
    if (punto.rol === "publicado") {
      return "#ffffff";
    }
    if (
      punto.fuente === "eventquery" &&
      String(punto.percibido || "").toUpperCase() === "S"
    ) {
      return "#c00000";
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

  // Hover sincronizado: al pasar por un punto se dispara el hover del mismo
  // evento en el otro gráfico; el flag evita el bucle entre ambos.
  let sincronizandoHover = false;

  function hoverEn(plot, traza, indice, subplot) {
    if (
      !plot ||
      !window.Plotly ||
      !window.Plotly.Fx ||
      !plot.data ||
      traza === null ||
      indice < 0
    ) {
      return;
    }
    sincronizandoHover = true;
    window.Plotly.Fx.hover(
      plot,
      [{ curveNumber: traza, pointNumber: indice }],
      subplot || "xy"
    );
    window.setTimeout(function () {
      sincronizandoHover = false;
    }, 0);
  }

  function quitarHover(plot) {
    if (
      !plot ||
      !window.Plotly ||
      !window.Plotly.Fx ||
      !plot.data ||
      sincronizandoHover
    ) {
      return;
    }
    sincronizandoHover = true;
    window.Plotly.Fx.unhover(plot);
    window.setTimeout(function () {
      sincronizandoHover = false;
    }, 0);
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
    mostrarSeleccion(punto, ancla);
    resaltarPlanta(buscarIndice(puntos, punto));
    resaltarPerfil(buscarIndice(perfilEventos, punto));
  }

  function limpiarSeleccion() {
    resaltarPlanta(-1);
    resaltarPerfil(-1);
    if (window.RCSVineta) {
      window.RCSVineta.ocultar();
    }
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
      hovertemplate: "%{text}<extra></extra>",
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
    if (historicoPerfil) {
      (historicoPerfil.along || []).forEach(function (valor) {
        if (typeof valor === "number" && Number.isFinite(valor)) xs.push(valor);
      });
      (historicoPerfil.prof || []).forEach(function (valor) {
        if (typeof valor === "number" && Number.isFinite(valor)) ys.push(valor);
      });
    }
    const xMin = xs.length ? Math.min.apply(null, xs) : undefined;
    const xMax = xs.length ? Math.max.apply(null, xs) : undefined;
    const yMin = ys.length ? Math.min.apply(null, ys) : undefined;
    const yMax = ys.length ? Math.max.apply(null, ys) : undefined;
    const layout = {
      margin: { l: 60, r: 15, t: 15, b: 45 },
      xaxis: {
        title: "Distancia a lo largo del perfil (km)",
        range: xMin !== undefined ? [xMin, xMax] : undefined,
        zeroline: false,
      },
      yaxis: {
        title: "Elevación / Profundidad (km)",
        range: yMin !== undefined ? [yMin, yMax] : undefined,
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
        if (sincronizandoHover) {
          return;
        }
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== perfilTrazaIdx) {
          return;
        }
        const punto = seleccion.customdata;
        if (!punto) {
          return;
        }
        const indice = buscarIndice(puntos, punto);
        if (plantaTipo === "leaflet") {
          abrirTooltipMapa(indice);
        } else {
          hoverEn(contenedor, 0, indice, "geo");
        }
      });
      perfil.on("plotly_unhover", function () {
        if (plantaTipo === "leaflet") {
          cerrarTooltipsMapa();
        } else {
          quitarHover(contenedor);
        }
      });
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
      hovertemplate: "%{text}<extra></extra>",
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
    const latSpan = Math.max((latMax - latMin) * 1.2, 5.0);
    const lonSpan = Math.max((lonMax - lonMin) * 1.2, 8.0);
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
        if (sincronizandoHover) {
          return;
        }
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== 0) {
          return;
        }
        const punto = seleccion.customdata;
        if (!punto) {
          return;
        }
        const indice = buscarIndice(perfilEventos, punto);
        hoverEn(perfil, perfilTrazaIdx, indice, "xy");
      });
      contenedor.on("plotly_unhover", function () {
        quitarHover(perfil);
      });
    });
  }

  function abrirTooltipMapa(indice) {
    marcadoresLeaflet.forEach(function (marcador, i) {
      if (i === indice && marcador.openTooltip) {
        marcador.openTooltip();
      }
    });
  }

  function cerrarTooltipsMapa() {
    marcadoresLeaflet.forEach(function (marcador) {
      if (marcador.closeTooltip) {
        marcador.closeTooltip();
      }
    });
  }

  function dibujarLeaflet() {
    plantaTipo = "leaflet";
    marcadoresLeaflet = [];
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
      // En Leaflet el hover muestra la identificación y sincroniza el perfil.
      marcador.bindTooltip(punto.etiqueta + " · " + punto.fecha, {
        sticky: true,
        direction: "top",
      });
      marcador.on("mouseover", function () {
        if (sincronizandoHover) {
          return;
        }
        const indice = buscarIndice(perfilEventos, punto);
        hoverEn(perfil, perfilTrazaIdx, indice, "xy");
      });
      marcador.on("mouseout", function () {
        quitarHover(perfil);
      });
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
    if (coordenadas.length === 1) {
      mapa.setView(coordenadas[0], 9);
    } else {
      mapa.fitBounds(coordenadas, { padding: [30, 30] });
    }
  }

  if (modo === "online") {
    dibujarLeaflet();
  } else {
    dibujarPlotly();
  }
  dibujarPerfil();

})();
