// Barra horizontal superior sincronizada para las tablas que desbordan.
// Evita tener que bajar hasta el final del listado para mover la tabla.
(function () {
  "use strict";

  function preparar(contenedor) {
    if (contenedor.dataset.scrollSuperior === "1") {
      return;
    }
    contenedor.dataset.scrollSuperior = "1";

    const barra = document.createElement("div");
    barra.className = "tabla-scroll-superior";
    barra.setAttribute("aria-hidden", "true");
    const espacio = document.createElement("div");
    espacio.className = "tabla-scroll-superior-espacio";
    barra.appendChild(espacio);
    contenedor.parentNode.insertBefore(barra, contenedor);

    let sincronizando = false;

    // El ancho del espaciador replica el de la tabla; la barra solo se muestra
    // cuando realmente hay desborde horizontal.
    function ajustar() {
      const tabla = contenedor.querySelector("table");
      const ancho = tabla
        ? Math.max(tabla.scrollWidth, contenedor.scrollWidth)
        : contenedor.scrollWidth;
      espacio.style.width = ancho + "px";
      barra.style.display =
        ancho > contenedor.clientWidth + 1 ? "block" : "none";
    }

    // Sincronización bidireccional entre la barra superior y el contenedor.
    barra.addEventListener("scroll", function () {
      if (sincronizando) {
        return;
      }
      sincronizando = true;
      contenedor.scrollLeft = barra.scrollLeft;
      sincronizando = false;
    });

    contenedor.addEventListener("scroll", function () {
      if (sincronizando) {
        return;
      }
      sincronizando = true;
      barra.scrollLeft = contenedor.scrollLeft;
      sincronizando = false;
    });

    window.addEventListener("resize", ajustar);
    if (window.ResizeObserver) {
      new ResizeObserver(ajustar).observe(contenedor);
      const tabla = contenedor.querySelector("table");
      if (tabla) {
        new ResizeObserver(ajustar).observe(tabla);
      }
    }
    ajustar();
  }

  document.querySelectorAll(".table-responsive").forEach(preparar);
})();
