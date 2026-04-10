from django.db import models
from users.models import User


class Pedido(models.Model):
    ESTADO_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('PICKING', 'Picking'),
        ('DESPACHADO', 'Despachado'),
        ('RECIBIDO', 'Recibido'),
        ('CERRADO', 'Cerrado'),
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
    deposito_codigo = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"Pedido #{self.numero_pedido} - {self.solicitante.username}"


class PedidoItem(models.Model):
    ESTADO_ITEM_CHOICES = [
        ('PENDIENTE', 'Pendiente'),
        ('DESPACHADO', 'Despachado'),
        ('RECIBIDO', 'Recibido'),
        ('BACK_ORDER', 'Back Order'),
        ('INCIDENCIA', 'Incidencia'),
    ]
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='items')
    codigo = models.CharField(max_length=50)
    descripcion = models.CharField(max_length=255)
    referencia = models.CharField(max_length=100, blank=True, default='')
    puesto = models.CharField(max_length=100, blank=True, default='')
    ref_proveedor = models.CharField(max_length=100, blank=True, default='')
    cantidad_solicitada = models.IntegerField()
    cantidad_despachada = models.IntegerField(default=0)
    cantidad_recibida = models.IntegerField(default=0)
    estado = models.CharField(max_length=20, choices=ESTADO_ITEM_CHOICES, default='PENDIENTE')
    observacion = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.codigo} - {self.descripcion} (x{self.cantidad_solicitada})"
