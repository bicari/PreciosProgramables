# Anulación de Pedidos y Despachos — Diseño

**Fecha:** 2026-06-27
**App:** `PedidosAlmacen`
**Estado:** Aprobado (pendiente de plan de implementación)

## Problema

Hoy no existe forma de eliminar un pedido ni de cambiarle el estado a uno que no
afecte los reportes KPI del almacén. Cualquier pedido creado por error, duplicado
o cancelado queda contando en los KPIs (totales, tiempos, por estado, incidencias).

## Objetivo

Agregar un estado **ANULADO** para pedidos y para despachos que:

- Saque al objeto de **todos** los cálculos KPI.
- Solo pueda ser ejecutado por usuarios **supervisores** o **superuser**.
- Deje rastro de auditoría (motivo, quién, cuándo, estado previo).

## Decisiones de alcance (confirmadas con el usuario)

1. **a2 / inventario:** Anular es una acción **administrativa solo en Django**. Se
   permite anular desde **cualquier estado**, incluso si ya hubo movimiento de
   inventario en a2 (`Pedido` en `DESPACHADO`, o `Despacho` con
   `traslado_a2_registrado=True`). El sistema **NO** revierte inventario en a2; la
   reversión, si aplica, queda **manual** en a2. Por eso se guarda el estado previo,
   para que el operador sepa si debe revertir manualmente.
2. **Auditoría / reversibilidad:** Motivo **obligatorio** + registro de quién y
   cuándo. Estado **terminal**: una vez anulado **no se puede revertir** desde la app.
3. **Relación Pedido ↔ Despacho:** **Independientes**. Anular un pedido **no** toca
   sus despachos, y anular un despacho **no** toca su pedido. Cada uno se anula por
   separado.
4. **Visibilidad:** Los objetos anulados **siguen apareciendo** en las listas
   operativas con un **badge rojo `ANULADO`**, pero quedan **excluidos de todos los
   KPIs** del reporte.

## Diseño

### 1. Modelo de datos

En `PedidosAlmacen/models.py`:

**`Pedido`**
- Añadir `('ANULADO', 'Anulado')` a `ESTADO_CHOICES`.
- Campos nuevos:
  - `motivo_anulacion = models.TextField(blank=True, default='')` (obligatorio a nivel de vista).
  - `anulado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='pedidos_anulados')`
  - `fecha_anulacion = models.DateTimeField(null=True, blank=True)`
  - `estado_anterior = models.CharField(max_length=20, blank=True, default='')`

**`Despacho`**
- Añadir `('ANULADO', 'Anulado')` a `ESTADO_CHOICES`.
- Campos nuevos (análogos):
  - `motivo_anulacion = models.TextField(blank=True, default='')`
  - `anulado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='despachos_anulados')`
  - `fecha_anulacion = models.DateTimeField(null=True, blank=True)`
  - `estado_anterior = models.CharField(max_length=20, blank=True, default='')`

Dos migraciones nuevas (continuando la numeración existente, `0020...` y `0021...`,
o una sola migración que cubra ambos modelos).

### 2. Acciones (vistas)

En `PedidosAlmacen/views.py`:

- `anular_pedido(request, pk)` y `anular_despacho(request, despacho_id)`.
- Decoradas con `@login_required(login_url='/login/')` +
  `@user_passes_test(is_pedidos_supervisor, login_url='dashboard')`
  (`is_pedidos_supervisor` ya incluye `is_superuser`).
- Solo aceptan `POST`.
- Validan `motivo` no vacío; si viene vacío → `messages.error` + redirect al detalle.
- Si el objeto ya está `ANULADO` → `messages.warning` + redirect (estado terminal).
- Al anular:
  - `obj.estado_anterior = obj.estado`
  - `obj.estado = 'ANULADO'`
  - `obj.anulado_por = request.user`
  - `obj.fecha_anulacion = timezone.now()`
  - `obj.motivo_anulacion = motivo`
- **Pedido:** si el `estado_anterior` era `ASIGNADO` o `PICKING`, liberar al picker
  (`obj.picker = None`) para no dejarlo ocupado.
- Registrar en logging la acción (quién anuló qué y por qué).

Rutas nuevas en `PedidosAlmacen/urls.py` para ambas vistas.

### 3. Exclusión de KPIs

- `reporte_pedidos`, `exportar_reporte_pdf` (y el armado del contexto del PDF):
  cambiar la base de `Pedido.objects.all()` a
  `Pedido.objects.exclude(estado='ANULADO')`. Todos los KPIs (tiempos, totales de
  ítems, `por_estado`, `por_categoria`, `por_condicion`, incidencias) derivan de ese
  queryset base, así que con excluir ahí basta.
- `reporte_incidencias`: añadir al queryset de `DespachoItem`
  `.exclude(despacho__estado='ANULADO').exclude(despacho__pedido__estado='ANULADO')`.
- Añadir al reporte un **contador informativo** "Pedidos anulados en el período",
  claramente separado de los KPIs (se calcula sobre el mismo rango de fechas pero
  filtrando `estado='ANULADO'`).

### 4. Visibilidad (badge dentro de listas)

- `lista_pedidos` / `lista_despachos`: **sin cambios en el queryset** → los anulados
  siguen apareciendo.
- `templates/pedidos-lista.html` y la plantilla de lista de despachos: badge rojo
  `ANULADO` y fila atenuada (`text-muted` / clase suave) para distinguirlos.
- Detalle de pedido (`detalle_pedido`) y detalle/confirmación de despacho: mostrar
  bloque de anulación (motivo, `anulado_por`, `fecha_anulacion`, `estado_anterior`)
  cuando el objeto esté anulado.
- Botón **"Anular"** con **modal de confirmación que exige el motivo**, visible
  **solo** para supervisor/superuser y solo si el objeto **no** está ya anulado.

### 5. Contadores y otros flujos

- `contar_pendientes` y filtros por estado específico (`PENDIENTE`, `ENVIADO`,
  `PENDIENTE_APROBACION`, etc.) ya excluyen `ANULADO` de forma natural porque no
  coincide con esos estados. **Sin cambios.**

## Fuera de alcance

- No se revierte inventario en a2 (reversión manual cuando aplique).
- No reversible / sin "desanular".
- Sin notificaciones por correo de anulación.
- Sin borrado físico de registros (siempre soft, vía estado).

## Permisos (resumen)

| Acción | Tienda | Almacén | Picker | Supervisor | Superuser |
|--------|:------:|:-------:|:------:|:----------:|:---------:|
| Ver objeto anulado en listas | ✔ | ✔ | ✔ | ✔ | ✔ |
| Anular pedido / despacho | ✘ | ✘ | ✘ | ✔ | ✔ |

## Criterios de aceptación

- Un supervisor/superuser puede anular un pedido y un despacho desde cualquier
  estado, indicando un motivo obligatorio.
- Un usuario no supervisor no ve el botón "Anular" y la vista rechaza su POST.
- Un pedido/despacho anulado no aparece en ningún KPI del reporte ni del PDF.
- Un pedido/despacho anulado sí aparece en las listas con badge `ANULADO`.
- El detalle muestra motivo, quién, cuándo y estado previo.
- Anular un pedido en `ASIGNADO`/`PICKING` libera al picker.
- Intentar anular algo ya anulado se rechaza con mensaje.
