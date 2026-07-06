from django.db import models

TIPOS_VALIDOS = ('despacho', 'pedido')


class PlantillaImpresion(models.Model):
    """Plantilla ReportBro de un tipo de documento (una fila por tipo)."""

    TIPO_CHOICES = [('despacho', 'Despacho'), ('pedido', 'Pedido')]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, unique=True)
    definicion = models.JSONField(help_text="Definición JSON producida por ReportBro Designer.")
    definicion_anterior = models.JSONField(null=True, blank=True)
    activa = models.BooleanField(default=False)
    actualizado_por = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='plantillas_actualizadas',
    )
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Plantilla de impresión'
        verbose_name_plural = 'Plantillas de impresión'

    def __str__(self):
        estado = 'activa' if self.activa else 'inactiva'
        return f"Plantilla {self.get_tipo_display()} ({estado})"

    def actualizar_definicion(self, definicion: dict, usuario) -> None:
        """Guarda una nueva definición rotando la actual a definicion_anterior."""
        self.definicion_anterior = self.definicion
        self.definicion = definicion
        self.actualizado_por = usuario
        self.save()

    def restaurar(self) -> bool:
        """Intercambia definicion y definicion_anterior. False si no hay anterior."""
        if self.definicion_anterior is None:
            return False
        self.definicion, self.definicion_anterior = self.definicion_anterior, self.definicion
        self.save()
        return True


class ReportePreview(models.Model):
    """PDF efímero generado para el preview del diseñador (patrón albumapp-django)."""

    key = models.CharField(max_length=36, unique=True)
    pdf = models.BinaryField()
    creado = models.DateTimeField(auto_now_add=True)
