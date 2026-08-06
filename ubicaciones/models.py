from django.conf import settings
from django.db import models


class Galpon(models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=255, blank=True, default='')
    grid_filas = models.PositiveIntegerField(default=10)
    grid_columnas = models.PositiveIntegerField(default=10)
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='galpones_creados',
    )

    class Meta:
        ordering = ['codigo']

    def __str__(self) -> str:
        return self.nombre or self.codigo


class Rack(models.Model):
    galpon = models.ForeignKey(Galpon, on_delete=models.PROTECT, related_name='racks')
    codigo = models.CharField(max_length=5)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    grid_fila = models.PositiveIntegerField(default=1)
    grid_columna = models.PositiveIntegerField(default=1)
    ancho = models.PositiveIntegerField(default=1)
    alto = models.PositiveIntegerField(default=1)
    max_niveles = models.PositiveIntegerField(default=6)
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='racks_creados',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['galpon', 'codigo'], name='uniq_rack_codigo_por_galpon'),
        ]
        ordering = ['galpon', 'codigo']

    def __str__(self) -> str:
        return f"{self.galpon.codigo}{self.codigo}"

    @property
    def total_cuerpos(self) -> int:
        return self.cuerpos.count()


class Cuerpo(models.Model):
    rack = models.ForeignKey(Rack, on_delete=models.PROTECT, related_name='cuerpos')
    codigo = models.CharField(max_length=4)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    activo = models.BooleanField(default=True, db_index=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='cuerpos_creados',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['rack', 'codigo'], name='uniq_cuerpo_codigo_por_rack'),
        ]
        ordering = ['rack', 'codigo']

    def __str__(self) -> str:
        return f"{self.rack} / Cuerpo {self.codigo}"


class Ubicacion(models.Model):
    cuerpo = models.ForeignKey(Cuerpo, on_delete=models.PROTECT, related_name='ubicaciones')
    codigo = models.CharField(max_length=4)
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
            models.UniqueConstraint(fields=['cuerpo', 'codigo'], name='uniq_ubicacion_codigo_por_cuerpo'),
        ]
        ordering = ['cuerpo', 'codigo']

    def __str__(self) -> str:
        return f"{self.cuerpo} / Ubicación {self.codigo}"

    @property
    def rack(self) -> Rack:
        return self.cuerpo.rack


class Nivel(models.Model):
    PICKING = 'PICKING'
    ALMACENAJE = 'ALMACENAJE'
    TIPO_CHOICES = [
        (PICKING, 'Picking'),
        (ALMACENAJE, 'Almacenaje'),
    ]

    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, related_name='niveles')
    numero = models.PositiveSmallIntegerField()
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, default=PICKING)
    descripcion = models.CharField(max_length=255, blank=True, default='')
    fusionado_en = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True,
        related_name='niveles_fusionados',
    )
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
            models.UniqueConstraint(fields=['ubicacion', 'numero'], name='uniq_nivel_numero_por_ubicacion'),
        ]
        ordering = ['ubicacion', 'numero']

    def __str__(self) -> str:
        return self.codigo_completo

    @property
    def cuerpo(self) -> Cuerpo:
        return self.ubicacion.cuerpo

    @property
    def rack(self) -> Rack:
        return self.ubicacion.cuerpo.rack

    @property
    def galpon(self) -> Galpon:
        return self.ubicacion.cuerpo.rack.galpon

    @property
    def codigo_completo(self) -> str:
        return (
            f"{self.galpon.codigo}{self.rack.codigo}"
            f"{self.cuerpo.codigo}{self.ubicacion.codigo}.{self.numero}"
        )

    @property
    def esta_fusionado(self) -> bool:
        return self.fusionado_en_id is not None


class ProductoUbicacion(models.Model):
    codigo_producto = models.CharField(max_length=50, db_index=True)
    nivel = models.ForeignKey(Nivel, on_delete=models.PROTECT, related_name='productos')
    cantidad = models.PositiveIntegerField(default=0)
    stock_minimo = models.PositiveIntegerField(null=True, blank=True)
    fecha_asignacion = models.DateTimeField(auto_now_add=True)
    asignado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='asignaciones_ubicacion',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['codigo_producto', 'nivel'], name='uniq_producto_por_nivel'),
        ]
        indexes = [models.Index(fields=['codigo_producto'])]
        ordering = ['codigo_producto']

    def __str__(self) -> str:
        return f"{self.codigo_producto} @ {self.nivel.codigo_completo}"


class MovimientoUbicacion(models.Model):
    TIPO_CHOICES = [
        ('CREACION_GALPON', 'Creación de galpón'),
        ('EDICION_GALPON', 'Edición de galpón'),
        ('DESACTIVACION_GALPON', 'Desactivación de galpón'),
        ('CREACION_RACK', 'Creación de rack'),
        ('EDICION_RACK', 'Edición de rack'),
        ('DESACTIVACION_RACK', 'Desactivación de rack'),
        ('CREACION_CUERPO', 'Creación de cuerpo'),
        ('DESACTIVACION_CUERPO', 'Desactivación de cuerpo'),
        ('DESACTIVACION_UBICACION', 'Desactivación de ubicación'),
        ('EDICION_NIVEL', 'Edición de nivel'),
        ('DESACTIVACION_NIVEL', 'Desactivación de nivel'),
        ('ASIGNACION', 'Asignación de producto'),
        ('EDICION_CANTIDAD', 'Edición de cantidad'),
        ('DESASIGNACION', 'Desasignación de producto'),
        ('TRASLADO', 'Traslado entre niveles'),
        ('FUSION_NIVEL', 'Fusión de niveles'),
        ('DESFUSION_NIVEL', 'Desfusión de nivel'),
    ]

    tipo = models.CharField(max_length=30, choices=TIPO_CHOICES, db_index=True)
    galpon = models.ForeignKey(Galpon, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    rack = models.ForeignKey(Rack, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    cuerpo = models.ForeignKey(Cuerpo, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    ubicacion = models.ForeignKey(Ubicacion, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    nivel = models.ForeignKey(Nivel, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos')
    nivel_origen = models.ForeignKey(
        Nivel, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos_origen',
    )
    nivel_destino = models.ForeignKey(
        Nivel, on_delete=models.PROTECT, null=True, blank=True, related_name='movimientos_destino',
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
