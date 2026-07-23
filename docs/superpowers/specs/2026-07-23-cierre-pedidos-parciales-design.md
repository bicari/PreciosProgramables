# Cierre de pedidos parciales — Diseño

**Fecha:** 2026-07-23
**App:** PedidosAlmacen

## Problema

Los pedidos en estado `PARCIAL` con back orders que nunca se van a completar
quedan abiertos indefinidamente en las listas operativas. Supervisores y
almacenistas necesitan una acción explícita para darlos por terminados.

El estado `CERRADO` ya existe en `Pedido.ESTADO_CHOICES` y las listas ya lo
excluyen (`views.py` lista de pedidos, `api_views.py`), pero no existe ninguna
acción que lleve un pedido a ese estado.

## Solución

Nueva acción "Cerrar pedido": vista POST + botón con modal en el detalle del
pedido, siguiendo el patrón existente de anulación.

### Elegibilidad

Un pedido se puede cerrar solo si se cumplen las tres condiciones:

1. `pedido.estado == 'PARCIAL'` (tiene items con back order pendiente, en
   estado `PARCIAL` o `BACK_ORDER`).
2. Ningún despacho del pedido está en `ENVIADO`, `PENDIENTE_APROBACION` ni
   `PREPARANDO` (despachos aún no finalizados). Los despachos en `RECIBIDO`,
   `PARCIAL` (recibido con incidencias pendientes) o `ANULADO` no bloquean.
3. El usuario pertenece al grupo `Pedidos Supervisor` o `Pedidos Almacen`, o
   es superuser. Se implementa con los helpers existentes
   `is_pedidos_supervisor(user) or is_pedidos_almacen(user)` (ambos ya
   incluyen superuser).

### Cambios de modelo (una migración)

- `PedidoItem.ESTADO_ITEM_CHOICES`: nuevo estado `('CERRADO', 'Cerrado')`.
  Distingue explícitamente los items que se cerraron sin completar.
- `Pedido`: campos de auditoría siguiendo el patrón de anulación:
  - `cerrado_por = FK(User, SET_NULL, null=True, blank=True, related_name='pedidos_cerrados')`
  - `fecha_cierre = DateTimeField(null=True, blank=True)`
  - `motivo_cierre = TextField(blank=True, default='')`
- No se agrega `estado_anterior` para el cierre: el estado previo siempre es
  `PARCIAL`.

### Acción de cierre

Vista `cerrar_pedido(request, pk)`, solo POST, decorada con `login_required`
y un check de permiso Supervisor-o-Almacén. Dentro de `transaction.atomic`
con `select_for_update` sobre el pedido (patrón de `anular_despacho`):

1. Revalidar elegibilidad (estado del pedido y despachos bloqueantes) dentro
   de la transacción; si falla, mensaje de error y redirect al detalle.
2. Motivo obligatorio (`request.POST['motivo']`); si falta, error y redirect.
3. Para cada item en estado `PARCIAL` o `BACK_ORDER`:
   `cantidad_back_order = 0` y `estado = 'CERRADO'`.
4. Pedido: `estado = 'CERRADO'`, `cerrado_por = request.user`,
   `fecha_cierre = timezone.now()`, `motivo_cierre = motivo`.
5. `logger.info` con número de pedido, usuario y motivo;
   `messages.success`; redirect al detalle.

URL: `pedidos/<pk>/cerrar/` (name `pedidos-cerrar`) junto a las rutas de
anulación existentes.

### UI

- `pedidos-detalle.html`: botón "Cerrar pedido" visible solo si el pedido es
  elegible y el usuario tiene permiso (flag `puede_cerrar` calculado en la
  vista de detalle). Modal de confirmación con textarea de motivo obligatorio,
  mismo patrón visual que el modal de anulación.
- Badge para el estado de item `CERRADO` en el detalle del pedido. El badge
  de pedido `CERRADO` ya existe en detalle, lista y reporte; el reporte ya
  contempla el badge de item `CERRADO`.
- En el detalle de un pedido cerrado, mostrar el bloque de auditoría
  (quién, cuándo, motivo), como hace la anulación.

### Interacciones verificadas con código existente (sin cambios)

- Listas de pedidos y API ya excluyen `estado='CERRADO'`.
- Resolver incidencias después del cierre funciona: la promoción de estados
  tras resolución nunca toca pedidos `CERRADO`
  (`_actualizar_estados_tras_resolucion`), y el despacho `PARCIAL → RECIBIDO`
  sigue operando de forma independiente al pedido.
- `pdf.py` ya mapea el estado `CERRADO`.
- Un pedido `PARCIAL` con picker reasignado pasa a `ASIGNADO`, por lo que
  deja de ser elegible automáticamente; no hace falta manejar picker en el
  cierre.

### Tests

En `PedidosAlmacen/tests.py` (correr con `test_settings`, SQLite):

- Elegibilidad: cierra un pedido `PARCIAL` sin despachos pendientes; rechaza
  pedidos en otros estados; rechaza si existe despacho en `ENVIADO`,
  `PENDIENTE_APROBACION` o `PREPARANDO`; permite con despachos `RECIBIDO`,
  `PARCIAL` y `ANULADO`.
- Permisos: Supervisor, Almacén y superuser pueden; Tienda y Picker no.
- Efecto: items `PARCIAL`/`BACK_ORDER` quedan con `cantidad_back_order = 0`
  y estado `CERRADO`; items ya `RECIBIDO`/`DESPACHADO` no se tocan; auditoría
  registrada en el pedido.
- Motivo obligatorio: POST sin motivo no cambia nada.
- GET no cierra (redirect).
