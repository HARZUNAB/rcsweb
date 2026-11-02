// Capa compartida de contorno nacional y divisiones regionales para Plotly.
(function () {
  "use strict";

  let urlCargada = "";
  let datosCargados = null;
  let promesaCargada = null;

  function cargar(url) {
    if (!url) {
      return Promise.resolve(null);
    }
    if (urlCargada === url && datosCargados) {
      return Promise.resolve(datosCargados);
    }
    if (urlCargada === url && promesaCargada) {
      return promesaCargada;
    }
    urlCargada = url;
    datosCargados = null;
    promesaCargada = fetch(url, { headers: { Accept: "application/json" } })
      .then(function (respuesta) {
        return respuesta.ok ? respuesta.json() : null;
      })
      .then(function (datos) {
        datosCargados =
          datos && datos.contorno && datos.regiones ? datos : null;
        return datosCargados;
      })
      .catch(function () {
        datosCargados = null;
        return null;
      })
      .finally(function () {
        promesaCargada = null;
      });
    return promesaCargada;
  }

  function pathProyectado(datos, proyeccion) {
    const partes = [];
    let parte = [];
    function cerrar() {
      if (parte.length > 1) {
        partes.push("M " + parte.join(" L "));
      }
      parte = [];
    }
    for (let i = 0; i < datos.lon.length; i += 1) {
      const lon = datos.lon[i];
      const lat = datos.lat[i];
      if (lon === null || lat === null) {
        cerrar();
        continue;
      }
      const punto = proyeccion([lon, lat]);
      if (!punto || !Number.isFinite(punto[0]) || !Number.isFinite(punto[1])) {
        cerrar();
        continue;
      }
      parte.push(punto[0].toFixed(1) + "," + punto[1].toFixed(1));
    }
    cerrar();
    return partes.join(" ");
  }

  function obtenerOverlay(mapaEl) {
    let overlay = mapaEl.querySelector(".mapa-regiones-overlay");
    if (!overlay) {
      overlay = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      overlay.setAttribute("class", "mapa-regiones-overlay");
      overlay.setAttribute("aria-hidden", "true");
      const contorno = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "path"
      );
      contorno.setAttribute("class", "overlay-contorno");
      contorno.setAttribute("fill", "none");
      const regiones = document.createElementNS(
        "http://www.w3.org/2000/svg",
        "path"
      );
      regiones.setAttribute("class", "overlay-regiones");
      regiones.setAttribute("fill", "none");
      overlay.appendChild(contorno);
      overlay.appendChild(regiones);
      mapaEl.appendChild(overlay);
    }
    mapaEl.style.position = "relative";
    overlay.style.position = "absolute";
    overlay.style.inset = "0";
    overlay.style.width = "100%";
    overlay.style.height = "100%";
    overlay.style.overflow = "hidden";
    overlay.style.pointerEvents = "none";
    overlay.style.zIndex = "10";
    return overlay;
  }

  function recortar(overlay, mapaEl) {
    const geoEl = mapaEl.querySelector(".geo");
    const clip = geoEl ? geoEl.getAttribute("clip-path") : "";
    const coincidencia = clip && clip.match(/^url\(#(.+)\)$/);
    const rectClip = coincidencia
      ? document.querySelector("#" + coincidencia[1] + " rect")
      : null;
    if (!rectClip) {
      overlay.style.clipPath = "none";
      return;
    }
    const x = Number(rectClip.getAttribute("x") || 0);
    const y = Number(rectClip.getAttribute("y") || 0);
    const w = Number(rectClip.getAttribute("width") || 0);
    const h = Number(rectClip.getAttribute("height") || 0);
    const ancho = mapaEl.clientWidth;
    const alto = mapaEl.clientHeight;
    overlay.style.clipPath =
      "inset(" +
      Math.max(0, y) + "px " +
      Math.max(0, ancho - (x + w)) + "px " +
      Math.max(0, alto - (y + h)) + "px " +
      Math.max(0, x) + "px)";
  }

  function dibujar(mapaEl, datos, opciones) {
    if (!mapaEl || !datos) {
      return;
    }
    const geo = mapaEl._fullLayout && mapaEl._fullLayout.geo;
    const sub = geo && geo._subplot;
    const proyeccion = sub && sub.projection;
    const overlay = obtenerOverlay(mapaEl);
    if (!proyeccion) {
      overlay.classList.add("d-none");
      return;
    }
    const ancho = mapaEl.clientWidth;
    const alto = mapaEl.clientHeight;
    overlay.setAttribute("viewBox", "0 0 " + ancho + " " + alto);
    overlay.classList.remove("d-none");

    const config = opciones || {};
    const contorno = overlay.querySelector(".overlay-contorno");
    const regiones = overlay.querySelector(".overlay-regiones");
    contorno.setAttribute("stroke", config.contorno_color || "#1f3a5f");
    contorno.setAttribute("stroke-width", config.contorno_ancho || "1.8");
    contorno.setAttribute("stroke-linecap", "round");
    regiones.setAttribute("stroke", config.regiones_color || "#52606d");
    regiones.setAttribute("stroke-width", config.regiones_ancho || "1.2");
    regiones.setAttribute("stroke-dasharray", config.regiones_dash || "4 2");
    regiones.setAttribute("stroke-linecap", "round");

    contorno.setAttribute(
      "d",
      pathProyectado(datos.contorno, proyeccion)
    );
    regiones.setAttribute(
      "d",
      pathProyectado(datos.regiones, proyeccion)
    );
    recortar(overlay, mapaEl);
  }

  function ocultar(mapaEl) {
    if (!mapaEl) {
      return;
    }
    const overlay = mapaEl.querySelector(".mapa-regiones-overlay");
    if (overlay) {
      overlay.classList.add("d-none");
      overlay.remove();
    }
  }

  window.RCSRegiones = {
    cargar: cargar,
    dibujar: dibujar,
    ocultar: ocultar,
  };
})();
