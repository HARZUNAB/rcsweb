// Paneles: planta del grupo seleccionado, perfil y viñeta del evento.
(function () {
  "use strict";

  const datosEl = document.getElementById("panel-datos");
  const graficosEl = document.getElementById("panel-perfiles-grafico");
  const mapaEl = document.getElementById("panel-mapa");
  const perfilEl = document.getElementById("panel-perfil");
  if (!datosEl || !mapaEl) {
    return;
  }

  let datos = null;
  let graficos = {};
  try {
    datos = JSON.parse(datosEl.textContent || "null");
    graficos = graficosEl ? JSON.parse(graficosEl.textContent || "{}") : {};
  } catch (error) {
    return;
  }
  if (!datos || !Array.isArray(datos.eventos)) {
    return;
  }

  const mapaTitulo = document.getElementById("panel-mapa-titulo");
  const mapaDetalle = document.getElementById("panel-mapa-detalle");
  const perfilTitulo = document.getElementById("panel-perfil-titulo");
  const perfilVacio = document.getElementById("panel-perfil-vacio");
  const perfilDetalle = document.getElementById("panel-perfil-detalle");
  const gruposEl = document.getElementById("panel-grupos");
  const tbody = document.getElementById("panel-eventos");
  const titulo = document.getElementById("panel-grupo-titulo");
  const detalle = document.getElementById("panel-grupo-detalle");
  const total = document.getElementById("panel-grupo-total");
  const aviso = document.getElementById("panel-eventos-aviso");
  const soloSospechosos = document.getElementById("panel-sospechosos");
  const listadoEl = document.getElementById("panel-listado");
  const filtrosEl = document.getElementById("panel-filtros");
  const seleccionadosCount = document.getElementById("panel-seleccionados-count");
  const botonDescargarTodo = document.getElementById("panel-descargar-todo");
  const botonDescargarFiltrado = document.getElementById("panel-descargar-filtrado");
  const botonDescargarSeleccionados = document.getElementById(
    "panel-descargar-seleccionados"
  );
  const seleccionarTodos = document.getElementById("panel-seleccionar-todos");
  const jobId = listadoEl ? listadoEl.dataset.jobId || "" : "";
  const LIMITE = 200;
  const seleccionados = new Set();

  const estado = {
    grupo: null,
    evento: null,
    solo: false,
    trazaMapa: null,
    trazaPerfil: null,
  };

  const COLORES_TIPO = {
    no_publicado: "#dc3545",
    no_actualizado: "#fd7e14",
    repetido: "#6f42c1",
    "": "#0d6efd",
  };
  const ETIQUETAS_TIPO = {
    no_publicado: "No publicado",
    no_actualizado: "No actualizado",
    repetido: "Repetido",
  };
  const ETIQUETAS_FUENTE = {
    seiscomp: "SeisComp",
    seisan: "Seisan",
    eventquery: "Eventquery",
  };

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

  function etiquetaFuente(fuente) {
    return ETIQUETAS_FUENTE[fuente] || fuente || "";
  }

  function eventosGrupo() {
    if (!estado.grupo) {
      return [];
    }
    return datos.eventos.filter(function (evento) {
      if (estado.grupo.tipo === "perfil") {
        return evento.perfil === estado.grupo.id;
      }
      return evento.territorio === estado.grupo.id;
    });
  }

  function eventosVisibles() {
    return eventosGrupo().filter(function (evento) {
      if (estado.solo && !evento.sospechoso) {
        return false;
      }
      return true;
    });
  }

  // Los mapas usan la paleta base; el color del tipo queda solo en la etiqueta
  // del listado para no mezclar la lectura del mapa con la clasificación.
  function colorEvento(evento) {
    if (evento.color) {
      return evento.color;
    }
    if (evento.rol === "publicado") {
      return "#ffffff";
    }
    if (
      evento.fuente === "eventquery" &&
      String(evento.percibido || "").toUpperCase() === "S"
    ) {
      return "#c00000";
    }
    return "#ffff00";
  }

  function colorTipo(evento) {
    return COLORES_TIPO[evento.tipo_observacion || ""] || "#6c757d";
  }

  function nombreGrupo() {
    if (!estado.grupo) {
      return "Eventos del grupo";
    }
    return estado.grupo.tipo === "perfil"
      ? "Perfil " + estado.grupo.id
      : "Territorio " + estado.grupo.id;
  }

  function anchoEvento(evento) {
    if (estado.evento && evento.id === estado.evento.id) {
      return 2.5;
    }
    return evento.sospechoso ? 3 : 1.2;
  }

  function colorBorde(evento) {
    if (estado.evento && evento.id === estado.evento.id) {
      return "#000080";
    }
    return evento.sospechoso ? "#7b1196" : "#000000";
  }

  function seleccionarGrupo(tipo, id) {
    estado.grupo = { tipo: tipo, id: id };
    estado.evento = null;
    seleccionados.clear();
    document.querySelectorAll(".fila-panel").forEach(function (fila) {
      const activo = fila.dataset.grupo === tipo && fila.dataset.id === id;
      fila.classList.toggle("table-active", activo);
    });
    cerrarVineta();
    renderEventos();
    dibujarMapa();
    renderPerfil();
    setTimeout(function () {
      if (window.Plotly) {
        window.Plotly.Plots.resize(mapaEl);
        if (tipo === "perfil") {
          window.Plotly.Plots.resize(perfilEl);
        }
      }
    }, 60);
  }

  function anclaDeEvento(evento, nodo) {
    if (evento && evento.event &&
        Number.isFinite(evento.event.clientX) &&
        Number.isFinite(evento.event.clientY)) {
      return { x: evento.event.clientX, y: evento.event.clientY };
    }
    if (window.RCSVineta) {
      return window.RCSVineta.anclaDeNodo(nodo || mapaEl);
    }
    return null;
  }

  function seleccionarEvento(evento, ancla) {
    if (!evento) {
      return;
    }
    estado.evento = evento;
    mostrarVineta(evento, ancla);
    resaltarEventoMapa();
    resaltarEventoPerfil();
  }

  function limpiarEvento() {
    estado.evento = null;
    cerrarVineta();
    dibujarMapa();
    renderPerfil();
  }

  function cerrarVineta() {
    if (window.RCSVineta) {
      window.RCSVineta.ocultar();
    }
  }

  function mostrarVineta(evento, ancla) {
    if (!window.RCSVineta) {
      return;
    }
    const tipo = evento.tipo_observacion
      ? ETIQUETAS_TIPO[evento.tipo_observacion] || evento.tipo_observacion
      : "—";
    const prof =
      evento.prof === null || evento.prof === undefined
        ? "—"
        : Number(evento.prof).toFixed(1) + " km";
    const perfil = evento.perfil
      ? esc(evento.perfil)
      : '<span class="text-secondary">No disponible</span>';
    let html =
      '<div class="small text-secondary mb-1">' +
      esc(evento.fecha) +
      " · " +
      esc(tipo) +
      " · " +
      esc(etiquetaFuente(evento.fuente)) +
      "</div>" +
      '<div class="fw-semibold mb-2">Evento seleccionado</div>' +
      '<dl class="row mb-0 small g-0">' +
      '<dt class="col-5 text-secondary fw-normal">Magnitud</dt>' +
      '<dd class="col-7">' +
      esc(evento.mag || "—") +
      "</dd>" +
      '<dt class="col-5 text-secondary fw-normal">Profundidad</dt>' +
      '<dd class="col-7">' +
      esc(prof) +
      "</dd>" +
      '<dt class="col-5 text-secondary fw-normal">Perfil</dt>' +
      '<dd class="col-7">' +
      perfil +
      "</dd>";
    if (!evento.perfil && evento.territorio) {
      html +=
        '<dt class="col-5 text-secondary fw-normal">Territorio</dt>' +
        '<dd class="col-7">' +
        esc(evento.territorio) +
        "</dd>";
    }
    if (evento.analista) {
      html +=
        '<dt class="col-5 text-secondary fw-normal">' +
        (evento.fuente === "eventquery"
          ? "Analista probable"
          : "Analista") +
        "</dt>" +
        '<dd class="col-7">' +
        esc(evento.analista) +
        "</dd>";
    }
    html +=
      '<dt class="col-5 text-secondary fw-normal">Revisión</dt>' +
      '<dd class="col-7">' +
      esc(evento.revision || "—") +
      "</dd>" +
      '<dt class="col-5 text-secondary fw-normal">Sospechoso</dt>' +
      '<dd class="col-7">' +
      (evento.sospechoso
        ? '<span class="badge text-bg-danger">Sí</span>'
        : "No") +
      "</dd></dl>";
    if (evento.url) {
      html +=
        '<a class="btn btn-sm btn-primary mt-2" target="_blank" rel="noopener" href="' +
        esc(evento.url) +
        '">Ver detalle</a>';
    }
    window.RCSVineta.mostrar(html, {
      ancla: ancla,
      evitar: [mapaEl, perfilEl].filter(Boolean),
      preferir: gruposEl,
    });
  }

  function renderEventos() {
    titulo.textContent = "Listado de eventos";
    const todos = eventosGrupo();
    const visibles = eventosVisibles();
    detalle.textContent = estado.grupo
      ? nombreGrupo() +
        " · " +
        todos.length +
        " evento" +
        (todos.length === 1 ? "" : "s") +
        " en el grupo"
      : "";
    total.textContent = visibles.length
      ? visibles.length + " visible" + (visibles.length === 1 ? "" : "s")
      : "";
    if (!datos.eventos.length) {
      tbody.innerHTML =
        '<tr><td colspan="9" class="text-center text-secondary py-3">' +
        "No hay eventos para el filtro seleccionado.</td></tr>";
      aviso.classList.add("d-none");
      actualizarSeleccion();
      return;
    }
    if (!estado.grupo) {
      tbody.innerHTML =
        '<tr><td colspan="9" class="text-center text-secondary py-3">' +
        "Seleccione un perfil o territorio.</td></tr>";
      aviso.classList.add("d-none");
      actualizarSeleccion();
      return;
    }
    if (!visibles.length) {
      tbody.innerHTML =
        '<tr><td colspan="9" class="text-center text-secondary py-3">' +
        "No hay eventos con estos filtros.</td></tr>";
      aviso.classList.add("d-none");
      actualizarSeleccion();
      return;
    }
    tbody.innerHTML = visibles
      .slice(0, LIMITE)
      .map(function (evento) {
        const tipo = evento.tipo_observacion
          ? '<span class="badge" style="background:' +
            colorTipo(evento) +
            '">' +
            esc(ETIQUETAS_TIPO[evento.tipo_observacion] || evento.tipo_observacion) +
            "</span>"
          : "—";
        const prof =
          evento.prof === null || evento.prof === undefined
            ? "—"
            : Number(evento.prof).toFixed(1);
        const accion = evento.url
          ? '<a class="btn btn-sm btn-outline-primary" target="_blank" rel="noopener" href="' +
            esc(evento.url) +
            '">Ver</a>'
          : "";
        return (
          '<tr class="fila-evento" data-id="' +
          esc(evento.id) +
          '" tabindex="0">' +
          '<td class="text-center">' +
          '<input class="form-check-input seleccion-evento-panel" type="checkbox" value="' +
          esc(evento.id) +
          '"' +
          (seleccionados.has(evento.id) ? " checked" : "") +
          ' aria-label="Seleccionar evento">' +
          "</td><td>" +
          esc(evento.fecha) +
          "</td><td>" +
          tipo +
          "</td><td>" +
          esc(etiquetaFuente(evento.fuente)) +
          '</td><td class="text-end">' +
          esc(evento.mag || "—") +
          '</td><td class="text-end">' +
          prof +
          "</td><td>" +
          esc(evento.revision || "—") +
          '</td><td class="text-end">' +
          (evento.sospechoso
            ? '<span class="badge text-bg-danger">Sí</span>'
            : "—") +
          '</td><td class="text-end">' +
          accion +
          "</td></tr>"
        );
      })
      .join("");
    if (visibles.length > LIMITE) {
      aviso.textContent =
        "Mostrando los primeros " + LIMITE + " de " + visibles.length + " eventos.";
      aviso.classList.remove("d-none");
    } else {
      aviso.classList.add("d-none");
    }
    actualizarSeleccion();
  }

  function actualizarSeleccion() {
    const visibles = tbody
      ? Array.from(tbody.querySelectorAll(".seleccion-evento-panel"))
      : [];
    const marcadas = visibles.filter(function (caja) {
      return caja.checked;
    }).length;
    if (seleccionadosCount) {
      seleccionadosCount.textContent =
        seleccionados.size +
        " seleccionado" +
        (seleccionados.size === 1 ? "" : "s");
    }
    if (botonDescargarSeleccionados) {
      botonDescargarSeleccionados.disabled = seleccionados.size === 0;
      botonDescargarSeleccionados.textContent = seleccionados.size
        ? "Descargar seleccionados (" + seleccionados.size + ")"
        : "Descargar seleccionados";
    }
    if (seleccionarTodos) {
      seleccionarTodos.checked =
        visibles.length > 0 && marcadas === visibles.length;
      seleccionarTodos.indeterminate =
        marcadas > 0 && marcadas < visibles.length;
    }
    if (botonDescargarTodo) {
      botonDescargarTodo.disabled =
        !estado.grupo || eventosGrupo().length === 0;
    }
    if (botonDescargarFiltrado) {
      botonDescargarFiltrado.disabled = eventosVisibles().length === 0;
    }
  }

  function csvCampo(valor) {
    const texto =
      valor === null || valor === undefined ? "" : String(valor);
    if (/[",\n\r]/.test(texto)) {
      return '"' + texto.replace(/"/g, '""') + '"';
    }
    return texto;
  }

  function descargarCSV(eventos, modo) {
    if (!eventos.length) {
      return;
    }
    const cabecera = [
      "Fecha",
      "Tipo",
      "Fuente",
      "Analista",
      "Magnitud",
      "Profundidad (km)",
      "Revisión",
      "Sospechoso",
      "Perfil",
      "Territorio",
    ];
    const lineas = [cabecera.map(csvCampo).join(",")];
    eventos.forEach(function (evento) {
      const tipo = evento.tipo_observacion
        ? ETIQUETAS_TIPO[evento.tipo_observacion] ||
          evento.tipo_observacion
        : "";
      const profundidad =
        evento.prof === null || evento.prof === undefined
          ? ""
          : evento.prof;
      lineas.push(
        [
          evento.fecha || "",
          tipo,
          etiquetaFuente(evento.fuente),
          evento.analista || "",
          evento.mag || "",
          profundidad,
          evento.revision || "",
          evento.sospechoso ? "Sí" : "No",
          evento.perfil || "No disponible",
          evento.territorio || "",
        ]
          .map(csvCampo)
          .join(",")
      );
    });
    const blob = new Blob(["\ufeff" + lineas.join("\r\n")], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const enlace = document.createElement("a");
    const grupo = estado.grupo ? estado.grupo.id : "grupo";
    enlace.href = url;
    enlace.download = (
      "paneles_" +
      String(jobId || "").slice(0, 8) +
      "_" +
      grupo +
      "_" +
      modo +
      ".csv"
    ).replace(/[^\w.-]+/g, "_");
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 1000);
  }

  function actualizarConteos(eventos) {
    const texto =
      eventos.length + " evento" + (eventos.length === 1 ? "" : "s");
    if (mapaDetalle) {
      mapaDetalle.textContent = texto;
    }
    if (perfilDetalle) {
      perfilDetalle.textContent = texto + " ·";
    }
  }

  function eventosPerfilFiltrados() {
    return eventosVisibles().filter(function (evento) {
      return (
        evento.along_km !== null &&
        evento.along_km !== undefined &&
        evento.prof !== null &&
        evento.prof !== undefined
      );
    });
  }

  function claveSuperpuesto(evento, perfil) {
    if (perfil) {
      if (
        evento.along_km === null ||
        evento.along_km === undefined ||
        evento.prof === null ||
        evento.prof === undefined
      ) {
        return null;
      }
      return (
        Number(evento.along_km).toFixed(1) +
        "|" +
        Number(evento.prof).toFixed(1)
      );
    }
    return (
      Number(evento.lat).toFixed(3) + "|" + Number(evento.lon).toFixed(3)
    );
  }

  function marcarSuperpuestos(eventos, perfil) {
    const grupos = new Map();
    eventos.forEach(function (evento) {
      const clave = claveSuperpuesto(evento, perfil);
      if (clave === null) {
        return;
      }
      if (!grupos.has(clave)) {
        grupos.set(clave, new Set());
      }
      grupos.get(clave).add(evento.fuente || "");
    });
    return eventos.filter(function (evento) {
      const clave = claveSuperpuesto(evento, perfil);
      const fuentes = clave === null ? null : grupos.get(clave);
      return fuentes && fuentes.size > 1;
    });
  }

  // Aro magenta para soluciones de fuentes distintas en la misma ubicación.
  function trazaSuperpuestos(eventos, perfil) {
    const marcados = marcarSuperpuestos(eventos, perfil);
    if (!marcados.length) {
      return null;
    }
    const traza = {
      type: perfil ? "scatter" : "scattergeo",
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
    if (perfil) {
      traza.x = marcados.map(function (evento) {
        return evento.along_km;
      });
      traza.y = marcados.map(function (evento) {
        return -evento.prof;
      });
    } else {
      traza.lon = marcados.map(function (evento) {
        return evento.lon;
      });
      traza.lat = marcados.map(function (evento) {
        return evento.lat;
      });
    }
    return traza;
  }

  // Hover sincronizado entre planta y perfil. El flag corta la recursión
  // cuando Plotly dispara el hover programático en el otro gráfico.
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

  function dibujarMapa() {
    if (!window.Plotly) {
      mapaEl.innerHTML =
        '<div class="text-secondary small p-3">No se pudo cargar el mapa.</div>';
      return;
    }
    const esPerfil = estado.grupo && estado.grupo.tipo === "perfil";
    if (mapaTitulo) {
      mapaTitulo.textContent = esPerfil
        ? "Planta del perfil " + estado.grupo.id
        : "Planta del territorio " + (estado.grupo ? estado.grupo.id : "");
    }
    const eventos = eventosVisibles();
    actualizarConteos(eventos);
    if (!eventos.length) {
      mapaEl.innerHTML =
        '<div class="text-secondary small p-3">No hay eventos para este grupo con los filtros actuales.</div>';
      return;
    }

    const trazas = [];
    if (esPerfil) {
      const grafico = graficos[estado.grupo.id];
      if (grafico && (grafico.slab_lon || []).length) {
        trazas.push({
          type: "scattergeo",
          mode: "lines",
          lon: grafico.slab_lon,
          lat: grafico.slab_lat,
          line: { color: "#1f1f1f", width: 2 },
          hoverinfo: "skip",
          name: "Perfil",
        });
      }
    }
    const indiceEventos = trazas.length;
    trazas.push({
      type: "scattergeo",
      mode: "markers",
      lon: eventos.map(function (evento) {
        return evento.lon;
      }),
      lat: eventos.map(function (evento) {
        return evento.lat;
      }),
      text: eventos.map(function (evento) {
        return evento.fecha + " · " + etiquetaFuente(evento.fuente);
      }),
      customdata: eventos,
      marker: {
        size: eventos.map(function (evento) {
          return estado.evento && estado.evento.id === evento.id ? 18 : 13;
        }),
        color: eventos.map(colorEvento),
        line: {
          color: eventos.map(colorBorde),
          width: eventos.map(anchoEvento),
        },
      },
      hovertemplate: "%{text}<extra></extra>",
      name: "Eventos",
    });
    const superpuestosMapa = trazaSuperpuestos(eventos, false);
    if (superpuestosMapa) {
      trazas.push(superpuestosMapa);
    }

    const layout = {
      margin: { l: 0, r: 0, t: 0, b: 0 },
      geo: {
        fitbounds: "locations",
        showland: true,
        landcolor: "#f1f3f5",
        showcountries: true,
        countrycolor: "#ced4da",
        showcoastlines: true,
        coastlinecolor: "#adb5bd",
        projection: {
          type: esPerfil ? "mercator" : "natural earth",
        },
      },
      showlegend: false,
      paper_bgcolor: "#ffffff",
    };
    window.Plotly.react(mapaEl, trazas, layout, {
      responsive: true,
      displaylogo: false,
    });
    estado.trazaMapa = indiceEventos;
    if (!mapaEl._panelClick) {
      mapaEl._panelClick = true;
      mapaEl.on("plotly_click", function (evento) {
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== estado.trazaMapa) {
          return;
        }
        const punto = seleccion.customdata;
        if (punto && punto.id) {
          seleccionarEvento(punto, anclaDeEvento(evento, mapaEl));
        }
      });
      mapaEl.on("plotly_hover", function (evento) {
        if (sincronizandoHover) {
          return;
        }
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== estado.trazaMapa) {
          return;
        }
        const punto = seleccion.customdata;
        if (!punto) {
          return;
        }
        const indice = eventosPerfilFiltrados().findIndex(function (item) {
          return item.id === punto.id;
        });
        hoverEn(perfilEl, estado.trazaPerfil, indice, "xy");
      });
      mapaEl.on("plotly_unhover", function () {
        quitarHover(perfilEl);
      });
    }
  }

  function mostrarPerfilVacio(mostrar) {
    if (perfilVacio) {
      perfilVacio.classList.toggle("d-none", !mostrar);
    }
  }

  function limpiarPerfil() {
    estado.trazaPerfil = null;
    if (perfilEl && window.Plotly && perfilEl.data) {
      window.Plotly.purge(perfilEl);
      perfilEl._panelClick = false;
      perfilEl._panelHover = false;
    }
  }

  function renderPerfil() {
    if (!perfilEl) {
      return;
    }
    if (estado.grupo) {
      actualizarConteos(eventosVisibles());
    }
    if (!estado.grupo || estado.grupo.tipo !== "perfil" || !window.Plotly) {
      if (perfilTitulo) {
        perfilTitulo.textContent = "Perfil";
      }
      limpiarPerfil();
      mostrarPerfilVacio(true);
      return;
    }
    if (perfilTitulo) {
      perfilTitulo.textContent = "Perfil " + estado.grupo.id;
    }
    const grafico = graficos[estado.grupo.id];
    if (!grafico) {
      limpiarPerfil();
      mostrarPerfilVacio(true);
      return;
    }
    mostrarPerfilVacio(false);
    const eventos = eventosPerfilFiltrados();
    const trazas = [];
    if ((grafico.topo_p || []).length) {
      trazas.push({
        type: "scatter",
        mode: "lines",
        x: grafico.topo_p,
        y: (grafico.topo_alt || []).map(function (valor) {
          return valor === null || valor === undefined ? null : valor / 1000.0;
        }),
        line: { color: "#b8a37a", width: 1 },
        fill: "tozeroy",
        fillcolor: "rgba(232, 220, 194, 0.55)",
        hoverinfo: "skip",
        name: "Topografía",
      });
    }
    if ((grafico.slab_p || []).length) {
      trazas.push({
        type: "scatter",
        mode: "lines",
        x: grafico.slab_p,
        y: (grafico.slab_depth || []).map(function (valor) {
          return valor === null || valor === undefined ? null : -valor;
        }),
        line: { color: "#1f1f1f", width: 2 },
        hoverinfo: "skip",
        name: "Slab",
      });
    }
    const indiceEventos = trazas.length;
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
        return evento.fecha + " · " + etiquetaFuente(evento.fuente);
      }),
      customdata: eventos,
      marker: {
        size: eventos.map(function (evento) {
          return estado.evento && estado.evento.id === evento.id ? 16 : 11;
        }),
        color: eventos.map(colorEvento),
        line: {
          color: eventos.map(colorBorde),
          width: eventos.map(anchoEvento),
        },
      },
      hovertemplate: "%{text}<extra></extra>",
      name: "Eventos",
    });
    const superpuestosPerfil = trazaSuperpuestos(eventos, true);
    if (superpuestosPerfil) {
      trazas.push(superpuestosPerfil);
    }

    const shapes = [
      {
        type: "line",
        xref: "paper",
        x0: 0,
        x1: 1,
        y0: 0,
        y1: 0,
        line: { color: "#adb5bd", width: 1, dash: "dot" },
      },
    ];
    const layout = {
      margin: { l: 55, r: 15, t: 15, b: 45 },
      xaxis: { title: "Distancia a lo largo del perfil (km)", zeroline: false },
      yaxis: { title: "Elevación / Profundidad (km)", zeroline: true },
      showlegend: false,
      paper_bgcolor: "#ffffff",
      plot_bgcolor: "#ffffff",
      shapes: shapes,
    };
    window.Plotly.react(perfilEl, trazas, layout, {
      responsive: true,
      displaylogo: false,
    });
    estado.trazaPerfil = indiceEventos;
    if (!perfilEl._panelClick) {
      perfilEl._panelClick = true;
      perfilEl.on("plotly_click", function (evento) {
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== estado.trazaPerfil) {
          return;
        }
        const punto = seleccion.customdata;
        if (punto && punto.id) {
          seleccionarEvento(punto, anclaDeEvento(evento, perfilEl));
        }
      });
      perfilEl.on("plotly_hover", function (evento) {
        if (sincronizandoHover) {
          return;
        }
        const seleccion = evento.points[0];
        if (!seleccion || seleccion.curveNumber !== estado.trazaPerfil) {
          return;
        }
        const punto = seleccion.customdata;
        if (!punto) {
          return;
        }
        const indice = eventosVisibles().findIndex(function (item) {
          return item.id === punto.id;
        });
        hoverEn(mapaEl, estado.trazaMapa, indice, "geo");
      });
      perfilEl.on("plotly_unhover", function () {
        quitarHover(mapaEl);
      });
    }
  }

  function resaltarEventoMapa() {
    if (!window.Plotly || estado.trazaMapa === null) {
      return;
    }
    const eventos = eventosVisibles();
    window.Plotly.restyle(
      mapaEl,
      {
        "marker.size": [
          eventos.map(function (evento) {
            return estado.evento && estado.evento.id === evento.id ? 18 : 13;
          }),
        ],
        "marker.line.width": [eventos.map(anchoEvento)],
        "marker.line.color": [eventos.map(colorBorde)],
      },
      [estado.trazaMapa]
    );
  }

  function resaltarEventoPerfil() {
    if (!window.Plotly || estado.trazaPerfil === null || !perfilEl) {
      return;
    }
    const eventos = eventosVisibles().filter(function (evento) {
      return (
        evento.along_km !== null &&
        evento.along_km !== undefined &&
        evento.prof !== null &&
        evento.prof !== undefined
      );
    });
    window.Plotly.restyle(
      perfilEl,
      {
        "marker.size": [
          eventos.map(function (evento) {
            return estado.evento && estado.evento.id === evento.id ? 16 : 11;
          }),
        ],
        "marker.line.width": [eventos.map(anchoEvento)],
        "marker.line.color": [eventos.map(colorBorde)],
      },
      [estado.trazaPerfil]
    );
  }

  function encontrarEvento(id) {
    return datos.eventos.find(function (evento) {
      return evento.id === id;
    });
  }

  // Navegación con teclado: las flechas recorren perfiles/territorios y
  // activan los dos mapas sin necesidad de hacer clic en cada fila.
  const filasPanel = Array.from(document.querySelectorAll(".fila-panel"));
  filasPanel.forEach(function (fila) {
    fila.addEventListener("click", function () {
      seleccionarGrupo(fila.dataset.grupo, fila.dataset.id);
    });
    fila.addEventListener("keydown", function (evento) {
      if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
        evento.preventDefault();
        const posicion = filasPanel.indexOf(fila);
        const destino =
          filasPanel[
            posicion + (evento.key === "ArrowDown" ? 1 : -1)
          ];
        if (destino) {
          destino.focus();
          seleccionarGrupo(destino.dataset.grupo, destino.dataset.id);
        }
        return;
      }
      if (evento.key === "Home" || evento.key === "End") {
        evento.preventDefault();
        const destino =
          evento.key === "Home"
            ? filasPanel[0]
            : filasPanel[filasPanel.length - 1];
        if (destino) {
          destino.focus();
          seleccionarGrupo(destino.dataset.grupo, destino.dataset.id);
        }
        return;
      }
      if (evento.key === "Enter" || evento.key === " ") {
        evento.preventDefault();
        seleccionarGrupo(fila.dataset.grupo, fila.dataset.id);
      }
    });
  });

  if (tbody) {
    tbody.addEventListener("click", function (evento) {
      if (evento.target.closest(".seleccion-evento-panel")) {
        return;
      }
      const fila = evento.target.closest(".fila-evento");
      if (!fila) {
        return;
      }
      const encontrado = encontrarEvento(fila.dataset.id);
      if (encontrado) {
        const ancla = window.RCSVineta
          ? window.RCSVineta.anclaDeNodo(fila)
          : null;
        seleccionarEvento(encontrado, ancla);
      }
    });
    tbody.addEventListener("keydown", function (evento) {
      if (evento.target.closest(".seleccion-evento-panel")) {
        return;
      }
      if (evento.key !== "Enter" && evento.key !== " ") {
        return;
      }
      const fila = evento.target.closest(".fila-evento");
      if (!fila) {
        return;
      }
      evento.preventDefault();
      const encontrado = encontrarEvento(fila.dataset.id);
      if (encontrado) {
        const ancla = window.RCSVineta
          ? window.RCSVineta.anclaDeNodo(fila)
          : null;
        seleccionarEvento(encontrado, ancla);
      }
    });
    tbody.addEventListener("change", function (evento) {
      const caja = evento.target.closest(".seleccion-evento-panel");
      if (!caja) {
        return;
      }
      if (caja.checked) {
        seleccionados.add(caja.value);
      } else {
        seleccionados.delete(caja.value);
      }
      actualizarSeleccion();
    });
  }

  if (seleccionarTodos) {
    seleccionarTodos.addEventListener("change", function () {
      const visibles = tbody
        ? tbody.querySelectorAll(".seleccion-evento-panel")
        : [];
      visibles.forEach(function (caja) {
        caja.checked = seleccionarTodos.checked;
        if (seleccionarTodos.checked) {
          seleccionados.add(caja.value);
        } else {
          seleccionados.delete(caja.value);
        }
      });
      actualizarSeleccion();
    });
  }

  if (botonDescargarTodo) {
    botonDescargarTodo.addEventListener("click", function () {
      descargarCSV(eventosGrupo(), "todo");
    });
  }
  if (botonDescargarFiltrado) {
    botonDescargarFiltrado.addEventListener("click", function () {
      descargarCSV(eventosVisibles(), "filtrado");
    });
  }
  if (botonDescargarSeleccionados) {
    botonDescargarSeleccionados.addEventListener("click", function () {
      descargarCSV(
        eventosGrupo().filter(function (evento) {
          return seleccionados.has(evento.id);
        }),
        "seleccionados"
      );
    });
  }

  if (soloSospechosos) {
    soloSospechosos.addEventListener("change", function () {
      estado.solo = soloSospechosos.checked;
      estado.evento = null;
      cerrarVineta();
      renderEventos();
      dibujarMapa();
      renderPerfil();
    });
  }
  document.addEventListener("rcs:vineta-cerrada", limpiarEvento);

  function resaltarListado() {
    if (!listadoEl) {
      return;
    }
    listadoEl.classList.remove("listado-resaltado");
    void listadoEl.offsetWidth;
    listadoEl.classList.add("listado-resaltado");
    window.setTimeout(function () {
      listadoEl.classList.remove("listado-resaltado");
    }, 1800);
  }

  function ajustarMargenes() {
    if (!filtrosEl) {
      return;
    }
    const fija = window.getComputedStyle(filtrosEl).position === "sticky";
    const margen = fija
      ? Math.ceil(filtrosEl.getBoundingClientRect().height + 16)
      : 16;
    if (listadoEl) {
      listadoEl.style.scrollMarginTop = margen + "px";
    }
    if (gruposEl) {
      gruposEl.style.scrollMarginTop = margen + "px";
    }
  }

  function desplazarAlListado() {
    if (!listadoEl) {
      return;
    }
    ajustarMargenes();
    const caja = listadoEl.getBoundingClientRect();
    if (caja.top < 0 || caja.bottom > window.innerHeight) {
      listadoEl.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    resaltarListado();
  }

  document.querySelectorAll("[data-ir-listado]").forEach(function (enlace) {
    enlace.addEventListener("click", function (evento) {
      evento.preventDefault();
      desplazarAlListado();
    });
  });
  document.querySelectorAll("[data-volver-paneles]").forEach(function (enlace) {
    enlace.addEventListener("click", function (evento) {
      evento.preventDefault();
      ajustarMargenes();
      const destino = gruposEl || filtrosEl;
      if (destino) {
        destino.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  });

  ajustarMargenes();
  window.addEventListener("resize", ajustarMargenes);

  if (listadoEl && listadoEl.dataset.scroll === "1") {
    window.setTimeout(desplazarAlListado, 250);
  }

  if (!datos.eventos.length) {
    actualizarConteos([]);
  }

  if (datos.perfiles && datos.perfiles.length) {
    seleccionarGrupo("perfil", datos.perfiles[0].id);
  } else if (datos.territorios && datos.territorios.length) {
    seleccionarGrupo("territorio", datos.territorios[0].nombre);
  }
})();
