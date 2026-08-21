"""Opciones del sistema que no son un catálogo: valen para todos.

Es una sola fila (`pk=1`). Un modelo con una fila única es más aburrido que un
archivo de settings, pero se cambia desde la pantalla de Configuración sin
tocar código ni reiniciar el servidor, y queda asentado en la auditoría.
"""

from django.conf import settings
from django.db import models


class Preferencias(models.Model):
    """Ajustes globales editables desde Configuración."""

    restringir_por_zona = models.BooleanField(
        "Restringir cada usuario a su zona",
        default=False,
        help_text="Apagado (como viene), todos ven todas las tiendas y todos "
                  "los expedientes, sin importar la zona. Prendelo solo si "
                  "algún día querés que cada usuario vea únicamente los "
                  "expedientes de su zona. No cambia lo que cada uno puede "
                  "hacer: borrar sigue siendo solo del Administrador.",
    )

    actualizado_en = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "preferencias del sistema"
        verbose_name_plural = "preferencias del sistema"

    def __str__(self):
        return "Preferencias del sistema"

    def save(self, *args, **kwargs):
        # Una sola fila, siempre la misma: así nunca hay dos configuraciones
        # compitiendo ni hace falta preguntarse cuál manda.
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def obtener(cls):
        """La fila única, creándola con los valores por defecto si falta."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
