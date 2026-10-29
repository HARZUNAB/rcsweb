// Mapa interactivo del detalle: Leaflet online y Plotly offline/perfil.
(function () {
  "use strict";

  const datos = document.getElementById("mapa-datos");
  const contenedor = document.getElementById("mapa-detalle");
  const perfil = document.getElementById("perfil-detalle");
  const panel = document.getElementById("mapa-seleccion");
  if (!datos || !contenedor || !perfil) {
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

  function mostrarSeleccion(punto) {
    if (!panel) {
      return;
    }
    panel.innerHTML = detalleHtml(punto);
    panel.classList.remove("d-none");
  }

  function mostrarAvisoOffline() {
    if (aviso) {
      aviso.classList.remove("d-none");
    }
    if (avisoLink && contenedor.dataset.offlineUrl) {
      avisoLink.href = contenedor.dataset.offlineUrl;
    }
  }

  function dibujarPerfilSimple() {
    const conProfundidad = puntos.filter(function (punto) {
      return punto.prof !== null && punto.prof !== undefined;
    });
    if (!conProfundidad.length || !window.Plotly) {
      perfil.innerHTML =
        '<div class="text-secondary small p-3">Sin profundidad para graficar el perfil.</div>';
      return;
    }
    const traza = {
      type: "scatter",
      mode: "markers",
      x: conProfundidad.map(function (punto) {
        return punto.dist_km === null || punto.dist_km === undefined
          ? 0
          : punto.dist_km;
      }),
      y: conProfundidad.map(function (punto) {
        return -punto.prof;
      }),
      text: conProfundidad.map(function (punto) {
        return punto.etiqueta + " · " + punto.fecha;
      }),
      customdata: conProfundidad,
      marker: {
        size: 11,
        color: conProfundidad.map(function (punto) {
          return punto.color;
        }),
        line: { color: "#ffffff", width: 1 },
      },
      hovertemplate: "%{text}<extra></extra>",
    };
    const layout = {
      margin: { l: 55, r: 15, t: 15, b: 45 },
      xaxis: { title: "Distancia (km)", zeroline: false },
      yaxis: { title: "Profundidad (km)" },
      showlegend: false,
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
    };
    window.Plotly.newPlot(perfil, [traza], layout, {
      responsive: true,
      displaylogo: false,
    }).then(function () {
      perfil.on("plotly_click", function (evento) {
        const punto = evento.points[0].customdata;
        if (punto) {
          mostrarSeleccion(punto);
        }
      });
    });
  }

  function dibujarPerfilCompleto(datos) {
    const eventos = (datos.eventos || []).filter(function (evento) {
      return evento.along_km !== null && evento.along_km !== undefined &&
        evento.prof !== null && evento.prof !== undefined;
    });
    if (!eventos.length || !window.Plotly) {
      dibujarPerfilSimple();
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
        color: eventos.map(function (evento) {
          return evento.color;
        }),
        line: {
          color: eventos.map(function (evento) {
            return evento.sospechoso ? "#7b1196" : "#ffffff";
          }),
          width: eventos.map(function (evento) {
            return evento.sospechoso ? 3 : 1;
          }),
        },
      },
      hovertemplate: "%{text}<extra></extra>",
      name: "Eventos",
    });
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
        const punto = evento.points[0].customdata;
        if (punto) {
          mostrarSeleccion(punto);
        }
      });
    });
  }

  function dibujarPerfil() {
    if (perfilDatos) {
      dibujarPerfilCompleto(perfilDatos);
    } else {
      dibujarPerfilSimple();
    }
  }

  function dibujarPlotly() {
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
        color: puntos.map(function (punto) {
          return punto.color;
        }),
        line: {
          color: puntos.map(function (punto) {
            return punto.sospechoso ? "#7b1196" : "#ffffff";
          }),
          width: puntos.map(function (punto) {
            return punto.sospechoso ? 3 : 1;
          }),
        },
      },
      hovertemplate: "%{text}<extra></extra>",
    };
    trazas.push(traza);
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
        const punto = evento.points[0].customdata;
        if (punto) {
          mostrarSeleccion(punto);
        }
      });
    });
  }

  function dibujarLeaflet() {
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
      const sospechoso = !!punto.sospechoso;
      const marcador = window.L.circleMarker([punto.lat, punto.lon], {
        radius: 8,
        color: sospechoso ? "#7b1196" : punto.color,
        fillColor: punto.color,
        fillOpacity: 0.85,
        weight: sospechoso ? 3 : 2,
      }).addTo(mapa);
      marcador.bindPopup(detalleHtml(punto));
      marcador.on("click", function () {
        mostrarSeleccion(punto);
      });
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
