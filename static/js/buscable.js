/* Desplegables con buscador.
 *
 * Con 49 tiendas, o con los cargos de todas las unidades, un desplegable común
 * obliga a bajar la lista entera buscando con el ojo. Acá se escriben tres
 * letras y queda lo que importa.
 *
 * Es una mejora encima del `<select>` de siempre, no un reemplazo: el select
 * original sigue en la página y sigue siendo el que manda. Eso importa por
 * tres motivos concretos:
 *
 *   - El formulario se envía igual, sin campos inventados ni nombres nuevos.
 *   - El script que deja solo los cargos de la unidad elegida sigue andando:
 *     vacía y rellena el select, y acá nos enteramos y redibujamos.
 *   - Si este archivo no carga, o el navegador es viejo, queda el desplegable
 *     nativo funcionando. Nadie se queda sin poder registrar a alguien.
 *
 * Los desplegables cortos no se tocan: para cuatro opciones, el desplegable
 * del teléfono es mejor que cualquier cosa que hagamos nosotros.
 */
(function () {
  "use strict";

  var DESDE = 8;                  // menos opciones que esto, no vale la pena
  var CLASE = "buscable";

  /* Sin acentos y en minúscula: buscar "cedula" tiene que encontrar "Cédula",
     y "maracaibo" tiene que encontrar "MARACAIBO". */
  function plano(texto) {
    return (texto || "")
      .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().trim();
  }

  function opcionesDe(select) {
    var lista = [];
    Array.prototype.forEach.call(select.options, function (o) {
      var grupo = o.parentNode && o.parentNode.tagName === "OPTGROUP"
        ? o.parentNode.label : "";
      lista.push({
        valor: o.value,
        texto: o.text,
        grupo: grupo,
        buscar: plano((grupo ? grupo + " " : "") + o.text),
      });
    });
    return lista;
  }

  function crear(etiqueta, clase, texto) {
    var e = document.createElement(etiqueta);
    if (clase) { e.className = clase; }
    if (texto != null) { e.textContent = texto; }
    return e;
  }

  function armar(select) {
    var caja = crear("div", CLASE);
    select.parentNode.insertBefore(caja, select);

    var boton = crear("button", CLASE + "__valor");
    boton.type = "button";
    boton.setAttribute("aria-haspopup", "listbox");
    boton.setAttribute("aria-expanded", "false");

    var panel = crear("div", CLASE + "__panel");
    panel.hidden = true;

    var buscar = document.createElement("input");
    buscar.type = "search";
    buscar.className = CLASE + "__buscar";
    buscar.setAttribute("placeholder", "Escribí para buscar…");
    buscar.setAttribute("autocomplete", "off");
    // Sin esto, el teléfono arranca la primera letra en mayúscula y corrige
    // solo lo que uno escribe, justo cuando se buscan nombres propios.
    buscar.setAttribute("autocapitalize", "off");
    buscar.setAttribute("autocorrect", "off");
    buscar.setAttribute("spellcheck", "false");

    var lista = crear("ul", CLASE + "__lista");
    lista.setAttribute("role", "listbox");
    var nada = crear("p", CLASE + "__nada", "No hay ninguna opción con eso.");
    nada.hidden = true;

    /* Cuántas hay. En el panel entran seis o siete a la vez; con 85 unidades
       organizativas cargadas, ver seis se lee como "hay seis" y el resto no
       existe. Este renglón es lo que dice que la lista sigue más abajo. */
    var cuenta = crear("p", CLASE + "__cuenta");
    cuenta.setAttribute("aria-live", "polite");

    panel.appendChild(buscar);
    panel.appendChild(cuenta);
    panel.appendChild(lista);
    panel.appendChild(nada);
    caja.appendChild(boton);
    caja.appendChild(panel);
    caja.appendChild(select);            // el original queda adentro, invisible
    select.classList.add(CLASE + "__real");
    select.setAttribute("tabindex", "-1");

    var opciones = [];
    var marcada = -1;                    // la que está resaltada con el teclado

    function pintarBoton() {
      var elegida = select.options[select.selectedIndex];
      var texto = elegida ? elegida.text : "";
      boton.textContent = texto;
      boton.classList.toggle(CLASE + "__valor--vacio", !select.value);
      // El select también es lo que lee un lector de pantalla y lo que valida
      // el navegador: el botón solo cuenta lo mismo con otras palabras.
      boton.setAttribute("aria-label",
        (select.getAttribute("aria-label") || "") + " " + texto);
    }

    function pintarLista() {
      var texto = plano(buscar.value);
      lista.innerHTML = "";
      var visibles = 0;
      opciones.forEach(function (o, i) {
        if (texto && o.buscar.indexOf(texto) < 0) { return; }
        var item = crear("li", CLASE + "__opcion", o.texto);
        item.setAttribute("role", "option");
        item.dataset.indice = i;
        if (o.grupo) { item.appendChild(crear("span", CLASE + "__grupo", o.grupo)); }
        if (i === select.selectedIndex) {
          item.classList.add(CLASE + "__opcion--elegida");
          item.setAttribute("aria-selected", "true");
        }
        lista.appendChild(item);
        visibles++;
      });
      nada.hidden = visibles > 0;
      pintarCuenta(visibles);
      marcar(0);
    }

    /* "85 opciones · deslizá para ver todas" / "12 de 85". La opción vacía
       ("— Elegí… —") no se cuenta: no es una opción para nadie.

       Lo de "deslizá" se agrega solo si de verdad quedó algo abajo, y eso se
       mide, no se supone: cuántas entran depende del alto de la pantalla, y un
       aviso que sale siempre deja de avisar. */
    function pintarCuenta(visibles) {
      var total = opciones.filter(function (o) { return o.valor; }).length;
      var mostradas = visibles;
      if (!buscar.value && opciones.length && !opciones[0].valor) {
        mostradas = Math.max(0, visibles - 1);
      }
      if (total <= 0) { cuenta.hidden = true; return; }
      cuenta.hidden = false;
      if (buscar.value) {
        cuenta.textContent = mostradas + " de " + total;
        return;
      }
      var sobra = lista.scrollHeight > lista.clientHeight + 1;
      cuenta.textContent = total + " opciones"
        + (sobra ? " · deslizá para ver todas, o escribí para buscar" : "");
    }

    function items() {
      return lista.querySelectorAll("." + CLASE + "__opcion");
    }

    function marcar(pos) {
      var todos = items();
      if (!todos.length) { marcada = -1; return; }
      marcada = Math.max(0, Math.min(pos, todos.length - 1));
      Array.prototype.forEach.call(todos, function (e, i) {
        e.classList.toggle(CLASE + "__opcion--marcada", i === marcada);
      });
      var elegido = todos[marcada];
      if (elegido.scrollIntoView) { elegido.scrollIntoView({ block: "nearest" }); }
    }

    function elegir(indice) {
      select.selectedIndex = indice;
      // El `change` es lo que despierta al resto: la búsqueda en vivo de la
      // lista, el filtro de cargos por unidad, lo que venga después.
      select.dispatchEvent(new Event("change", { bubbles: true }));
      pintarBoton();
      cerrar();
      boton.focus();
    }

    function abrir() {
      if (!panel.hidden) { return; }
      cerrarLosDemas();
      // Se releen acá y no solo cuando avisa el observador: el observador
      // corre un instante después de que el select cambia, y elegir la unidad
      // y tocar el cargo enseguida alcanzaba para ver la lista vieja —cargos
      // de otra unidad, ofrecidos como si nada—.
      releer();
      panel.hidden = false;
      caja.dataset.abierto = "1";
      boton.setAttribute("aria-expanded", "true");
      buscar.value = "";
      pintarLista();
      acomodar();
      // Al abrir se marca la que está puesta, no la primera de la lista.
      Array.prototype.forEach.call(items(), function (e, i) {
        if (Number(e.dataset.indice) === select.selectedIndex) { marcar(i); }
      });
      buscar.focus();
    }

    /* Si el campo quedó cerca del borde de abajo —y en un teléfono pasa casi
       siempre—, el panel se abre para arriba. Abajo quedaría medio tapado por
       el borde de la pantalla, sin manera de ver el resto de la lista. */
    function acomodar() {
      var caj = boton.getBoundingClientRect();
      var alto = panel.offsetHeight;
      var abajo = window.innerHeight - caj.bottom;
      caja.classList.toggle(CLASE + "--arriba", abajo < alto + 8 && caj.top > abajo);
    }

    function cerrar() {
      panel.hidden = true;
      delete caja.dataset.abierto;
      boton.setAttribute("aria-expanded", "false");
    }

    boton.addEventListener("click", function () {
      if (panel.hidden) { abrir(); } else { cerrar(); }
    });

    buscar.addEventListener("input", pintarLista);

    lista.addEventListener("click", function (e) {
      var item = e.target.closest ? e.target.closest("." + CLASE + "__opcion") : null;
      if (item) { elegir(Number(item.dataset.indice)); }
    });

    panel.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { e.preventDefault(); marcar(marcada + 1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); marcar(marcada - 1); }
      else if (e.key === "Enter") {
        e.preventDefault();
        var elegido = items()[marcada];
        if (elegido) { elegir(Number(elegido.dataset.indice)); }
      } else if (e.key === "Escape") {
        e.preventDefault(); cerrar(); boton.focus();
      }
    });

    boton.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
        e.preventDefault(); abrir();
      }
    });

    caja.cerrarBuscable = cerrar;

    /* El select puede cambiar por su cuenta: elegir una unidad rehace la lista
       de cargos, y volver atrás en el navegador restaura el valor guardado. Si
       no lo miráramos, el botón mostraría un cargo que ya no está en la lista. */
    function releer() {
      opciones = opcionesDe(select);
      pintarBoton();
      if (!panel.hidden) { pintarLista(); }
    }
    new MutationObserver(releer).observe(select, { childList: true, subtree: true });
    select.addEventListener("change", pintarBoton);

    releer();
    return caja;
  }

  function cerrarLosDemas(menos) {
    Array.prototype.forEach.call(
      document.querySelectorAll("." + CLASE), function (c) {
        if (c !== menos && c.cerrarBuscable) { c.cerrarBuscable(); }
      });
  }

  document.addEventListener("click", function (e) {
    var dentro = e.target.closest ? e.target.closest("." + CLASE) : null;
    cerrarLosDemas(dentro);
  });

  /* --- El panel de casillas (tiendas) -------------------------------------
     No es un `<select>`, así que no pasa por lo de arriba, pero es el que más
     falta le hace: son todas las tiendas del país. */
  function armarCasillas(panel) {
    var etiquetas = panel.querySelectorAll("label");
    if (etiquetas.length < DESDE) { return; }

    var buscar = document.createElement("input");
    buscar.type = "search";
    buscar.className = CLASE + "__buscar";
    buscar.setAttribute("placeholder", "Buscar tienda…");
    buscar.setAttribute("autocomplete", "off");
    buscar.setAttribute("autocapitalize", "off");
    buscar.setAttribute("spellcheck", "false");

    var acciones = panel.querySelector(".multi__acciones");
    panel.insertBefore(buscar, acciones ? acciones.nextSibling : panel.firstChild);

    var nada = crear("p", CLASE + "__nada", "Ninguna tienda con eso.");
    nada.hidden = true;
    panel.appendChild(nada);

    buscar.addEventListener("input", function () {
      var texto = plano(buscar.value);
      var visibles = 0;
      Array.prototype.forEach.call(etiquetas, function (l) {
        var entra = !texto || plano(l.textContent).indexOf(texto) >= 0;
        l.hidden = !entra;
        if (entra) { visibles++; }
      });
      nada.hidden = visibles > 0;
    });

    // Escribir adentro del panel no tiene que cerrarlo ni mandar el formulario.
    buscar.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { e.preventDefault(); }
    });
  }

  function repasar(raiz) {
    var donde = raiz || document;
    Array.prototype.forEach.call(donde.querySelectorAll("select"), function (s) {
      if (s.multiple || s.dataset.buscable === "no" || s.dataset.listo) { return; }
      if (s.options.length < DESDE) { return; }
      s.dataset.listo = "1";
      armar(s);
    });
    Array.prototype.forEach.call(
      donde.querySelectorAll(".multi__panel"), function (p) {
        if (p.dataset.listo) { return; }
        p.dataset.listo = "1";
        armarCasillas(p);
      });
  }

  repasar();
  // htmx cambia pedazos de la página sin recargarla.
  document.body.addEventListener("htmx:afterSwap", function (e) {
    repasar(e.target);
  });
})();
