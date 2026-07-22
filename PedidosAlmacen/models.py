from django.core.exceptions import ValidationError
from django.db import models
from users.models import User


class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('ASIGNADO', 'Asignado'),
        ('PICKING', 'Picking'),
        ('EN_PREPARACION', 'En Preparación'),
        ('DESPACHADO', 'Despachado'),
        ('PARCIAL', 'Parcial'),
        ('RECIBIDO', 'Recibido'),
        ('CERRADO', 'Cerrado'),
        ('ANULADO', 'Anulado'),
    ]
    CONDICION_CHOICES = [
        ('URGENTE', 'Urgente'),
        ('SURTIDO', 'Surtido'),
        ('CLIENTE_RETIRA', 'Cliente Retira'),
    ]
    numero_pedido = models.AutoField(primary_key=True)
    solicitante = models.ForeignKey(User, on_delete=models.PROTECT, related_name='pedidos_solicitados')
    despachador = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_despachados')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PENDIENTE')
    condicion = models.CharField(max_length=20, choices=CONDICION_CHOICES, blank=True, default='')
    deposito = models.CharField(max_length=100, blank=True, default='')
    observaciones = models.TextField(blank=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_despacho = models.DateTimeField(null=True, blank=True)
    fecha_recepcion = models.DateTimeField(null=True, blank=True)
    categoria = models.CharField(max_length=70, blank=True, default='')
    categoria_nombre = models.CharField(max_length=150, blank=True, default='')
    deposito_codigo = models.IntegerField(null=True, blank=True)
    deposito_transito = models.IntegerField(
        null=True, blank=True,
        help_text="Depósito de tránsito usado en el despacho de este pedido "
                  "(snapshot de la configuración al despachar).",
    )
    picker = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pedidos_picking',
    )
    fecha_asignacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.TextField(blank=True, default='')
    anulado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pedidos_anulados',
    )
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    estado_anterior = models.CharField(max_length=20, blank=True, default='')

    def __str__(self):
        return f"Pedido #{self.numero_pedido} - {self.solicitante.username}"


class PedidoItem(models.Model):
    ESTADO_ITEM_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('DESPACHADO', 'Despachado'),
        ('PARCIAL', 'Parcial'),
        ('RECIBIDO', 'Recibido'),
        ('BACK_ORDER', 'Back Order'),
        ('INCIDENCIA', 'Incidencia'),
        ('INCIDENCIA_RESUELTA', 'Incidencia Resuelta'),
    ]
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='items')
    codigo = models.CharField(max_length=50)
    descripcion = models.CharField(max_length=255)
    referencia = models.CharField(max_length=100, blank=True, default='')
    puesto = models.CharField(max_length=100, blank=True, default='')
    ref_proveedor = models.CharField(max_length=100, blank=True, default='')
    cantidad_solicitada = models.IntegerField()
    cantidad_preparada = models.IntegerField(null=True, blank=True)
    cantidad_despachada = models.IntegerField(default=0)
    cantidad_back_order = models.IntegerField(default=0)
    cantidad_recibida = models.IntegerField(default=0)
    estado = models.CharField(max_length=20, choices=ESTADO_ITEM_CHOICES, default='PENDIENTE')
    observacion = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.codigo} - {self.descripcion} (x{self.cantidad_solicitada})"


class Despacho(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE_APROBACION', 'Pendiente de Aprobación'),
        ('PREPARANDO', 'Preparando'),
        ('ENVIADO', 'Enviado'),
        ('RECIBIDO', 'Recibido'),
        ('PARCIAL', 'Parcial'),
        ('ANULADO', 'Anulado'),
    ]
    pedido = models.ForeignKey(Pedido, on_delete=models.PROTECT, related_name='despachos')
    numero_despacho = models.AutoField(primary_key=True)
    despachador = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='despachos_realizados')
    picker = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='despachos_pickeados')
    receptor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='despachos_recibidos')
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PREPARANDO')
    observaciones = models.TextField(blank=True)
    fecha_despacho = models.DateTimeField(null=True, blank=True)
    fecha_recepcion = models.DateTimeField(null=True, blank=True)
    traslado_a2_registrado = models.BooleanField(default=False)
    motivo_anulacion = models.TextField(blank=True, default='')
    anulado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='despachos_anulados',
    )
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    estado_anterior = models.CharField(max_length=20, blank=True, default='')

    def __str__(self):
        return f"Despacho #{self.numero_despacho} → Pedido #{self.pedido_id}"


class DespachoItem(models.Model):
    TIPO_INCIDENCIA_CHOICES = [
        ('PRODUCTO_ERRONEO', 'Producto Erróneo'),
        ('SKU_NO_CONTEMPLADO', 'SKU No Contemplado'),
        ('CANTIDAD_MENOR', 'Cantidad Menor a lo Despachado'),
        ('CANTIDAD_MAYOR', 'Cantidad Mayor a lo Despachado'),
    ]
    despacho = models.ForeignKey(Despacho, on_delete=models.CASCADE, related_name='items')
    # Nullable para SKU no contemplados (no tienen PedidoItem de origen)
    pedido_item = models.ForeignKey(PedidoItem, on_delete=models.PROTECT, related_name='despachos', null=True, blank=True)
    cantidad_despachada = models.IntegerField()
    cantidad_recibida = models.IntegerField(default=0)
    observacion = models.CharField(max_length=255, blank=True)
    tipo_incidencia = models.CharField(max_length=20, choices=TIPO_INCIDENCIA_CHOICES, blank=True, default='')
    # Producto realmente recibido (solo para PRODUCTO_ERRONEO)
    codigo_real = models.CharField(max_length=50, blank=True)
    descripcion_real = models.CharField(max_length=255, blank=True)
    autorizado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='despachos_autorizados',
    )
    foto_incidencia = models.ImageField(
        upload_to='incidencias/%Y/%m/%d/',
        null=True, blank=True,
    )
    # Resolución ACTIVA de la incidencia; null = incidencia pendiente.
    # El historial completo (incluidas resoluciones anuladas) vive en IncidenciaEvento.
    resolucion = models.ForeignKey(
        'ResolucionIncidencia', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='items_resueltos',
    )

    def __str__(self):
        codigo = self.pedido_item.codigo if self.pedido_item else self.codigo_real
        return f"{codigo} x{self.cantidad_despachada} (Despacho #{self.despacho_id})"


class DepositoPermitido(models.Model):
    """Depósito de a2 habilitado para selección al crear un pedido.

    Se sincroniza desde SDEPOSITOS y el admin marca cuáles quedan activos.
    Además define el alcance de recepción: los usuarios en ``receptores``
    pueden recibir despachos destinados a este depósito (independiente de
    ``activo``, que solo gobierna la selección al crear pedidos).
    """
    codigo = models.IntegerField(unique=True)      # FDP_CODIGO de SDEPOSITOS
    nombre = models.CharField(max_length=150)      # FDP_DESCRIPCION
    activo = models.BooleanField(default=False)
    fecha_sync = models.DateTimeField(auto_now=True)
    receptores = models.ManyToManyField(
        User, blank=True, related_name='depositos_recepcion',
        help_text='Usuarios autorizados a recibir despachos destinados a este depósito.',
    )

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Depósito permitido'
        verbose_name_plural = 'Depósitos permitidos'

    def __str__(self) -> str:
        return f"{self.codigo} - {self.nombre}"


class ConfiguracionPedidos(models.Model):
    """Configuración operativa singleton del módulo de pedidos (una sola fila)."""
    deposito_transito = models.IntegerField(
        help_text="Código de depósito de tránsito en a2 (SDEPOSITOS.FDP_CODIGO)."
    )
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Configuracion deposito tránsito a2'
        verbose_name_plural = 'Configuración de pedidos'

    def save(self, *args, **kwargs):
        self.pk = 1  # fuerza singleton
        super().save(*args, **kwargs)

    def clean(self):
        # Validación suave contra el espejo de SDEPOSITOS: si aún no se ha
        # sincronizado ningún depósito, no bloquea.
        if DepositoPermitido.objects.exists() and \
                not DepositoPermitido.objects.filter(codigo=self.deposito_transito).exists():
            raise ValidationError({
                'deposito_transito':
                    f'El depósito {self.deposito_transito} no existe en los '
                    f'depósitos sincronizados desde a2.'
            })

    @classmethod
    def load(cls) -> 'ConfiguracionPedidos':
        obj, _ = cls.objects.get_or_create(pk=1, defaults={'deposito_transito': 10})
        return obj


class ResolucionIncidencia(models.Model):
    """Acto de resolución que agrupa incidencias resueltas con un mismo documento."""
    TIPO_CHOICES = [
        ('TRASLADO', 'Traslado a2'),
        ('MANUAL', 'Manual'),
    ]
    ESTADO_CHOICES = [
        ('ACTIVA', 'Activa'),
        ('ANULADA', 'Anulada'),
    ]
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES)
    documento_traslado = models.CharField(max_length=20, blank=True, default='')
    observacion = models.CharField(max_length=255, blank=True, default='')
    resuelto_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='incidencias_resueltas',
    )
    fecha_resolucion = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default='ACTIVA')
    anulada_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='resoluciones_anuladas',
    )
    fecha_anulacion = models.DateTimeField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['-fecha_resolucion']
        verbose_name = 'Resolución de incidencia'
        verbose_name_plural = 'Resoluciones de incidencias'

    def __str__(self) -> str:
        ref = self.documento_traslado or 'manual'
        return f"Resolución #{self.pk} ({ref})"


class IncidenciaEvento(models.Model):
    """Log inmutable de resoluciones/anulaciones por item. Nunca se edita ni borra."""
    TIPO_EVENTO_CHOICES = [
        ('RESOLUCION', 'Resolución'),
        ('ANULACION', 'Anulación'),
    ]
    despacho_item = models.ForeignKey(
        DespachoItem, on_delete=models.CASCADE, related_name='eventos_incidencia',
    )
    resolucion = models.ForeignKey(
        ResolucionIncidencia, on_delete=models.PROTECT, related_name='eventos',
    )
    tipo_evento = models.CharField(max_length=10, choices=TIPO_EVENTO_CHOICES)
    usuario = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True,
        related_name='eventos_incidencia',
    )
    fecha = models.DateTimeField(auto_now_add=True)
    detalle = models.CharField(max_length=255, blank=True, default='')

    class Meta:
        ordering = ['fecha']
        verbose_name = 'Evento de incidencia'
        verbose_name_plural = 'Eventos de incidencias'

    def __str__(self) -> str:
        return f"{self.tipo_evento} item #{self.despacho_item_id} ({self.fecha:%d/%m/%Y})"
