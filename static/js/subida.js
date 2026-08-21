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
 * El tamano se revisa ACA, antes de mandar nada. Con la conexion de una tienda,
 * enterarse a los diez minutos de que el archivo era muy grande es la
 * diferencia entre un aviso y una tarde perdida. El servidor igual lo vuelve a
 * revisar: esto es la comodidad, no la seguridad.
 */
(function () {
  "use strict";

  var formulario = document.getElementById("subir-documento");
  if (!formulario) { return; }

  var campo = formulario.querySelector('input[type="file"]');
  var boton = formulario.querySelector('button[type="submit"]');
  var tope = parseInt(formulario.dataset.maxBytes, 10) || 0;
  var textoBoton = boton ? boton.textContent : "";

  // El cartel de progreso se arma acá y no en la plantilla: si el navegador no
  // corre este archivo, el formulario tiene que seguir andando como siempre, y
  // un cartel vacío colgado en la pantalla no ayudaría a nadie.
  var panel = document.createElement("div");
  panel.className = "subida";
  panel.hidden = true;
  panel.innerHTML =
    '<div class="subida__texto"><span class="subida__estado">Subiendo…</span>'
    + '<span class="subida__porcentaje"></span></div>'
    + '<div class="barra"><span style="width:0%"></span></div>'
    + '<div class="pequeno mut subida__aviso">No cierres esta pantalla hasta que termine.</div>';
  formulario.appendChild(panel);

  var estado = panel.querySelector(".subida__estado");
  var porcentaje = panel.querySelector(".subida__porcentaje");
  var relleno = panel.querySelector(".barra > span");
  var aviso = panel.querySelector(".subida__aviso");

  function mb(n) { return (n / 1024 / 1024).toFixed(1).replace(".", ",") + " MB"; }

  function error(texto) {
    panel.hidden = false;
    panel.classList.add("subida--mal");
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

  function avisarSiPesaDemasiado() {
    if (!campo || !tope || !campo.files || !campo.files.length) { return true; }
    var archivo = campo.files[0];
    if (archivo.size <= tope) {
      panel.hidden = true;
      panel.classList.remove("subida--mal");
      return true;
    }
    error("Ese archivo pesa " + mb(archivo.size) + " y el máximo es " + mb(tope)
          + ". Volvé a escanearlo con menos calidad, o subilo partido.");
    return false;
  }

  // Se avisa al elegir el archivo, no al enviar: es el momento en que todavía
  // no se subió nada y la persona tiene el archivo a mano para cambiarlo.
  if (campo) {
    campo.addEventListener("change", avisarSiPesaDemasiado);
  }

  formulario.addEventListener("submit", function (evento) {
    if (!avisarSiPesaDemasiado()) {
      evento.preventDefault();
      return;
    }
    // Sin estas dos, no hay forma de saber cuánto lleva subido: que ande el
    // envío de toda la vida, con el botón trabado, es mejor que no andar.
    if (!window.XMLHttpRequest || !window.FormData) {
      trabar();
      panel.hidden = false;
      porcentaje.textContent = "";
      return;
    }

    evento.preventDefault();
    trabar();
    panel.hidden = false;
    panel.classList.remove("subida--mal");
    aviso.hidden = false;
    estado.textContent = "Subiendo…";
    relleno.style.width = "0%";
    porcentaje.textContent = "0%";

    var pedido = new XMLHttpRequest();
    pedido.open("POST", formulario.action, true);
    pedido.setRequestHeader("X-Requested-With", "XMLHttpRequest");

    pedido.upload.addEventListener("progress", function (e) {
      if (!e.lengthComputable) { return; }
      var cuanto = Math.round((e.loaded / e.total) * 100);
      relleno.style.width = cuanto + "%";
      porcentaje.textContent = cuanto + "%";
      if (cuanto >= 100) {
        // Subido no es guardado: falta cifrarlo y escribirlo. Si acá dijera
        // "100%" y nada más, parecería colgado justo al final.
        estado.textContent = "Guardando el documento…";
        porcentaje.textContent = "";
      }
    });

    pedido.addEventListener("load", function () {
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

    pedido.send(new FormData(formulario));
  });
})();
