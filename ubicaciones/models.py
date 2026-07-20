from django.conf import settings
from django.db import models


class Rack(models.Model):
    codigo = models.CharField(max_length=20, unique=True)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    max_niveles = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Máximo de niveles permitidos (activos + inactivos). Vacío = sin tope.',
    )
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='racks_creados',
    )

    class Meta:
        ordering = ['codigo']

    def __str__(self) -> str:
        return self.codigo

    @property
    def total_niveles(self) -> int:
        return self.niveles.count()

    @property
    def tope_alcanzado(self) -> bool:
        if self.max_niveles is None:
            return False
        return self.niveles.count() >= self.max_niveles


class Nivel(models.Model):
    PICKING = 'PICKING'
    ALMACENAJE = 'ALMACENAJE'
    TIPO_CHOICES = [
        (PICKING, 'Picking'),
        (ALMACENAJE, 'Almacenaje'),
    ]

    rack = models.ForeignKey(Rack, on_delete=models.PROTECT, related_name='niveles')
    codigo = models.CharField(max_length=20)
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=PICKING)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='niveles_creados',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['rack', 'codigo'], name='uniq_nivel_codigo_por_rack'),
        ]
        ordering = ['rack', 'codigo']

    def __str__(self) -> str:
        return f"{self.rack.codigo} / {self.codigo}"


class Ubicacion(models.Model):
    nivel = models.ForeignKey(Nivel, on_delete=models.PROTECT, related_name='ubicaciones')
    codigo = models.CharField(max_length=20)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ubicaciones_creadas',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['nivel', 'codigo'], name='uniq_ubicacion_codigo_por_nivel'),
        ]
        ordering = ['nivel', 'codigo']

    def __str__(self) -> str:
        return self.codigo_completo

    @property
    def codigo_completo(self) -> str:
        return f"{self.nivel.rack.codigo} / {self.nivel.codigo} / {self.codigo}"

    @property
    def rack(self) -> Rack:
        return self.nivel.rack


class ProductoUbicacion(models.Model):
    codigo_producto = models.CharField(max_length=50, db_index=True)
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, related_name='productos')
    fecha_asignacion = models.DateTimeField(auto_now_add=True)
    asignado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asignaciones_ubicacion',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['codigo_producto', 'ubicacion'],
                name='uniq_producto_por_ubicacion',
            ),
        ]
        indexes = [
            models.Index(fields=['codigo_producto']),
        ]
        ordering = ['codigo_producto']

    def __str__(self) -> str:
        return f"{self.codigo_producto} @ {self.ubicacion}"


class MovimientoUbicacion(models.Model):
    TIPO_CHOICES = [
        ('CREACION_RACK',       'Creación de rack'),
        ('EDICION_RACK',        'Edición de rack'),
        ('DESACTIVACION_RACK',  'Desactivación de rack'),
        ('CREACION_NIVEL',      'Creación de nivel'),
        ('EDICION_NIVEL',       'Edición de nivel'),
        ('DESACTIVACION_NIVEL', 'Desactivación de nivel'),
        ('CREACION_UBICACION',      'Creación de ubicación'),
        ('EDICION_UBICACION',       'Edición de ubicación'),
        ('DESACTIVACION_UBICACION', 'Desactivación de ubicación'),
        ('ASIGNACION',    'Asignación de producto'),
        ('DESASIGNACION', 'Desasignación de producto'),
        ('TRASLADO',      'Traslado entre ubicaciones'),
        ('FUSION',        'Fusión de ubicaciones'),
    ]

    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, db_index=True)
    rack = models.ForeignKey(
        Rack, on_delete=models.PROTECT,
        null=True, blank=True, related_name='movimientos',
    )
    nivel = models.ForeignKey(
        Nivel, on_delete=models.PROTECT,
        null=True, blank=True, related_name='movimientos',
    )
    ubicacion_origen = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT,
        null=True, blank=True, related_name='movimientos_origen',
    )
    ubicacion_destino = models.ForeignKey(
        Ubicacion, on_delete=models.PROTECT,
        null=True, blank=True, related_name='movimientos_destino',
    )
    codigo_producto = models.CharField(max_length=50, blank=True, default='', db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='movimientos_ubicacion',
    )
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)
    notas = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-fecha']
        indexes = [
            models.Index(fields=['-fecha']),
            models.Index(fields=['tipo', '-fecha']),
            models.Index(fields=['codigo_producto', '-fecha']),
        ]

    def __str__(self) -> str:
        return f"{self.get_tipo_display()} — {self.codigo_producto or '-'} ({self.fecha:%Y-%m-%d %H:%M})"
