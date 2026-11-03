// Catálogos: mapas generados a demanda, con indicador de actividad y ZIP opcional.
(function () {
  "use strict";

  const modalEl = document.getElementById("modalMapaCatalogo");
  const actividad = document.getElementById("catalogo-actividad");
  const actividadTexto = document.getElementById("catalogo-actividad-texto");
  const actividadSpinner = actividad
    ? actividad.querySelector(".spinner-border")
    : null;
  const formZip = document.getElementById("catalogo-zip");

  let modal = null;
  let urlObjeto = null;
  let pendientes = 0;

  function iniciarActividad(texto) {
    if (!actividad || !actividadTexto) {
      return;
    }
    const avisoPagina = document.getElementById("cargando-pagina");
    if (avisoPagina) {
      avisoPagina.classList.add("d-none");
    }
    pendientes += 1;
    actividadTexto.textContent = texto;
    actividad.classList.remove("d-none", "alert-danger");
    actividad.classList.add("alert-info");
    if (actividadSpinner) {
      actividadSpinner.classList.remove("d-none");
    }
  }

  function terminarActividad() {
    if (!actividad) {
      return;
    }
    pendientes = Math.max(0, pendientes - 1);
    if (!pendientes) {
      actividad.classList.add("d-none");
    }
  }

  function fallarActividad(texto) {
    if (!actividad || !actividadTexto) {
      return;
    }
    pendientes = Math.max(0, pendientes - 1);
    actividad.classList.remove("d-none", "alert-info");
    actividad.classList.add("alert-danger");
    actividadTexto.textContent = texto;
    if (actividadSpinner) {
      actividadSpinner.classList.add("d-none");
    }
  }

  async function pedir(url, tipo) {
    const respuesta = await fetch(url, {
      headers: { Accept: tipo },
      credentials: "same-origin",
    });
    if (!respuesta.ok) {
      throw new Error("El servidor respondió con error " + respuesta.status + ".");
    }
    const contenido = respuesta.headers.get("content-type") || "";
    if (!contenido.includes(tipo)) {
      throw new Error("La respuesta no tiene el formato esperado.");
    }
    return respuesta.blob();
  }

  function descargar(blob, nombre) {
    const enlace = document.createElement("a");
    const url = URL.createObjectURL(blob);
    enlace.href = url;
    enlace.download = nombre || "mapa.png";
    document.body.appendChild(enlace);
    enlace.click();
    enlace.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(url);
    }, 30000);
  }

  function liberarUrl() {
    if (urlObjeto) {
      URL.revokeObjectURL(urlObjeto);
      urlObjeto = null;
    }
  }

  function abrirModal(titulo, nombre) {
    if (!modalEl || !window.bootstrap) {
      return null;
    }
    if (!modal) {
      modal = new window.bootstrap.Modal(modalEl);
    }
    const tituloEl = document.getElementById("modal-mapa-titulo");
    const cargando = document.getElementById("modal-mapa-cargando");
    const error = document.getElementById("modal-mapa-error");
    const imagen = document.getElementById("modal-mapa-imagen");
    const descarga = document.getElementById("modal-mapa-descargar");

    tituloEl.textContent = titulo || "Mapa del catálogo";
    cargando.classList.remove("d-none");
    error.classList.add("d-none");
    error.textContent = "";
    imagen.classList.add("d-none");
    imagen.removeAttribute("src");
    descarga.classList.add("disabled");
    descarga.setAttribute("aria-disabled", "true");
    descarga.href = "#";
    descarga.download = nombre || "mapa.png";
    liberarUrl();
    modal.show();
    return { cargando, error, imagen, descarga };
  }

  async function verMapa(url, titulo, nombre) {
    const partes = abrirModal(titulo, nombre);
    if (!partes) {
      window.location.href = url;
      return;
    }
    iniciarActividad("Generando " + (titulo || "mapa") + "…");
    try {
      const blob = await pedir(url, "image/png");
      urlObjeto = URL.createObjectURL(blob);
      partes.imagen.src = urlObjeto;
      partes.imagen.alt = titulo || "Mapa del catálogo";
      partes.imagen.classList.remove("d-none");
      partes.cargando.classList.add("d-none");
      partes.descarga.href = urlObjeto;
      partes.descarga.download = nombre || "mapa.png";
      partes.descarga.classList.remove("disabled");
      partes.descarga.setAttribute("aria-disabled", "false");
      terminarActividad();
    } catch (error) {
      partes.cargando.classList.add("d-none");
      partes.error.textContent =
        "No se pudo generar el mapa. " + (error.message || "Intente nuevamente.");
      partes.error.classList.remove("d-none");
      fallarActividad("No se pudo generar el mapa.");
    }
  }

  async function descargarMapa(url, nombre, boton) {
    if (boton) {
      boton.classList.add("disabled");
      boton.setAttribute("aria-busy", "true");
    }
    iniciarActividad("Generando " + (nombre || "mapa") + "…");
    try {
      const blob = await pedir(url, "image/png");
      descargar(blob, nombre);
      terminarActividad();
    } catch (error) {
      fallarActividad(
        "No se pudo generar el mapa. " + (error.message || "Intente nuevamente.")
      );
    } finally {
      if (boton) {
        boton.classList.remove("disabled");
        boton.removeAttribute("aria-busy");
      }
    }
  }

  document.addEventListener("click", function (evento) {
    const ver = evento.target.closest(".js-mapa-ver");
    if (ver) {
      evento.preventDefault();
      verMapa(
        ver.dataset.url || ver.getAttribute("href"),
        ver.dataset.titulo || "",
        ver.dataset.nombre || "mapa.png"
      );
      return;
    }
    const bajar = evento.target.closest(".js-mapa-descargar");
    if (bajar) {
      evento.preventDefault();
      descargarMapa(
        bajar.dataset.url || bajar.getAttribute("href"),
        bajar.dataset.nombre || "mapa.png",
        bajar
      );
    }
  });

  if (modalEl) {
    modalEl.addEventListener("hidden.bs.modal", function () {
      liberarUrl();
      const imagen = document.getElementById("modal-mapa-imagen");
      const descarga = document.getElementById("modal-mapa-descargar");
      if (imagen) {
        imagen.removeAttribute("src");
        imagen.classList.add("d-none");
      }
      if (descarga) {
        descarga.href = "#";
        descarga.classList.add("disabled");
        descarga.setAttribute("aria-disabled", "true");
      }
    });
  }

  if (formZip) {
    const botonZip = document.getElementById("zip-boton");
    const textoBoton = botonZip ? botonZip.innerHTML : "";

    function cantidadMapas() {
      const plantas = document.getElementById("zip-plantas");
      const incluirPlantas = plantas && plantas.checked;
      const totalPlantas = Number(formZip.dataset.totalPlantas || 0);
      const totalPerfiles = Number(formZip.dataset.totalPerfiles || 0);
      const variante = formZip.querySelector(
        'input[name="perfiles"]:checked'
      );
      let perfiles = 0;
      if (variante) {
        if (variante.value === "ambos") {
          perfiles = totalPerfiles * 2;
        } else {
          perfiles = totalPerfiles;
        }
      }
      return (incluirPlantas ? totalPlantas : 0) + perfiles;
    }

    formZip.addEventListener("submit", async function (evento) {
      evento.preventDefault();
      const plantas = document.getElementById("zip-plantas");
      const variante = formZip.querySelector(
        'input[name="perfiles"]:checked'
      );
      const params = new URLSearchParams({
        plantas: plantas && plantas.checked ? "1" : "0",
        perfiles: variante ? variante.value : "ambos",
      });
      const base = formZip.dataset.url || "";
      const url = base + (base.includes("?") ? "&" : "?") + params.toString();
      const total = cantidadMapas();

      if (botonZip) {
        botonZip.disabled = true;
        botonZip.innerHTML =
          '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Generando…';
      }
      iniciarActividad(
        total > 0
          ? "Generando ZIP con " + total + " mapa" + (total === 1 ? "" : "s") + "…"
          : "Generando ZIP con el CSV…"
      );
      try {
        const blob = await pedir(url, "application/zip");
        descargar(blob, formZip.dataset.nombre || "catalogo.zip");
        terminarActividad();
      } catch (error) {
        fallarActividad(
          "No se pudo generar el ZIP. " +
            (error.message || "Intente nuevamente.")
        );
      } finally {
        if (botonZip) {
          botonZip.disabled = false;
          botonZip.innerHTML = textoBoton;
        }
      }
    });
  }
})();
