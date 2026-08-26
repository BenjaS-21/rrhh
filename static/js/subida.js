/* Subir un documento sin quedarse mirando una pantalla quieta.
 *
 * Un formulario normal, al enviarse, no muestra nada: el navegador se queda
 * cargando y la persona no sabe si esta subiendo, si se colgo, o si le tiene
 * que dar de nuevo al boton. Darle de nuevo era lo peor que podia pasar: cada
 * click arrancaba otra subida y el servidor terminaba cifrando dos archivos a
 * la vez.
 *
 * Asi que se manda con XMLHttpRequest, que si avisa cuanto lleva subido, y
 * mientras tanto el boton queda trabado.
 *
 * El tamano se mira ACA, antes de mandar nada, pero NO para rechazar: desde
 * que el servidor cifra por bloques, un archivo pesado entra igual. Lo que se
 * hace aca es OFRECER comprimirlo —"Comprimir aqui y subir"— porque en la
 * conexion de una tienda, un escaneo de 25 MB comprimido a 5 MB es la
 * diferencia entre un rato y una tarde:
 * - las IMAGENES se comprimen en el navegador (canvas + JPEG), sin subir nada;
 * - los PDF (y los TIFF, que el navegador no sabe abrir) se suben una sola vez
 *   a la ruta de compresion y el servidor devuelve el documento ya guardado.
 * Quien no quiera comprimir le da a Subir y listo: el archivo viaja tal cual.
 */
(function () {
  "use strict";

  var formulario = document.getElementById("subir-documento");
  if (!formulario) { return; }

  var campo = formulario.querySelector('input[type="file"]');
  var boton = formulario.querySelector('button[type="submit"]');
  var tope = parseInt(formulario.dataset.maxBytes, 10) || 0;
  var urlCompresion = formulario.dataset.comprimirUrl || "";
  var textoBoton = boton ? boton.textContent : "";

  // El archivo ya comprimido, listo para reemplazar al original en el envio.
  var comprimido = null;

  // El cartel de progreso se arma acá y no en la plantilla: si el navegador no
  // corre este archivo, el formulario tiene que seguir andando como siempre, y
  // un cartel vacío colgado en la pantalla no ayudaría a nadie.
  var panel = document.createElement("div");
  panel.className = "subida";
  panel.hidden = true;
  panel.innerHTML =
    '<div class="subida__texto"><span class="subida__rueda" hidden></span>'
    + '<span class="subida__estado">Subiendo…</span>'
    + '<span class="subida__porcentaje"></span></div>'
    + '<div class="barra"><span style="width:0%"></span></div>'
    + '<button type="button" class="btn subida__comprimir" hidden></button>'
    + '<div class="pequeno mut subida__aviso">No cierres esta pantalla hasta que termine.</div>';
  formulario.appendChild(panel);

  var estado = panel.querySelector(".subida__estado");
  var rueda = panel.querySelector(".subida__rueda");
  var porcentaje = panel.querySelector(".subida__porcentaje");
  var relleno = panel.querySelector(".barra > span");
  var botonComprimir = panel.querySelector(".subida__comprimir");
  var aviso = panel.querySelector(".subida__aviso");

  function mb(n) { return (n / 1024 / 1024).toFixed(1).replace(".", ",") + " MB"; }

  function extensionDe(nombre) {
    var m = /\.([a-z0-9]+)$/i.exec(nombre || "");
    return m ? m[1].toLowerCase() : "";
  }

  function error(texto) {
    panel.hidden = false;
    panel.classList.add("subida--mal");
    panel.classList.remove("subida--procesando");
    rueda.hidden = true;
    estado.textContent = texto;
    porcentaje.textContent = "";
    relleno.style.width = "0%";
    aviso.hidden = true;
    soltar();
  }

  function trabar() {
    if (boton) { boton.disabled = true; boton.textContent = "Subiendo…"; }
  }

  function soltar() {
    if (boton) { boton.disabled = false; boton.textContent = textoBoton; }
  }

  // --- Compresion local de imagenes ---------------------------------------
  // Una hoja legible no necesita mas que 2500 px de lado largo; a partir de
  // ahi se baja la calidad JPEG y, si no alcanza, tambien las dimensiones.
  function comprimirImagen(archivo, hecho, fallo) {
    var url = URL.createObjectURL(archivo);
    var img = new Image();
    img.onload = function () {
      URL.revokeObjectURL(url);
      var escala = Math.min(1, 2500 / Math.max(img.width, img.height));
      var calidades = [0.85, 0.70, 0.55];
      (function intentar(cal, esc) {
        var w = Math.max(1, Math.round(img.width * esc));
        var h = Math.max(1, Math.round(img.height * esc));
        var canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        canvas.getContext("2d").drawImage(img, 0, 0, w, h);
        canvas.toBlob(function (blob) {
          if (!blob) { fallo(); return; }
          if (blob.size <= tope) { hecho(blob); return; }
          if (cal + 1 < calidades.length) { intentar(cal + 1, esc); return; }
          if (esc > 0.35) { intentar(0, esc * 0.7); return; }
          fallo();
        }, "image/jpeg", calidades[cal]);
      })(0, escala);
    };
    img.onerror = function () { URL.revokeObjectURL(url); fallo(); };
    img.src = url;
  }

  // --- Envio por XHR (subida normal o a la ruta de compresion) -------------
  function enviar(destino, datos) {
    trabar();
    panel.hidden = false;
    panel.classList.remove("subida--mal");
    panel.classList.remove("subida--procesando");
    rueda.hidden = false;
    botonComprimir.hidden = true;
    aviso.hidden = false;
    estado.textContent = "Subiendo…";
    relleno.style.width = "0%";
    porcentaje.textContent = "0%";

    var pedido = new XMLHttpRequest();
    pedido.open("POST", destino, true);
    pedido.setRequestHeader("X-Requested-With", "XMLHttpRequest");

    pedido.upload.addEventListener("progress", function (e) {
      if (!e.lengthComputable) { return; }
      var cuanto = Math.round((e.loaded / e.total) * 100);
      relleno.style.width = cuanto + "%";
      porcentaje.textContent = cuanto + "%";
      if (cuanto >= 100) {
        // Subido no es guardado: falta comprimir, cifrar y escribir. Si aca
        // dijera "100%" y nada mas, pareceria colgado justo al final. La barra
        // pasa a vaiven y la rueda sigue: se ve que el servidor esta trabajando.
        panel.classList.add("subida--procesando");
        estado.textContent = destino === urlCompresion
          ? "Comprimiendo el documento en el servidor…"
          : "Guardando el documento…";
        porcentaje.textContent = "";
      }
    });

    pedido.addEventListener("load", function () {
      if (destino === urlCompresion) {
        // La ruta de compresion responde JSON; el mensaje de exito queda
        // guardado en la sesion y se ve al recargar el expediente.
        var respuesta = {};
        try { respuesta = JSON.parse(pedido.responseText) || {}; } catch (e) {}
        if (pedido.status >= 200 && pedido.status < 300 && respuesta.ok) {
          window.location.reload();
          return;
        }
        error(respuesta.error || ("No se pudo comprimir (error " + pedido.status + ")."));
        return;
      }
      if (pedido.status >= 200 && pedido.status < 400) {
        // La vista redirige al expediente; el navegador ya siguió el redirect,
        // así que `responseURL` es la pantalla a la que hay que ir.
        window.location = pedido.responseURL || window.location.href;
        return;
      }
      var detalle = "";
      try { detalle = (JSON.parse(pedido.responseText) || {}).error || ""; } catch (e) {}
      error(detalle || ("No se pudo subir el documento (error " + pedido.status + ")."));
    });

    pedido.addEventListener("error", function () {
      error("Se cortó la conexión mientras subía. Probá de nuevo.");
    });

    pedido.addEventListener("abort", function () {
      error("Se canceló la subida.");
    });

    pedido.send(datos);
  }

  // --- El cartel cuando el archivo pasa del tope ---------------------------
  // No es un error (rojo no): es una sugerencia. El archivo entra igual.
  function ofrecerCompresion(archivo) {
    var ext = extensionDe(archivo.name);
    var esImagenLocal = ["jpg", "jpeg", "png", "webp"].indexOf(ext) !== -1;
    panel.hidden = false;
    panel.classList.remove("subida--mal");
    relleno.style.width = "0%";
    porcentaje.textContent = "";
    aviso.hidden = true;
    rueda.hidden = true;
    estado.textContent = "Ese archivo pesa " + mb(archivo.size)
      + ". Se sube igual, pero comprimido tardaría menos.";
    botonComprimir.hidden = false;
    botonComprimir.textContent = esImagenLocal
      ? "🗜 Comprimir aquí antes de subir"
      : "🗜 Comprimir en el servidor antes de subir";

    botonComprimir.onclick = function () {
      botonComprimir.disabled = true;
      if (esImagenLocal) {
        estado.textContent = "Comprimiendo la imagen…";
        panel.classList.remove("subida--mal");
        rueda.hidden = false;
        comprimirImagen(archivo, function (blob) {
          var nombre = archivo.name.replace(/\.[a-z0-9]+$/i, "") + ".jpg";
          comprimido = new File([blob], nombre, { type: "image/jpeg" });
          rueda.hidden = true;
          estado.textContent = "Lista: quedó en " + mb(blob.size)
            + ". Dale a «Subir documento».";
          botonComprimir.hidden = true;
          botonComprimir.disabled = false;
        }, function () {
          botonComprimir.disabled = false;
          error("No se pudo comprimir la imagen. Probá escanearla con menos "
                + "calidad o subila como PDF.");
        });
        return;
      }
      // PDF y TIFF: los comprime el servidor; el archivo viaja una sola vez.
      botonComprimir.disabled = false;
      enviar(urlCompresion, new FormData(formulario));
    };
  }

  function avisarSiPesaDemasiado() {
    // Avisa y ofrece comprimir, pero NUNCA frena la subida: pese lo que pese,
    // el archivo entra. El techo absoluto lo pone el middleware del servidor.
    if (!campo || !tope || !campo.files || !campo.files.length) { return; }
    var archivo = campo.files[0];
    if (archivo.size <= tope) {
      panel.hidden = true;
      panel.classList.remove("subida--mal");
      botonComprimir.hidden = true;
      comprimido = null;
      return;
    }
    if (comprimido) { return; }
    ofrecerCompresion(archivo);
  }

  // Se avisa al elegir el archivo, no al enviar: es el momento en que todavía
  // no se subió nada y la persona tiene el archivo a mano para cambiarlo.
  if (campo) {
    campo.addEventListener("change", function () {
      // Lo comprimido vale solo para el archivo elegido en ese momento.
      comprimido = null;
      avisarSiPesaDemasiado();
    });
  }

  formulario.addEventListener("submit", function (evento) {
    // Sin estas dos, no hay forma de saber cuánto lleva subido: que ande el
    // envío de toda la vida, con el botón trabado, es mejor que no andar.
    if (!window.XMLHttpRequest || !window.FormData) {
      trabar();
      panel.hidden = false;
      porcentaje.textContent = "";
      return;
    }

    evento.preventDefault();
    var datos = new FormData(formulario);
    if (comprimido) {
      datos.set("archivo", comprimido, comprimido.name);
    }
    enviar(formulario.action, datos);
  });
})();
