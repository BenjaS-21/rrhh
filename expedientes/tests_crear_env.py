"""`crear_env.bat`: arma el archivo de claves, y sobre todo no pisa el que hay.

Lo que más importa no es que sepa crear el archivo, sino que sepa NO crearlo.
Con `DOCUMENTOS_ENCRYPTION_KEY` se cifran los documentos en disco: si el script
reemplazara un `.env` existente por uno con clave nueva, todo lo ya subido
quedaría ilegible para siempre, sin aviso y sin vuelta atrás.

Se ejecuta el `.bat` de verdad, en una carpeta de paso, porque es la única
forma de saber qué escribe. Fuera de Windows la clase se saltea.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BAT = Path(settings.BASE_DIR) / "crear_env.bat"


def _leer(carpeta):
    """El .env como diccionario, ignorando comentarios y renglones vacíos."""
    valores = {}
    texto = (carpeta / ".env").read_text(encoding="utf-8", errors="replace")
    for linea in texto.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        nombre, _, valor = linea.partition("=")
        valores[nombre.strip()] = valor.strip()
    return valores


@unittest.skipUnless(sys.platform == "win32", "El .bat solo corre en Windows.")
class CrearEnv(SimpleTestCase):

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp(prefix="gde-env-"))
        shutil.copy(BAT, self.carpeta / "crear_env.bat")
        self.addCleanup(shutil.rmtree, self.carpeta, ignore_errors=True)

    def correr(self, respuesta="", *argumentos):
        """Ejecuta el .bat. `respuesta` es lo que se tipea si pregunta algo."""
        return subprocess.run(
            ["cmd", "/c", str(self.carpeta / "crear_env.bat"), *argumentos],
            cwd=self.carpeta, input=respuesta + "\r\n",
            capture_output=True, timeout=120,
            encoding="cp1252", errors="replace",
            # `pause` espera una tecla: con stdin cerrado sigue de largo.
            env={**os.environ},
        )

    # --- Modo servidor --------------------------------------------------------
    def test_en_modo_servidor_no_deja_las_trazas_de_error_a_la_vista(self):
        """El .env del servidor no puede salir igual que el de una laptop.

        Con DEBUG=1 sobre una direccion publica, cualquiera que provoque un
        error ve las rutas, la configuracion y las consultas del sistema. Que
        el propio script lo deje bien evita depender de que alguien se acuerde
        de editarlo a mano despues de instalar.
        """
        self.correr("", "servidor")
        valores = _leer(self.carpeta)
        self.assertEqual(valores["DJANGO_DEBUG"], "0")
        self.assertEqual(valores["DJANGO_SECURE_COOKIES"], "1")

    def test_sin_argumento_sigue_siendo_una_maquina_de_desarrollo(self):
        """Testigo: es para lo que se usa casi siempre, y ahi las trazas ayudan."""
        self.correr()
        valores = _leer(self.carpeta)
        self.assertEqual(valores["DJANGO_DEBUG"], "1")
        self.assertEqual(valores["DJANGO_SECURE_COOKIES"], "0")

    def test_avisa_en_que_modo_quedo(self):
        """Si no lo dice, no hay forma de saber cual de los dos corrio."""
        self.assertIn("servidor", self.correr("", "servidor").stdout)

    # --- Crear de cero --------------------------------------------------------
    def test_escribe_el_archivo_con_todo_lo_que_settings_lee(self):
        self.correr()
        valores = _leer(self.carpeta)
        for nombre in ("DJANGO_SECRET_KEY", "DJANGO_DEBUG", "DJANGO_ALLOWED_HOSTS",
                       "DJANGO_CSRF_TRUSTED_ORIGINS", "DJANGO_SITE_URL",
                       "DOCUMENTOS_ENCRYPTION_KEY", "DJANGO_SECURE_COOKIES"):
            with self.subTest(variable=nombre):
                self.assertIn(nombre, valores)

    def test_las_claves_salen_generadas_y_no_de_ejemplo(self):
        self.correr()
        valores = _leer(self.carpeta)
        self.assertGreater(len(valores["DJANGO_SECRET_KEY"]), 40)
        self.assertNotIn("cambiame", valores["DJANGO_SECRET_KEY"].lower())
        self.assertNotIn("insecure", valores["DJANGO_SECRET_KEY"].lower())

    def test_la_clave_de_cifrado_sirve_para_cifrar(self):
        """No alcanza con que haya texto: Fernet la rechaza si no mide justo."""
        from cryptography.fernet import Fernet
        self.correr()
        clave = _leer(self.carpeta)["DOCUMENTOS_ENCRYPTION_KEY"]
        f = Fernet(clave.encode())
        self.assertEqual(f.decrypt(f.encrypt(b"una cedula")), b"una cedula")

    def test_dos_instalaciones_no_comparten_claves(self):
        """Testigo: si estuvieran escritas a mano, esto pasaría igual y el
        archivo no tendría ningún secreto de verdad."""
        self.correr()
        primero = _leer(self.carpeta)
        (self.carpeta / ".env").unlink()
        self.correr()
        segundo = _leer(self.carpeta)
        self.assertNotEqual(primero["DJANGO_SECRET_KEY"], segundo["DJANGO_SECRET_KEY"])
        self.assertNotEqual(primero["DOCUMENTOS_ENCRYPTION_KEY"],
                            segundo["DOCUMENTOS_ENCRYPTION_KEY"])

    def test_dotenv_lo_lee_igual_que_lo_leeria_django(self):
        """Se escribe con `echo` de Windows: si quedara mal armado, Django
        arrancaría con las claves vacías y sin decir nada."""
        from dotenv import dotenv_values
        self.correr()
        leido = dotenv_values(self.carpeta / ".env")
        self.assertEqual(leido["DOCUMENTOS_ENCRYPTION_KEY"],
                         _leer(self.carpeta)["DOCUMENTOS_ENCRYPTION_KEY"])
        self.assertEqual(leido["DJANGO_DEBUG"], "1")

    # --- No pisar lo que ya hay ----------------------------------------------
    def test_no_reemplaza_un_env_que_ya_existe(self):
        """El que importa. Pisar la clave de cifrado deja ilegibles todos los
        documentos ya subidos, sin aviso y sin vuelta atrás."""
        mio = ("DJANGO_SECRET_KEY=la-mia-de-siempre\n"
               "DOCUMENTOS_ENCRYPTION_KEY=T5rQGvJ8xX2mB0nK4wL6pR9sV1yU3zA7cD5eF8gH0iM=\n")
        (self.carpeta / ".env").write_text(mio, encoding="utf-8")

        salida = self.correr()

        self.assertEqual((self.carpeta / ".env").read_text(encoding="utf-8"), mio)
        self.assertIn("NO se va a reemplazar", salida.stdout)

    def test_avisa_cuando_falta_la_clave_de_cifrado(self):
        """Pasa de verdad: sin ella no se puede subir ningún documento."""
        (self.carpeta / ".env").write_text(
            "DJANGO_SECRET_KEY=algo\nDOCUMENTOS_ENCRYPTION_KEY=\n", encoding="utf-8")
        salida = self.correr(respuesta="no")
        self.assertIn("FALTA: DOCUMENTOS_ENCRYPTION_KEY", salida.stdout)

    def test_sin_confirmar_no_toca_nada(self):
        original = "DJANGO_SECRET_KEY=algo\nDOCUMENTOS_ENCRYPTION_KEY=\n"
        (self.carpeta / ".env").write_text(original, encoding="utf-8")
        self.correr(respuesta="no")
        self.assertEqual((self.carpeta / ".env").read_text(encoding="utf-8"), original)

    def test_al_confirmar_agrega_lo_que_falta_y_deja_el_resto(self):
        (self.carpeta / ".env").write_text(
            "DJANGO_SECRET_KEY=la-mia-de-siempre\n"
            "DJANGO_SITE_URL=https://algo.propio\n"
            "DOCUMENTOS_ENCRYPTION_KEY=\n", encoding="utf-8")

        self.correr(respuesta="SI")

        valores = _leer(self.carpeta)
        # Lo que ya estaba, intacto.
        self.assertEqual(valores["DJANGO_SECRET_KEY"], "la-mia-de-siempre")
        self.assertEqual(valores["DJANGO_SITE_URL"], "https://algo.propio")
        # Y la que faltaba, puesta y usable.
        from cryptography.fernet import Fernet
        Fernet(valores["DOCUMENTOS_ENCRYPTION_KEY"].encode())

    def test_antes_de_agregar_guarda_una_copia(self):
        (self.carpeta / ".env").write_text(
            "DJANGO_SECRET_KEY=la-mia\nDOCUMENTOS_ENCRYPTION_KEY=\n", encoding="utf-8")
        self.correr(respuesta="SI")
        copias = list((self.carpeta / "respaldos").glob("env-antes-de-completar-*.txt"))
        self.assertEqual(len(copias), 1, copias)
        self.assertIn("la-mia", copias[0].read_text(encoding="utf-8"))

    def test_cuando_esta_completo_lo_dice_y_se_va(self):
        completo = ("DJANGO_SECRET_KEY=algo-largo-de-verdad\n"
                    "DOCUMENTOS_ENCRYPTION_KEY=T5rQGvJ8xX2mB0nK4wL6pR9sV1yU3zA7cD5eF8gH0iM=\n")
        (self.carpeta / ".env").write_text(completo, encoding="utf-8")
        salida = self.correr()
        self.assertIn("no hay nada que hacer", salida.stdout.lower())
        self.assertEqual((self.carpeta / ".env").read_text(encoding="utf-8"), completo)


class ElBatEstaEnElProyecto(SimpleTestCase):
    """Barata: corre en cualquier sistema."""

    def test_existe_y_no_trae_acentos(self):
        """La consola de Windows no usa UTF-8: un acento sale como basura y
        `python-dotenv` puede leer mal el archivo que escribe."""
        self.assertTrue(BAT.exists())
        crudo = BAT.read_bytes()
        self.assertTrue(crudo.isascii(),
                        "el .bat tiene caracteres que la consola no dibuja bien")

    def test_no_esta_versionado_el_env(self):
        """Si el .env entrara al repositorio, las claves quedarían publicadas."""
        gitignore = (Path(settings.BASE_DIR) / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gitignore.split())
