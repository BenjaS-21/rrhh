"""Las pruebas no pueden depender del `.env` de la máquina donde corren.

Salió a la luz al endurecer el servidor. Este equipo es el servidor: tiene el
`.env` de producción, con `DJANGO_SECURE_COOKIES=1`. Apenas se puso, 500 de 636
pruebas empezaron a fallar, y ninguna por un error del sistema: el cliente de
pruebas habla por HTTP, así que `SECURE_SSL_REDIRECT` le contestaba 301 a todo
y las cookies marcadas como seguras no volvían nunca.

El defecto de fondo no era esa variable sino que el resultado del suite cambiara
según cómo estuviera configurada la máquina. Una prueba que pasa en la laptop de
uno y falla en la de otro no prueba nada, y peor todavía: acá el suite entero se
habría vuelto inservible justo cuando hacía falta para verificar el
endurecimiento.

Así que las pruebas fijan lo que tienen que fijar. Lo demás sigue viniendo del
`.env`, como antes.
"""

from django.test.runner import DiscoverRunner

# Lo que se pone en producción y el cliente de pruebas no puede cumplir, porque
# habla por HTTP plano contra un servidor de mentira.
COMO_SI_FUERA_HTTP = {
    # Devolvía 301 a cada pedido: ninguna vista llegaba a ejecutarse.
    "SECURE_SSL_REDIRECT": False,
    # El cliente no guarda cookies marcadas como seguras sobre HTTP: sin esto
    # no hay forma de iniciar sesión y todo lo que requiere permisos se cae.
    "SESSION_COOKIE_SECURE": False,
    "CSRF_COOKIE_SECURE": False,
    # No aporta nada a una prueba y ensucia las cabeceras que sí se revisan.
    "SECURE_HSTS_SECONDS": 0,
}


class Corredor(DiscoverRunner):
    """El de siempre, con la configuración de transporte pinchada.

    Se cambia en `setup_test_environment`, antes de que se arme el primer
    cliente: `SecurityMiddleware` lee estos valores una sola vez, al cargarse.
    """

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        from django.conf import settings
        self._anterior = {}
        for nombre, valor in COMO_SI_FUERA_HTTP.items():
            self._anterior[nombre] = getattr(settings, nombre, None)
            setattr(settings, nombre, valor)

    def teardown_test_environment(self, **kwargs):
        from django.conf import settings
        for nombre, valor in getattr(self, "_anterior", {}).items():
            setattr(settings, nombre, valor)
        super().teardown_test_environment(**kwargs)
