// Selección de eventos para solicitudes de revisión.
// La selección se guarda por trabajo + fuente + analista para conservarla
// cuando se entra al detalle de un evento y se vuelve al listado.
(function () {
  "use strict";

  const panel = document.getElementById("revision-seleccion");
  if (!panel) {
    return;
  }

  const url = panel.dataset.url || "";
  const fuente = panel.dataset.fuente || "";
  const analista = panel.dataset.analista || "";
  const analistaNombre = panel.dataset.analistaNombre || "";
  const maximo = Number(panel.dataset.max || 50);
  const clave = "rcs-revision-seleccion:" + (panel.dataset.clave || "");

  const casillas = function () {
    return Array.from(document.querySelectorAll(".seleccion-revision"));
  };
  const seleccionarTodos = document.getElementById(
    "seleccionar-todos-revision"
  );
  const contador = document.getElementById("revision-seleccionados");
  const boton = document.getElementById("btn-solicitar-revision");
  const aviso = document.getElementById("revision-aviso");

  const modalEl = document.getElementById("modalRevision");
  const modal = modalEl && window.bootstrap
    ? new window.bootstrap.Modal(modalEl)
    : null;
  const modalAnalista = document.getElementById("revision-analista");
  const modalCantidad = document.getElementById("revision-cantidad");
  const modalNota = document.getElementById("revision-nota");
  const modalAvisoCerrada = document.getElementById("revision-cerrada-aviso");
  const modalProgreso = document.getElementById("revision-progreso");
  const modalBarra = document.getElementById("revision-barra");
  const modalPaso = document.getElementById("revision-paso");
  const modalResultado = document.getElementById("revision-resultado");
  const modalError = document.getElementById("revision-error");
  const btnGenerar = document.getElementById("btn-generar-revision");

  let seleccion = new Set();
  let sondeo = null;
  let recargarAlCerrar = false;

  try {
    const guardadas = JSON.parse(window.localStorage.getItem(clave) || "[]");
    if (Array.isArray(guardadas)) {
      seleccion = new Set(guardadas.map(String));
    }
  } catch (error) {
    seleccion = new Set();
  }

  function guardar() {
    try {
      window.localStorage.setItem(
        clave,
        JSON.stringify(Array.from(seleccion))
      );
    } catch (error) {
      // Sin almacenamiento: la selección sigue en memoria.
    }
  }

  function seleccionadas() {
    return casillas().filter(function (caja) {
      return caja.checked;
    });
  }

  function actualizar() {
    const total = seleccionadas().length;
    if (contador) {
      contador.textContent =
        total + " seleccionado" + (total === 1 ? "" : "s");
    }
    if (boton) {
      boton.disabled = total === 0 || !analista;
    }
    if (seleccionarTodos) {
      const disponibles = casillas().filter(function (caja) {
        return !caja.disabled;
      });
      const marcadas = disponibles.filter(function (caja) {
        return caja.checked;
      }).length;
      seleccionarTodos.checked =
        disponibles.length > 0 && marcadas === disponibles.length;
      seleccionarTodos.indeterminate =
        marcadas > 0 && marcadas < disponibles.length;
    }
  }

  function mostrarAviso(texto) {
    if (aviso) {
      aviso.textContent = texto || "";
    }
  }

  function sincronizar() {
    const valores = new Set(seleccion);
    casillas().forEach(function (caja) {
      const valor = String(caja.value);
      const incluir = valores.has(valor) && !caja.disabled;
      caja.checked = incluir;
      if (!incluir) {
        seleccion.delete(valor);
      }
    });
    actualizar();
  }

  if (!analista) {
    casillas().forEach(function (caja) {
      caja.disabled = true;
    });
    if (seleccionarTodos) {
      seleccionarTodos.disabled = true;
    }
    mostrarAviso("Filtre por un usuario analista para seleccionar eventos.");
  } else {
    sincronizar();
  }

  casillas().forEach(function (caja) {
    caja.addEventListener("change", function () {
      const valor = String(caja.value);
      if (caja.checked) {
        const otra = seleccionadas().find(function (otraCaja) {
          return (
            String(otraCaja.value) !== valor &&
            otraCaja.dataset.analista !== caja.dataset.analista
          );
        });
        if (otra) {
          caja.checked = false;
          mostrarAviso("Seleccione solo eventos del mismo analista.");
          return;
        }
        if (seleccionadas().length > maximo) {
          caja.checked = false;
          mostrarAviso(
            "Máximo " + maximo + " eventos por solicitud. Quite uno antes de agregar otro."
          );
          return;
        }
        seleccion.add(valor);
      } else {
        seleccion.delete(valor);
      }
      mostrarAviso("");
      guardar();
      actualizar();
    });
  });

  if (seleccionarTodos) {
    seleccionarTodos.addEventListener("change", function () {
      const disponibles = casillas().filter(function (caja) {
        return !caja.disabled;
      });
      if (seleccionarTodos.checked) {
        if (disponibles.length > maximo) {
          mostrarAviso(
            "Hay " + disponibles.length + " eventos y el máximo es " + maximo + "."
          );
        }
        disponibles.slice(0, maximo).forEach(function (caja) {
          caja.checked = true;
          seleccion.add(String(caja.value));
        });
      } else {
        disponibles.forEach(function (caja) {
          caja.checked = false;
          seleccion.delete(String(caja.value));
        });
      }
      guardar();
      actualizar();
    });
  }

  function mostrarProgreso(datos) {
    if (!modalProgreso) {
      return;
    }
    modalProgreso.classList.remove("d-none");
    const progreso = Math.max(0, Math.min(100, Number(datos.progreso || 0)));
    if (modalBarra) {
      modalBarra.style.width = progreso + "%";
      modalBarra.textContent = progreso + "%";
    }
    if (modalPaso) {
      modalPaso.textContent = datos.paso || "Generando informe…";
    }
  }

  function detenerSondeo() {
    if (sondeo !== null) {
      window.clearTimeout(sondeo);
      sondeo = null;
    }
  }

  function consultarEstado(reportId) {
    fetch(url.replace(/\/$/, "") + "/" + reportId + "/estado", {
      headers: { Accept: "application/json" },
    })
      .then(function (respuesta) {
        return respuesta.json().then(function (datos) {
          return { ok: respuesta.ok, datos: datos };
        });
      })
      .then(function (resultado) {
        const datos = resultado.datos || {};
        if (!resultado.ok) {
          throw new Error(datos.error || "No se pudo consultar el estado.");
        }
        mostrarProgreso(datos);
        if (datos.estado === "listo") {
          detenerSondeo();
          if (btnGenerar) {
            btnGenerar.disabled = true;
          }
          recargarAlCerrar = true;
          if (modalResultado) {
            modalResultado.classList.remove("d-none");
            modalResultado.innerHTML =
              (datos.aviso ? "<div class=\"mb-1\">" + datos.aviso + "</div>" : "") +
              '<a class="btn btn-sm btn-primary" href="' +
              datos.url_solicitud +
              '">Ver solicitud</a>';
          }
          // La solicitud ya existe: limpiar la selección de este analista.
          seleccion.clear();
          guardar();
          casillas().forEach(function (caja) {
            caja.checked = false;
          });
          actualizar();
          return;
        }
        if (datos.estado === "error") {
          detenerSondeo();
          if (btnGenerar) {
            btnGenerar.disabled = false;
          }
          if (modalProgreso) {
            modalProgreso.classList.add("d-none");
          }
          if (modalError) {
            modalError.classList.remove("d-none");
            modalError.textContent =
              datos.error || "No se pudo generar la solicitud.";
          }
          return;
        }
        sondeo = window.setTimeout(function () {
          consultarEstado(reportId);
        }, 1500);
      })
      .catch(function (error) {
        detenerSondeo();
        if (btnGenerar) {
          btnGenerar.disabled = false;
        }
        if (modalError) {
          modalError.classList.remove("d-none");
          modalError.textContent = error.message;
        }
      });
  }

  if (boton) {
    boton.addEventListener("click", function () {
      const total = seleccionadas().length;
      if (!total || !analista || !modal) {
        return;
      }
      if (modalAnalista) {
        modalAnalista.textContent = analistaNombre || "—";
      }
      if (modalCantidad) {
        modalCantidad.textContent = String(total);
      }
      if (modalAvisoCerrada) {
        const cerrada = seleccionadas().some(function (caja) {
          return caja.dataset.cerrada === "1";
        });
        modalAvisoCerrada.classList.toggle("d-none", !cerrada);
        modalAvisoCerrada.textContent = cerrada
          ? "Algún evento ya tuvo una revisión cerrada. Se creará una nueva solicitud."
          : "";
      }
      if (modalProgreso) {
        modalProgreso.classList.add("d-none");
      }
      if (modalResultado) {
        modalResultado.classList.add("d-none");
        modalResultado.innerHTML = "";
      }
      if (modalError) {
        modalError.classList.add("d-none");
        modalError.textContent = "";
      }
      if (btnGenerar) {
        btnGenerar.disabled = false;
      }
      modal.show();
    });
  }

  if (btnGenerar) {
    btnGenerar.addEventListener("click", function () {
      const total = seleccionadas().length;
      if (!total || !analista) {
        return;
      }
      const meta = document.querySelector('meta[name="csrf-token"]');
      const formato =
        (document.querySelector(
          'input[name="revision-formato"]:checked'
        ) || {}).value || "pdf";
      const datos = new FormData();
      datos.append("csrf_token", meta ? meta.getAttribute("content") || "" : "");
      datos.append("fuente", fuente);
      datos.append("formato", formato);
      datos.append("nota", modalNota ? modalNota.value.trim() : "");
      seleccionadas().forEach(function (caja) {
        datos.append("eventos", String(caja.value));
      });

      btnGenerar.disabled = true;
      if (modalError) {
        modalError.classList.add("d-none");
      }
      if (modalResultado) {
        modalResultado.classList.add("d-none");
        modalResultado.innerHTML = "";
      }
      mostrarProgreso({ progreso: 0, paso: "Encolando la solicitud…" });

      fetch(url, {
        method: "POST",
        body: datos,
        headers: {
          Accept: "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
      })
        .then(function (respuesta) {
          return respuesta.json().then(function (cuerpo) {
            return { ok: respuesta.ok, datos: cuerpo };
          });
        })
        .then(function (resultado) {
          if (!resultado.ok) {
            throw new Error(
              (resultado.datos && resultado.datos.error) ||
                "No se pudo crear la solicitud."
            );
          }
          consultarEstado(resultado.datos.report_id);
        })
        .catch(function (error) {
          if (btnGenerar) {
            btnGenerar.disabled = false;
          }
          if (modalError) {
            modalError.classList.remove("d-none");
            modalError.textContent = error.message;
          }
        });
    });
  }

  if (modalEl) {
    modalEl.addEventListener("hidden.bs.modal", function () {
      detenerSondeo();
      if (recargarAlCerrar) {
        window.location.reload();
      }
    });
  }
})();
