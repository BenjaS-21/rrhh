/* Procesado de la foto: buscar la hoja y dejarla como fotocopia.
 *
 * Son funciones puras sobre píxeles, sin cámara ni pantalla. Viven aparte de
 * `escaner.js` justamente por eso: se pueden ejercitar en un navegador común,
 * que es la única forma de comprobar que el recorte y el filtro hacen lo que
 * dicen.
 */
(function (global) {
  "use strict";

  function aGris(datos) {
    var gris = new Uint8ClampedArray(datos.width * datos.height);
    var px = datos.data;
    for (var i = 0, j = 0; i < px.length; i += 4, j++) {
      gris[j] = (px[i] * 299 + px[i + 1] * 587 + px[i + 2] * 114) / 1000;
    }
    return gris;
  }

  function buscarHoja(gris, ancho, alto) {
    /* Devuelve el recuadro de la hoja dentro del encuadre.
     *
     * La hoja es lo claro sobre un fondo más oscuro (el escritorio, el piso).
     * Se marca cada píxel como claro u oscuro y se busca la franja de filas y
     * de columnas donde la mayoría es clara. No reconoce las esquinas ni
     * endereza la perspectiva: recorta un rectángulo derecho, que es lo que
     * sirve cuando la foto se saca más o menos de frente.
     */
    var suma = 0, i;
    for (i = 0; i < gris.length; i++) { suma += gris[i]; }
    var promedio = suma / gris.length;
    var corte = promedio + (255 - promedio) * 0.25;

    var porFila = new Float32Array(alto);
    var porColumna = new Float32Array(ancho);
    for (var y = 0; y < alto; y++) {
      for (var x = 0; x < ancho; x++) {
        if (gris[y * ancho + x] > corte) { porFila[y]++; porColumna[x]++; }
      }
    }

    /* El corte se mide contra la fila más clara que haya, no contra el ancho
       de la foto. Pedir "más de la mitad de la fila" da por sentado que la
       hoja cruza la pantalla entera: una cédula, un carnet o una hoja sacada
       desde un poco más lejos nunca llegan a la mitad, y entonces el recorte
       agarraba cualquier cosa y se comía parte del documento. */
    function franja(cuentas, largo) {
      var maximo = 0, k;
      for (k = 0; k < largo; k++) {
        if (cuentas[k] > maximo) { maximo = cuentas[k]; }
      }
      var minimo = maximo * 0.6, desde = 0, hasta = largo - 1;
      while (desde < largo && cuentas[desde] < minimo) { desde++; }
      while (hasta > desde && cuentas[hasta] < minimo) { hasta--; }
      return [desde, hasta];
    }

    var v = franja(porFila, alto);
    var h = franja(porColumna, ancho);

    /* `hallada` dice si de verdad se distinguió una hoja del fondo, o si esto
       es el encuadre entero por no haber encontrado nada. La diferencia
       importa cuando se busca en vivo, muchas veces por segundo: sin ella, la
       vez que no encuentra nada se lee como "la hoja ocupa toda la pantalla" y
       el recuadro se abre de golpe cada vez que la cámara se mueve. */
    var altoHoja = v[1] - v[0], anchoHoja = h[1] - h[0];
    var muyChica = altoHoja < alto * 0.25 || anchoHoja < ancho * 0.25;
    /* Ocupar el cuadro entero no es haber encontrado una hoja: es lo que pasa
       cuando no hay nada que distinguir —la cámara apuntando a una pared, a la
       mesa sola, o tapada—. Ahí todas las filas son igual de claras y la franja
       sale de borde a borde. Dicho como hallazgo, el recuadro se abría de par
       en par cada vez que la cámara perdía la hoja de vista. */
    var ocupaTodo = altoHoja >= alto * 0.97 && anchoHoja >= ancho * 0.97;
    if (muyChica || ocupaTodo) {
      return { x: 0, y: 0, ancho: ancho, alto: alto, hallada: false };
    }
    var margen = Math.round(Math.min(ancho, alto) * 0.01);
    var x0 = Math.max(0, h[0] - margen), y0 = Math.max(0, v[0] - margen);
    var x1 = Math.min(ancho - 1, h[1] + margen), y1 = Math.min(alto - 1, v[1] + margen);
    return { x: x0, y: y0, ancho: x1 - x0 + 1, alto: y1 - y0 + 1, hallada: true };
  }

  function filtroEscaner(datos) {
    /* Deja la hoja como fotocopia: fondo blanco parejo y letra negra.
     *
     * Se estima la iluminación con un desenfoque grande y se divide la imagen
     * por ella. Eso borra la sombra de la mano y el degradé del foco, que es
     * lo que más delata que la "hoja escaneada" era una foto. Un umbral fijo,
     * en cambio, dejaría media hoja en negro.
     *
     * El desenfoque se calcula con una imagen integral: el costo no depende
     * del radio, así que en un teléfono corre igual de rápido.
     */
    var ancho = datos.width, alto = datos.height;
    var gris = aGris(datos);

    var integral = new Float64Array((ancho + 1) * (alto + 1));
    for (var y = 0; y < alto; y++) {
      var fila = 0;
      for (var x = 0; x < ancho; x++) {
        fila += gris[y * ancho + x];
        integral[(y + 1) * (ancho + 1) + (x + 1)] =
          integral[y * (ancho + 1) + (x + 1)] + fila;
      }
    }

    function media(x0, y0, x1, y1) {
      var a = integral[y0 * (ancho + 1) + x0];
      var b = integral[y0 * (ancho + 1) + x1];
      var c = integral[y1 * (ancho + 1) + x0];
      var d = integral[y1 * (ancho + 1) + x1];
      return (d - b - c + a) / ((x1 - x0) * (y1 - y0));
    }

    var radio = Math.max(8, Math.round(Math.min(ancho, alto) / 12));
    var px = datos.data;
    for (var yy = 0; yy < alto; yy++) {
      var y0 = Math.max(0, yy - radio), y1 = Math.min(alto, yy + radio + 1);
      for (var xx = 0; xx < ancho; xx++) {
        var x0 = Math.max(0, xx - radio), x1 = Math.min(ancho, xx + radio + 1);
        var fondo = media(x0, y0, x1, y1) || 1;
        // 1.0 = igual que su entorno (papel) -> blanco. Menos = tinta.
        var relativo = gris[yy * ancho + xx] / fondo;
        var valor = (relativo - 0.82) / 0.18 * 255;   // curva de contraste
        valor = valor < 0 ? 0 : (valor > 255 ? 255 : valor);
        var i = (yy * ancho + xx) * 4;
        px[i] = px[i + 1] = px[i + 2] = valor;
        px[i + 3] = 255;
      }
    }
    return datos;
  }

  /* De la pantalla a la foto y de vuelta.
   *
   * El video se muestra con `object-fit: cover`: llena el visor y le sobra por
   * los costados o por arriba, así que lo que se ve NO es toda la foto. El
   * recuadro vive en fracciones de lo que se ve (0 a 1); estas dos funciones
   * lo pasan a píxeles de la foto y al revés.
   *
   * Están acá, y no en `escaner.js`, porque es la cuenta que decide qué queda
   * adentro del documento: si está corrida, se guarda un pedazo equivocado sin
   * que nada avise. Acá se puede comprobar sola, sin cámara.
   */
  function _tapado(caja, foto) {
    var escala = Math.max(caja.ancho / foto.ancho, caja.alto / foto.alto);
    return {
      escala: escala,
      sobraX: (foto.ancho * escala - caja.ancho) / 2,
      sobraY: (foto.alto * escala - caja.alto) / 2,
    };
  }

  function recuadroEnLaFoto(marco, caja, foto) {
    var t = _tapado(caja, foto);
    function fijar(v, maximo) { return v < 0 ? 0 : (v > maximo ? maximo : v); }

    var x = fijar((t.sobraX + marco.x * caja.ancho) / t.escala, foto.ancho - 1);
    var y = fijar((t.sobraY + marco.y * caja.alto) / t.escala, foto.alto - 1);
    return {
      x: Math.round(x),
      y: Math.round(y),
      ancho: Math.max(1, Math.round(Math.min(marco.an * caja.ancho / t.escala,
                                             foto.ancho - x))),
      alto: Math.max(1, Math.round(Math.min(marco.al * caja.alto / t.escala,
                                            foto.alto - y))),
    };
  }

  function recuadroEnPantalla(zona, caja, foto) {
    var t = _tapado(caja, foto);
    return {
      x: (zona.x * t.escala - t.sobraX) / caja.ancho,
      y: (zona.y * t.escala - t.sobraY) / caja.alto,
      an: zona.ancho * t.escala / caja.ancho,
      al: zona.alto * t.escala / caja.alto,
    };
  }

  global.EscanerImagen = {
    aGris: aGris,
    buscarHoja: buscarHoja,
    filtroEscaner: filtroEscaner,
    recuadroEnLaFoto: recuadroEnLaFoto,
    recuadroEnPantalla: recuadroEnPantalla,
  };
})(window);
