/* Escáner de documentos con la cámara del teléfono.
 *
 * Flujo: se abre la cámara, se sacan las hojas de a una, se ven en miniatura,
 * y al terminar se elige el tipo de documento y se sube todo como un PDF.
 *
 * Cada foto se procesa en el teléfono antes de guardarse: se busca la hoja
 * dentro del encuadre, se recorta, y se aplica el filtro que la deja como
 * fotocopia. Sube una imagen liviana en vez de una foto de varios MB, que con
 * la conexión de una tienda es la diferencia entre que ande y que no.
 *
 * Las hojas sacadas quedan guardadas en el navegador (IndexedDB) mientras no se
 * suban: si se corta la llamada, se apaga la pantalla o se recarga sin querer,
 * al volver a abrir el escáner siguen ahí.
 */
(function () {
  "use strict";

  var CALIDAD = 0.82;          // JPEG: alcanza para leer y pesa un tercio
  var LADO_MAXIMO = 1800;      // píxeles del lado largo que se suben
  var BD = "gde-escaner";
  var ALMACEN = "hojas";

  var caja = document.getElementById("escaner");
  if (!caja) { return; }

  var expediente = caja.dataset.trabajador;
  var url = caja.dataset.url;
  var boton = document.getElementById("escaner-abrir");
  var panel = document.getElementById("escaner-panel");
  var video = document.getElementById("escaner-video");
  var tiras = document.getElementById("escaner-hojas");
  var conteo = document.getElementById("escaner-conteo");
  var aviso = document.getElementById("escaner-aviso");
  var pasoCaptura = document.getElementById("escaner-captura");
  var pasoGuardar = document.getElementById("escaner-guardar");
  var selectTipo = document.getElementById("escaner-tipo");
  var campoVence = document.getElementById("escaner-vence");
  var campoObs = document.getElementById("escaner-obs");
  var campoNombre = document.getElementById("escaner-nombre");
  var visor = document.querySelector(".escaner__visor");
  var guia = document.getElementById("escaner-guia");
  var botonAuto = document.getElementById("escaner-auto");

  var imagen = window.EscanerImagen;   // recorte y filtro (escaner-imagen.js)

  var flujo = null;      // MediaStream
  var hojas = [];        // {id, blob, url}
  var subiendo = false;

  // --- ¿Se muestra el botón? -------------------------------------------------
  // Solo en teléfono: en una computadora, arrastrar el archivo al formulario de
  // arriba es más rápido que sostener una hoja frente a la webcam.
  function esTelefono() {
    return window.matchMedia("(pointer: coarse)").matches
        && window.matchMedia("(max-width: 900px)").matches;
  }

  function hayCamara() {
    return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  }

  if (!esTelefono() || !hayCamara() || !window.EscanerImagen) { return; }
  caja.hidden = false;

  // --- Guardado local (IndexedDB) -------------------------------------------
  function abrirBase() {
    return new Promise(function (listo, falla) {
      var pedido = indexedDB.open(BD, 1);
      pedido.onupgradeneeded = function () {
        var bd = pedido.result;
        if (!bd.objectStoreNames.contains(ALMACEN)) {
          var almacen = bd.createObjectStore(ALMACEN, { keyPath: "id", autoIncrement: true });
          almacen.createIndex("expediente", "expediente");
        }
      };
      pedido.onsuccess = function () { listo(pedido.result); };
      pedido.onerror = function () { falla(pedido.error); };
    });
  }

  function conAlmacen(modo, tarea) {
    return abrirBase().then(function (bd) {
      return new Promise(function (listo, falla) {
        var tx = bd.transaction(ALMACEN, modo);
        var resultado = tarea(tx.objectStore(ALMACEN));
        tx.oncomplete = function () { listo(resultado && resultado.result); };
        tx.onerror = function () { falla(tx.error); };
      });
    });
  }

  function guardarHoja(blob) {
    return conAlmacen("readwrite", function (a) {
      return a.add({ expediente: expediente, blob: blob, creado: Date.now() });
    });
  }

  function olvidarHoja(id) {
    return conAlmacen("readwrite", function (a) { a.delete(id); });
  }

  function olvidarTodo() {
    return Promise.all(hojas.map(function (h) { return olvidarHoja(h.id); }));
  }

  function recuperarHojas() {
    return conAlmacen("readonly", function (a) {
      return a.index("expediente").getAll(expediente);
    }).then(function (guardadas) {
      (guardadas || []).forEach(function (g) { agregarALaTira(g.id, g.blob); });
    }).catch(function () { /* sin guardado local igual se puede escanear */ });
  }

  // --- El recuadro ES el recorte ---------------------------------------------
  // Se guarda lo que quede adentro y nada más. Antes se buscaba la hoja sola en
  // toda la foto y a veces se comía medio documento, sin forma de corregirlo.
  // Ahora el recorte se ve antes de disparar y se puede mover con el dedo.
  //
  // Se anota en fracciones (0 a 1) de lo que se ve en el visor, no en píxeles:
  // así sirve igual con la pantalla girada o con otra cámara.
  var MINIMO = 0.12;                   // que no se achique hasta desaparecer
  var LLAVE_MARCO = "gde-escaner-marco";
  var marco = { x: 0.06, y: 0.08, an: 0.88, al: 0.84 };

  try {
    var anotado = JSON.parse(localStorage.getItem(LLAVE_MARCO) || "null");
    if (anotado && anotado.an > MINIMO && anotado.al > MINIMO) { marco = anotado; }
  } catch (e) { /* si no se puede leer, se arranca con el de fábrica */ }

  function recordarMarco() {
    try { localStorage.setItem(LLAVE_MARCO, JSON.stringify(marco)); } catch (e) {}
  }

  function pintarMarco() {
    guia.style.left = (marco.x * 100) + "%";
    guia.style.top = (marco.y * 100) + "%";
    guia.style.width = (marco.an * 100) + "%";
    guia.style.height = (marco.al * 100) + "%";
  }

  function entre(v, minimo, maximo) {
    return v < minimo ? minimo : (v > maximo ? maximo : v);
  }

  // Arrastrar: adentro lo mueve, desde una esquina lo estira.
  function arrastrar(elemento, esquina) {
    elemento.addEventListener("pointerdown", function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      // Capturar el puntero mantiene el arrastre aunque el dedo se salga del
      // recuadro. No todos los navegadores lo aceptan siempre, y perderlo solo
      // significa un arrastre menos cómodo: no vale abortar por eso.
      try { elemento.setPointerCapture(ev.pointerId); } catch (e) {}
      var caja = visor.getBoundingClientRect();
      var desdeX = ev.clientX, desdeY = ev.clientY;
      var inicial = { x: marco.x, y: marco.y, an: marco.an, al: marco.al };
      // Corregir a mano manda: si la detección siguiera prendida, en un cuarto
      // de segundo devolvería el recuadro a donde estaba.
      if (automatico) { prenderAuto(false, true); }

      function mover(e) {
        var dx = (e.clientX - desdeX) / caja.width;
        var dy = (e.clientY - desdeY) / caja.height;
        if (!esquina) {
          marco.x = entre(inicial.x + dx, 0, 1 - inicial.an);
          marco.y = entre(inicial.y + dy, 0, 1 - inicial.al);
        } else {
          var i = esquina.indexOf("i") > 0;            // "ni"/"si": borde izquierdo
          var n = esquina.charAt(0) === "n";           // borde de arriba
          if (i) {
            var x = entre(inicial.x + dx, 0, inicial.x + inicial.an - MINIMO);
            marco.an = inicial.x + inicial.an - x;
            marco.x = x;
          } else {
            marco.an = entre(inicial.an + dx, MINIMO, 1 - inicial.x);
          }
          if (n) {
            var y = entre(inicial.y + dy, 0, inicial.y + inicial.al - MINIMO);
            marco.al = inicial.y + inicial.al - y;
            marco.y = y;
          } else {
            marco.al = entre(inicial.al + dy, MINIMO, 1 - inicial.y);
          }
        }
        pintarMarco();
      }

      function soltar() {
        elemento.removeEventListener("pointermove", mover);
        elemento.removeEventListener("pointerup", soltar);
        elemento.removeEventListener("pointercancel", soltar);
        recordarMarco();
      }

      elemento.addEventListener("pointermove", mover);
      elemento.addEventListener("pointerup", soltar);
      elemento.addEventListener("pointercancel", soltar);
    });
  }

  arrastrar(guia, null);
  Array.prototype.forEach.call(
    guia.querySelectorAll(".escaner__tirador"),
    function (t) { arrastrar(t, t.dataset.esquina); });
  pintarMarco();

  function medidas() {
    var caja = visor.getBoundingClientRect();
    return {
      caja: { ancho: caja.width, alto: caja.height },
      foto: { ancho: video.videoWidth, alto: video.videoHeight },
    };
  }

  function zonaDeLaFoto() {
    var m = medidas();
    return imagen.recuadroEnLaFoto(marco, m.caja, m.foto);
  }

  function fotoEntera() {
    var vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh) { return null; }
    var lienzo = document.createElement("canvas");
    lienzo.width = vw; lienzo.height = vh;
    lienzo.getContext("2d").drawImage(video, 0, 0);
    return lienzo;
  }

  /* --- La cámara busca la hoja sola ----------------------------------------
   *
   * Cada poco se mira lo que ve la cámara y se corre el recuadro hasta la
   * hoja. Se hace sobre una copia diminuta del cuadro —160 px de lado— y no
   * sobre la foto entera: buscar sobre 1920x1080 varias veces por segundo
   * calienta el teléfono y se come la batería, y para saber dónde está una
   * hoja blanca sobre una mesa oscura, 160 px sobran.
   *
   * El recuadro no salta: se acerca de a poco a lo que se encontró. Un salto
   * por cuadro haría temblar el marco con cualquier movimiento de la mano, y
   * costaría más encuadrar que hacerlo a dedo.
   */
  var AUTO_MS = 250;              // cuatro miradas por segundo alcanzan
  var AUTO_LADO = 160;            // lado mayor de la copia que se analiza
  var SUAVE = 0.35;               // cuánto se acerca el recuadro por vuelta
  var LLAVE_AUTO = "gde-escaner-auto";

  var automatico = localStorage.getItem(LLAVE_AUTO) !== "no";
  var reloj = null;
  var lienzoChico = document.createElement("canvas");

  function pintarBotonAuto() {
    botonAuto.setAttribute("aria-pressed", automatico ? "true" : "false");
    botonAuto.classList.toggle("escaner__auto--prendido", automatico);
    botonAuto.textContent = automatico ? "Detectando sola" : "Detectar sola";
    guia.classList.toggle("escaner__guia--auto", automatico);
  }

  function prenderAuto(si, contar) {
    automatico = si;
    try { localStorage.setItem(LLAVE_AUTO, si ? "si" : "no"); } catch (e) {}
    pintarBotonAuto();
    if (contar) {
      decir(si ? "La cámara busca la hoja sola."
               : "Detección apagada: el recuadro lo movés vos.");
    }
  }

  function unaMirada() {
    if (!automatico || panel.hidden || !flujo) { return; }
    var vw = video.videoWidth, vh = video.videoHeight;
    if (!vw || !vh) { return; }

    var escala = AUTO_LADO / Math.max(vw, vh);
    var ancho = Math.max(1, Math.round(vw * escala));
    var alto = Math.max(1, Math.round(vh * escala));
    if (lienzoChico.width !== ancho) { lienzoChico.width = ancho; }
    if (lienzoChico.height !== alto) { lienzoChico.height = alto; }

    var ctx = lienzoChico.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(video, 0, 0, ancho, alto);
    var hallado = imagen.buscarHoja(
      imagen.aGris(ctx.getImageData(0, 0, ancho, alto)), ancho, alto);
    // Cuando no se distingue nada, el recuadro se queda donde está. Abrirlo de
    // par en par sería peor que no hacer nada.
    if (!hallado.hallada) { return; }

    var m = medidas();
    var destino = imagen.recuadroEnPantalla(
      hallado, m.caja, { ancho: ancho, alto: alto });
    acercarMarcoA(destino);
  }

  function acercarMarcoA(destino) {
    function acercar(desde, hasta) { return desde + (hasta - desde) * SUAVE; }
    var x = entre(acercar(marco.x, destino.x), 0, 1 - MINIMO);
    var y = entre(acercar(marco.y, destino.y), 0, 1 - MINIMO);
    marco = {
      x: x, y: y,
      an: entre(acercar(marco.an, destino.an), MINIMO, 1 - x),
      al: entre(acercar(marco.al, destino.al), MINIMO, 1 - y),
    };
    pintarMarco();
  }

  function mirarSeguido(si) {
    if (reloj) { clearInterval(reloj); reloj = null; }
    if (si) { reloj = setInterval(unaMirada, AUTO_MS); }
  }

  botonAuto.addEventListener("click", function () { prenderAuto(!automatico, true); });
  pintarBotonAuto();

  // Con la pantalla apagada o la app de fondo, no hay nada que mirar.
  document.addEventListener("visibilitychange", function () {
    mirarSeguido(!document.hidden && !panel.hidden);
  });

  // --- Procesado de la foto --------------------------------------------------
  function capturar() {
    var lienzo = fotoEntera();
    if (!lienzo) { return Promise.reject(new Error("La cámara todavía no está lista.")); }
    var recorte = zonaDeLaFoto();

    // Se reescala al recortar: procesar 1800 px de lado es instantáneo, y
    // procesar los 4000 del sensor deja el teléfono trabado varios segundos.
    var escala = Math.min(1, LADO_MAXIMO / Math.max(recorte.ancho, recorte.alto));
    var salida = document.createElement("canvas");
    salida.width = Math.max(1, Math.round(recorte.ancho * escala));
    salida.height = Math.max(1, Math.round(recorte.alto * escala));
    var sctx = salida.getContext("2d");
    sctx.drawImage(lienzo, recorte.x, recorte.y, recorte.ancho, recorte.alto,
                   0, 0, salida.width, salida.height);

    var datos = sctx.getImageData(0, 0, salida.width, salida.height);
    sctx.putImageData(imagen.filtroEscaner(datos), 0, 0);

    return new Promise(function (listo) {
      salida.toBlob(function (blob) { listo(blob); }, "image/jpeg", CALIDAD);
    });
  }

  // --- Miniaturas ------------------------------------------------------------
  function agregarALaTira(id, blob) {
    var direccion = URL.createObjectURL(blob);
    hojas.push({ id: id, blob: blob, url: direccion });

    var item = document.createElement("div");
    item.className = "escaner__hoja";
    item.dataset.id = id;
    var img = document.createElement("img");
    img.src = direccion;
    img.alt = "";
    var quitar = document.createElement("button");
    quitar.type = "button";
    quitar.className = "escaner__quitar";
    quitar.setAttribute("aria-label", "Quitar esta hoja");
    quitar.textContent = "×";
    quitar.addEventListener("click", function () { quitarHoja(id); });
    item.appendChild(img);
    item.appendChild(quitar);
    tiras.appendChild(item);
    actualizarConteo();
  }

  function quitarHoja(id) {
    var i = hojas.findIndex(function (h) { return h.id === id; });
    if (i < 0) { return; }
    URL.revokeObjectURL(hojas[i].url);
    hojas.splice(i, 1);
    var item = tiras.querySelector('[data-id="' + id + '"]');
    if (item) { item.remove(); }
    olvidarHoja(id);
    actualizarConteo();
  }

  function actualizarConteo() {
    var n = hojas.length;
    conteo.textContent = n === 0 ? "Sin hojas todavía"
      : n + (n === 1 ? " hoja" : " hojas");
    document.getElementById("escaner-listo").disabled = n === 0;
  }

  function decir(texto, esError) {
    aviso.textContent = texto || "";
    aviso.hidden = !texto;
    aviso.classList.toggle("escaner__aviso--error", !!esError);
  }

  // --- Cámara ----------------------------------------------------------------
  function abrirCamara() {
    // `environment` pide la cámara trasera, que es la que enfoca de cerca.
    return navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" },
               width: { ideal: 1920 }, height: { ideal: 1080 } },
      audio: false,
    }).then(function (f) {
      flujo = f;
      video.srcObject = f;
      return video.play();
    });
  }

  function cerrarCamara() {
    mirarSeguido(false);
    if (flujo) {
      flujo.getTracks().forEach(function (t) { t.stop(); });
      flujo = null;
    }
    video.srcObject = null;
  }

  // --- Trabar el fondo sin perder el lugar ----------------------------------
  // El escáner está al final de un expediente largo: para llegar hay que bajar
  // bastante. Trabar la página con `position: fixed` la manda arriba de todo,
  // así que se anota a qué altura estaba y se la devuelve ahí al cerrar.
  var alturaGuardada = 0;

  function trabarFondo() {
    alturaGuardada = window.pageYOffset || document.documentElement.scrollTop || 0;
    document.body.style.top = "-" + alturaGuardada + "px";
    document.body.classList.add("sin-scroll");
  }

  function soltarFondo() {
    document.body.classList.remove("sin-scroll");
    document.body.style.top = "";
    window.scrollTo(0, alturaGuardada);
  }

  function abrir() {
    trabarFondo();
    panel.hidden = false;
    mostrarPaso("captura");
    decir("");
    mirarSeguido(true);        // buscar la hoja mientras el panel esté abierto
    abrirCamara().catch(function (e) {
      decir(e && e.name === "NotAllowedError"
        ? "No diste permiso para usar la cámara. Habilitalo en el navegador y volvé a intentar."
        : "No se pudo abrir la cámara en este teléfono.", true);
    });
    recuperarHojas();
  }

  function cerrar() {
    cerrarCamara();
    panel.hidden = true;
    soltarFondo();
  }

  function mostrarPaso(cual) {
    pasoCaptura.hidden = cual !== "captura";
    pasoGuardar.hidden = cual !== "guardar";
  }

  // --- Subida ----------------------------------------------------------------
  function subir() {
    if (subiendo) { return; }
    if (!selectTipo.value) { decir("Elegí qué documento es.", true); return; }

    subiendo = true;
    decir("Subiendo…");
    var datos = new FormData();
    datos.append("csrfmiddlewaretoken", caja.dataset.csrf);
    datos.append("tipo", selectTipo.value);
    datos.append("nombre", campoNombre.value || "");
    datos.append("fecha_vencimiento", campoVence.value || "");
    datos.append("observaciones", campoObs.value || "");
    hojas.forEach(function (h, i) {
      datos.append("paginas", h.blob, "hoja-" + (i + 1) + ".jpg");
    });

    fetch(url, { method: "POST", body: datos, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, cuerpo: j }; }); })
      .then(function (r) {
        if (!r.ok || !r.cuerpo.ok) {
          throw new Error(r.cuerpo.error || "No se pudo guardar el documento.");
        }
        // Recién se borra el guardado local cuando el servidor confirmó: si
        // falla la subida, las hojas siguen ahí para reintentar.
        return olvidarTodo().then(function () { window.location.reload(); });
      })
      .catch(function (e) {
        subiendo = false;
        decir(e.message || "No se pudo guardar el documento.", true);
      });
  }

  // --- Cableado --------------------------------------------------------------
  boton.addEventListener("click", abrir);
  document.getElementById("escaner-cerrar").addEventListener("click", cerrar);

  document.getElementById("escaner-disparar").addEventListener("click", function () {
    decir("");
    capturar()
      .then(function (blob) { return guardarHoja(blob).then(function (id) {
        agregarALaTira(id || Date.now(), blob);
      }); })
      .catch(function (e) { decir(e.message || "No se pudo tomar la foto.", true); });
  });

  document.getElementById("escaner-listo").addEventListener("click", function () {
    cerrarCamara();          // se apaga la cámara mientras se completan los datos
    mostrarPaso("guardar");
    decir("");
  });

  document.getElementById("escaner-volver").addEventListener("click", function () {
    mostrarPaso("captura");
    decir("");
    abrirCamara().catch(function () { decir("No se pudo volver a abrir la cámara.", true); });
  });

  document.getElementById("escaner-subir").addEventListener("click", subir);

  // Salir del expediente con la cámara prendida deja la luz encendida.
  window.addEventListener("pagehide", cerrarCamara);
})();
