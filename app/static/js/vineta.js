// Viñeta flotante compartida por el detalle y los paneles.
(function () {
  "use strict";

  let contenedor = null;
  let ultimoHtml = "";
  let ultimasOpciones = {};
  let temporizadorResize = null;

  function crear() {
    if (contenedor) {
      return contenedor;
    }
    contenedor = document.createElement("div");
    contenedor.id = "vineta-flotante";
    contenedor.className = "card border-0 shadow vineta-flotante d-none";
    contenedor.setAttribute("role", "dialog");
    contenedor.setAttribute("aria-live", "polite");
    contenedor.innerHTML =
      '<div class="card-body p-3">' +
      '<button type="button" class="btn-close float-end ms-2" ' +
      'data-cerrar-vineta aria-label="Cerrar"></button>' +
      '<div class="vineta-contenido"></div>' +
      "</div>";
    document.body.appendChild(contenedor);
    contenedor.addEventListener("click", function (evento) {
      if (evento.target.closest("[data-cerrar-vineta]")) {
        ocultar();
        document.dispatchEvent(new CustomEvent("rcs:vineta-cerrada"));
      }
    });
    return contenedor;
  }

  function limitar(valor, minimo, maximo) {
    if (maximo < minimo) {
      return minimo;
    }
    return Math.max(minimo, Math.min(maximo, valor));
  }

  function rectDocumento(elemento) {
    const caja = elemento.getBoundingClientRect();
    if (!caja.width || !caja.height) {
      return null;
    }
    const scrollX = window.scrollX || 0;
    const scrollY = window.scrollY || 0;
    return {
      left: caja.left + scrollX,
      top: caja.top + scrollY,
      right: caja.right + scrollX,
      bottom: caja.bottom + scrollY,
      width: caja.width,
      height: caja.height,
    };
  }

  function unir(rects) {
    if (!rects.length) {
      return null;
    }
    return {
      left: Math.min.apply(null, rects.map(function (r) { return r.left; })),
      top: Math.min.apply(null, rects.map(function (r) { return r.top; })),
      right: Math.max.apply(null, rects.map(function (r) { return r.right; })),
      bottom: Math.max.apply(null, rects.map(function (r) { return r.bottom; })),
    };
  }

  function intersecta(a, b) {
    return !(
      a.right <= b.left ||
      a.left >= b.right ||
      a.bottom <= b.top ||
      a.top >= b.bottom
    );
  }

  function colisiona(candidato, evitar) {
    return evitar.some(function (r) {
      return intersecta(candidato, r);
    });
  }

  function areaInterseccion(a, b) {
    const ancho = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const alto = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return ancho > 0 && alto > 0 ? ancho * alto : 0;
  }

  function candidato(x, y, ancho, alto) {
    return {
      left: x,
      top: y,
      right: x + ancho,
      bottom: y + alto,
      width: ancho,
      height: alto,
    };
  }

  function costo(c, ancla, vista) {
    let desplazamiento = 0;
    if (c.top < vista.top) {
      desplazamiento += vista.top - c.top;
    } else if (c.bottom > vista.bottom) {
      desplazamiento += c.bottom - vista.bottom;
    }
    if (c.left < vista.left) {
      desplazamiento += vista.left - c.left;
    } else if (c.right > vista.right) {
      desplazamiento += c.right - vista.right;
    }
    const dx = c.left + c.width / 2 - ancla.x;
    const dy = c.top + c.height / 2 - ancla.y;
    return {
      visible: desplazamiento === 0,
      desplazamiento: desplazamiento,
      distancia: Math.hypot(dx, dy),
    };
  }

  function asegurarVisible(elegido, vista) {
    let desplazamiento = 0;
    if (elegido.top < vista.top) {
      desplazamiento = elegido.top - vista.top;
    } else if (elegido.bottom > vista.bottom) {
      desplazamiento = elegido.bottom - vista.bottom;
    }
    if (!desplazamiento) {
      return;
    }
    const destino = Math.max(0, window.scrollY + desplazamiento);
    window.scrollTo({ top: destino, behavior: "smooth" });
  }

  function posicionar(nodo, opciones) {
    const ancho = nodo.offsetWidth || 340;
    const alto = nodo.offsetHeight || 240;
    const margen = 12;
    const scrollX = window.scrollX || 0;
    const scrollY = window.scrollY || 0;
    const vistaAncho = document.documentElement.clientWidth || window.innerWidth;
    const vistaAlto = document.documentElement.clientHeight || window.innerHeight;
    const vista = {
      left: scrollX + margen,
      top: scrollY + (scrollY < 60 ? 76 : 16),
      right: scrollX + vistaAncho - margen,
      bottom: scrollY + vistaAlto - margen,
    };
    const evitar = (opciones.evitar || [])
      .map(rectDocumento)
      .filter(function (r) { return r; });
    const union = unir(evitar);
    const ancla = opciones.ancla || {};
    const anclaX = Number.isFinite(ancla.x)
      ? ancla.x + scrollX
      : union
        ? union.left + union.width / 2
        : vista.left + ancho / 2;
    const anclaY = Number.isFinite(ancla.y)
      ? ancla.y + scrollY
      : union
        ? union.top + 80
        : vista.top + 80;

    const candidatos = [];
    let preferido = null;
    const agregar = function (x, y) {
      candidatos.push(candidato(x, y, ancho, alto));
    };
    const centrarX = function (centro) {
      return limitar(centro - ancho / 2, vista.left, vista.right - ancho);
    };
    const ubicarX = function (x) {
      return limitar(x, vista.left, vista.right - ancho);
    };
    const ubicarY = function (y) {
      return limitar(y, vista.top, vista.bottom - alto);
    };

    if (opciones.preferir) {
      const zona = rectDocumento(opciones.preferir);
      if (zona && zona.width >= ancho + 16) {
        preferido = candidato(
          limitar(anclaX - ancho / 2, zona.left + 8, zona.right - ancho - 8),
          ubicarY(anclaY - alto / 2),
          ancho,
          alto
        );
        candidatos.push(preferido);
      }
    }
    if (union) {
      agregar(centrarX(anclaX), union.top - alto - 12);
      agregar(centrarX(anclaX), union.bottom + 12);
      agregar(ubicarX(union.left - ancho - 12), ubicarY(anclaY - alto / 2));
      agregar(ubicarX(union.right + 12), ubicarY(anclaY - alto / 2));
      evitar.forEach(function (r) {
        agregar(centrarX(anclaX), r.top - alto - 12);
        agregar(centrarX(anclaX), r.bottom + 12);
        agregar(ubicarX(r.left - ancho - 12), ubicarY(anclaY - alto / 2));
        agregar(ubicarX(r.right + 12), ubicarY(anclaY - alto / 2));
      });
    }
    agregar(vista.left, vista.top);
    agregar(vista.right - ancho, vista.top);
    agregar(vista.left, vista.bottom - alto);
    agregar(vista.right - ancho, vista.bottom - alto);

    const libres = candidatos.filter(function (c) {
      return !colisiona(c, evitar);
    });
    let elegido = null;
    if (preferido && libres.indexOf(preferido) !== -1 &&
        costo(preferido, { x: anclaX, y: anclaY }, vista).visible) {
      elegido = preferido;
    } else if (libres.length) {
      libres.sort(function (a, b) {
        const ca = costo(a, { x: anclaX, y: anclaY }, vista);
        const cb = costo(b, { x: anclaX, y: anclaY }, vista);
        if (ca.visible !== cb.visible) {
          return ca.visible ? -1 : 1;
        }
        if (ca.desplazamiento !== cb.desplazamiento) {
          return ca.desplazamiento - cb.desplazamiento;
        }
        return ca.distancia - cb.distancia;
      });
      elegido = libres[0];
    } else {
      let menor = Infinity;
      candidatos.forEach(function (c) {
        const area = evitar.reduce(function (total, r) {
          return total + areaInterseccion(c, r);
        }, 0);
        if (area < menor) {
          menor = area;
          elegido = c;
        }
      });
    }
    if (!elegido) {
      elegido = candidato(vista.left, vista.top, ancho, alto);
    }
    nodo.style.left = elegido.left + "px";
    nodo.style.top = elegido.top + "px";
    nodo.style.right = "auto";
    nodo.style.bottom = "auto";
    asegurarVisible(elegido, vista);
  }

  function mostrar(html, opciones) {
    const nodo = crear();
    const contenido = nodo.querySelector(".vineta-contenido");
    if (contenido) {
      contenido.innerHTML = html;
    }
    nodo.classList.remove("d-none");
    ultimoHtml = html;
    ultimasOpciones = opciones || {};
    const movil = window.matchMedia("(max-width: 991.98px)").matches;
    nodo.classList.toggle("vineta-hoja", movil);
    if (movil) {
      nodo.style.left = "";
      nodo.style.top = "";
      nodo.style.right = "";
      nodo.style.bottom = "";
      return;
    }
    posicionar(nodo, ultimasOpciones);
  }

  function ocultar() {
    if (contenedor) {
      contenedor.classList.add("d-none");
    }
  }

  function anclaDeNodo(nodo) {
    if (!nodo || typeof nodo.getBoundingClientRect !== "function") {
      return null;
    }
    const caja = nodo.getBoundingClientRect();
    return {
      x: caja.left + caja.width / 2,
      y: caja.top + caja.height / 2,
    };
  }

  document.addEventListener("keydown", function (evento) {
    if (evento.key === "Escape" && contenedor && !contenedor.classList.contains("d-none")) {
      ocultar();
      document.dispatchEvent(new CustomEvent("rcs:vineta-cerrada"));
    }
  });

  window.addEventListener("resize", function () {
    if (!contenedor || contenedor.classList.contains("d-none")) {
      return;
    }
    window.clearTimeout(temporizadorResize);
    temporizadorResize = window.setTimeout(function () {
      mostrar(ultimoHtml, ultimasOpciones);
    }, 120);
  });

  window.RCSVineta = {
    mostrar: mostrar,
    ocultar: ocultar,
    anclaDeNodo: anclaDeNodo,
  };
})();
