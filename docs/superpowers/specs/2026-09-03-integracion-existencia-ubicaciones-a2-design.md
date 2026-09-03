# Integración de existencia por ubicación con a2 (picking + reconciliación + API móvil)

**Fecha:** 2026-09-03

## Nota de reemplazo

Este documento **reemplaza y deja sin validez** el spec
`docs/superpowers/specs/2026-09-02-existencia-por-ubicacion-picking-design.md`
(modelos `PickingOrigen`/`ExistenciaSinUbicacion`, servicio `aplicar_picking`
con bloqueo por stock insuficiente). Al completar la implementación de este
spec:

- Eliminar `docs/superpowers/specs/2026-09-02-existencia-por-ubicacion-picking-design.md`.
- Eliminar/reescribir en `ubicaciones/tests.py` las clases que testean el
  diseño descartado: las que referencian `PickingOrigen`,
  `ExistenciaSinUbicacion` y `UbicacionesService.aplicar_picking`.

## Problema

`ubicaciones` permite asignar productos a ubicaciones físicas con una
cantidad (`ProductoUbicacion.cantidad`), validada al asignar/editar contra la
existencia real en a2 (`PedidosDBISAM.consultar_stock`, `SINVDEP` depósito 1)
para que la suma asignada nunca supere el total en a2. Pero esa es la única
integración que existe hoy:

1. El flujo de picking (`PedidosAlmacen`, donde el picker carga
   `PedidoItem.cantidad_preparada` vía la app móvil) no toca `ubicaciones` en
   absoluto — las cantidades por ubicación quedan estáticas hasta que alguien
   las edite a mano.
2. a2 puede cambiar por operaciones que no pasan por la app en absoluto
   (venta de mostrador, compra, ajuste directo en el POS a2), sin que
   Postgres se entere de qué ubicación física se vio afectada. No hay ninguna
   reconciliación entre el total de a2 y la suma de lo asignado por
   ubicación.

La asignación de ubicaciones a productos es progresiva — no todo el
inventario tiene ubicación asignada todavía — por lo que la solución debe
convivir con productos sin ninguna ubicación sin romper el flujo de picking
actual, y sin bloquear nunca la operación de pedidos por un problema de
organización del almacén.

## Principios de diseño

1. **a2 (`SINVDEP` depósito 1) es la única fuente de verdad del total.** No
   se le enseña a conocer ubicaciones; su esquema no se toca.
2. **Postgres (`ubicaciones`) es la única fuente de verdad de la
   distribución por ubicación**, y esa asignación es progresiva.
3. **Diferencia a2 vs. suma de ubicaciones:** si `a2_total ≥
   suma(ubicaciones)`, la diferencia es simplemente stock sin asignar
   todavía — no es una incidencia. Si `a2_total < suma(ubicaciones)`, hubo
   una salida externa sin pasar por la app — es una incidencia que se
   autocorrige y queda pendiente de revisión.
4. **`ubicaciones` nunca bloquea el flujo operativo de `PedidosAlmacen`.**
   Guardar `cantidad_preparada` siempre procede, tenga o no tenga el
   producto ubicaciones asignadas, y aunque haya ambigüedad de dónde
   descontar. Cuando el sistema no puede determinar sin ambigüedad de qué
   ubicación descontar, no adivina: registra una incidencia
   `pendiente_revision` y sigue.
5. **Un SKU puede ocupar varias ubicaciones PICKING y varias ALMACENAJE a la
   vez**, sin restricción 1:1.

## Alcance

- Cambios de modelo en `ubicaciones`: `ProductoUbicacion.es_principal`;
  `MovimientoUbicacion` gana `cantidad`, `pendiente_revision`,
  `revisado_por`, `fecha_revision`, `pedido_item` (FK laxa a
  `PedidosAlmacen.PedidoItem`), `activo`; nuevos tipos `PICKING` y
  `AJUSTE_A2`.
- Nuevo método de servicio `UbicacionesService.descontar_por_picking(...)`,
  reentrante, y `marcar_principal(...)` / `resolver_incidencia(...)`.
- Nuevo management command `ubicaciones/management/commands/
  reconciliar_existencias.py` (job periódico, ejecutado por el Task
  Scheduler de Windows, mismo patrón que `validar_traslados_recepcion`).
- Integración en `PedidosAlmacen`: `api_update_item` y `api_preparar_pedido`
  (y sus contrapartes web equivalentes si existen) llaman a
  `descontar_por_picking` cada vez que se guarda `cantidad_preparada`.
- API nueva en `ubicaciones`: listar/resolver incidencias
  (`pendiente_revision`) y marcar/desmarcar `es_principal`.

Fuera de alcance: reposición automática ALMACENAJE→PICKING por
`stock_minimo` (el campo ya existe pero no hay alertas automáticas todavía);
cambios al despacho final (`despachar_pedido`) o al traslado a2 ya
existente; reversión de la deducción de ubicación al anular un despacho (ver
"Manejo de errores").

## Modelo de datos

### `ProductoUbicacion`

Nuevo campo `es_principal` (`BooleanField`, `default=False`). Marca, por
`codigo_producto`, la ubicación que usa el job de reconciliación cuando hay
ambigüedad entre varias. El servicio garantiza unicidad a nivel de
aplicación: al marcar una como principal, desmarca cualquier otra del mismo
`codigo_producto` (mismo patrón de validación en servicio que usa el resto
de la app, sin constraint de BD).

### `MovimientoUbicacion`

Nuevos valores en `TIPO_CHOICES`:

```python
('PICKING', 'Descuento por picking'),
('AJUSTE_A2', 'Ajuste por reconciliación con a2'),
```

Nuevos campos:

| Campo | Tipo | Uso |
|---|---|---|
| `cantidad` | `IntegerField`, `null=True`, `blank=True` | Magnitud del movimiento. Hoy el log no guarda cantidades; se necesita para picking y para el detalle del ajuste/incidencia. |
| `pendiente_revision` | `BooleanField`, `default=False` | Solo se usa en `PICKING` (con faltante) y `AJUSTE_A2`. |
| `revisado_por` | `FK` a usuario, `on_delete=SET_NULL`, `null=True`, `blank=True` | Quién cerró la incidencia. |
| `fecha_revision` | `DateTimeField`, `null=True`, `blank=True` | |
| `pedido_item` | `FK` laxa a `'PedidosAlmacen.PedidoItem'`, `on_delete=CASCADE`, `null=True`, `blank=True`, `related_name='movimientos_ubicacion'` | Solo se usa en `PICKING`; permite ubicar y revertir el descuento vigente de un ítem. |
| `activo` | `BooleanField`, `default=True` | Solo tiene sentido en `PICKING`: `True` mientras el descuento sigue vigente; se pone `False` al revertir por reedición. En el resto de los tipos queda `True` sin usarse (no se filtra por él). |

## Servicio: `UbicacionesService.descontar_por_picking`

```python
@staticmethod
@transaction.atomic
def descontar_por_picking(
    pedido_item,            # PedidosAlmacen.PedidoItem
    cantidad: int,          # cantidad_preparada que se está guardando ahora
    usuario,
    nivel_id: int | None = None,  # ubicación elegida por el picker, si aplica
) -> dict:
    ...
```

Es **reentrante**: se llama cada vez que se guarda `cantidad_preparada` para
ese ítem (desde `api_update_item` o `api_preparar_pedido`), no solo una vez.

Pasos:

1. **Revertir lo vigente.** Busca, con `select_for_update`, el
   `MovimientoUbicacion(tipo=PICKING, pedido_item=pedido_item, activo=True)`
   más reciente (a lo sumo uno). Si existe, devuelve su `cantidad` al
   `ProductoUbicacion` correspondiente (si esa asignación ya no existe —fue
   trasladada o eliminada— se recrea con esa cantidad, igual patrón que
   `trasladar_producto` con `get_or_create`) y lo marca `activo=False`.
2. **Resolver ubicación de origen** para la nueva `cantidad`, según cuántas
   `ProductoUbicacion` con `nivel__tipo=PICKING` (activo, no fusionado) tiene
   el `codigo` del ítem:
   - **0** → no hay nada que descontar. Se retorna sin crear movimiento.
     (Cubre también `cantidad == 0`: solo se ejecuta el paso 1 de reversión.)
   - **1** → se usa esa automáticamente, ignorando `nivel_id` si vino vacío o
     si coincide.
   - **Varias** → requiere `nivel_id` explícito (elegido por el picker en la
     app móvil, que antes consultó `GET /api/productos/<codigo>/
     ubicaciones/`). Si no vino `nivel_id`, o no corresponde a una
     `ProductoUbicacion` PICKING de ese código, **no se descuenta nada**: se
     registra `MovimientoUbicacion(tipo=PICKING, pedido_item=pedido_item,
     codigo_producto=codigo, cantidad=cantidad, pendiente_revision=True,
     activo=False, notas='Ambigüedad: varias ubicaciones PICKING, ninguna
     indicada')` y se retorna. (`activo=False` porque no hay descuento
     vigente que revertir después.)
3. **Aplicar el descuento** (cuando el paso 2 resolvió una ubicación única).
   Con `select_for_update` sobre esa `ProductoUbicacion`: si `cantidad` >
   disponible, se deja en 0 y se registra la diferencia como incidencia
   (`pendiente_revision=True`) en el mismo movimiento; si alcanza, se
   descuenta completo sin incidencia. En ambos casos se crea
   `MovimientoUbicacion(tipo=PICKING, pedido_item=pedido_item,
   nivel_origen=nivel, codigo_producto=codigo, cantidad=cantidad,
   activo=True, pendiente_revision=<bool>)`.

El paso 1 siempre corre (incluida cuando `cantidad == 0`, ej. el picker
reduce a nada o el ítem se revierte a `BACK_ORDER`/`PENDIENTE` antes de
despachar), así que reeditar cualquier número de veces antes del despacho
mantiene la ubicación consistente con el último valor guardado.

**Nunca lanza excepción por temas de stock/ambigüedad** — a diferencia del
resto de `UbicacionesService` (que sí usa `ValidationError` para
operaciones manuales), este método está pensado para no frenar el guardado
del pedido; cualquier problema queda como incidencia, no como error.

## Integración con `PedidosAlmacen`

- `api_update_item` (`PATCH /api/pedidos/<pedido_pk>/items/<item_pk>/`) y
  `api_preparar_pedido` (`POST /api/pedidos/<pk>/preparar/`): después de
  guardar `cantidad_preparada` en el `PedidoItem`, llaman a
  `UbicacionesService.descontar_por_picking(item, nueva_cantidad, request.user,
  nivel_id=request.data.get('ubicacion_picking'))`. El resultado (incidencia
  sí/no) se puede incluir en la respuesta para que la app móvil lo muestre
  como aviso no bloqueante, pero **no cambia el código de estado de la
  respuesta** — el guardado del ítem ya fue exitoso.
- **No se dispara** cuando `cantidad_preparada` se limpia a `None` como parte
  de la creación de un `Despacho` (el stock ya salió físicamente de la
  ubicación; ese descuento queda como vigente/definitivo). Se llama
  explícitamente solo desde los dos puntos de entrada donde el picker
  registra una cantidad, no desde el código de despacho.
- La app móvil, antes de guardar un ítem cuyo código tiene más de una
  `ProductoUbicacion` PICKING, puede mostrarle al picker el listado (ya
  expuesto por `GET /api/productos/<codigo>/ubicaciones/`) para que elija;
  si no lo hace, el guardado igual se completa (ver principio 4) y queda una
  incidencia para revisión.

## Reconciliación con a2 (job periódico)

`ubicaciones/management/commands/reconciliar_existencias.py`, solo lectura
sobre a2 pero con escritura en Postgres (a diferencia de
`validar_traslados_recepcion`), ejecutado por el Task Scheduler de Windows.

Por cada `codigo_producto` con al menos una `ProductoUbicacion` activa:

1. Trae el total de a2 en lote con `consultar_stock_multiple` (batch, no una
   consulta por producto).
2. Calcula `suma_ubicaciones = sum(cantidad de sus ProductoUbicacion)`.
3. Si `existencia_a2 >= suma_ubicaciones`: nada que hacer.
4. Si `existencia_a2 < suma_ubicaciones`: `faltante = suma_ubicaciones -
   existencia_a2`.
   - Si el producto tiene **una sola** `ProductoUbicacion` (sin importar
     tipo): se resuelve esa como ubicación a ajustar.
   - Si tiene **varias** y una está marcada `es_principal=True`: se resuelve
     esa.
   - Si tiene **varias** y ninguna es principal: no se resuelve ninguna — no
     se descuenta nada, solo queda la incidencia (ver más abajo).
   - Cuando sí se resolvió una ubicación, se le descuenta `faltante`,
     clavado a 0 si `faltante` supera lo que esa ubicación tiene registrado
     (el campo `cantidad` de `ProductoUbicacion` nunca queda negativo).
   - En todos los casos de faltante, registra `MovimientoUbicacion(tipo=
     AJUSTE_A2, codigo_producto=codigo, cantidad=faltante,
     pendiente_revision=True, nivel_destino=<ubicación tocada o None si no
     se pudo resolver>)`.

Todo por producto dentro de `@transaction.atomic` con `select_for_update`,
igual que el resto de `UbicacionesService` (se añade un método de servicio
`ajustar_por_reconciliacion_a2` que encapsula el paso 4, para que el comando
solo orqueste la iteración y el cálculo de diferencias).

## API

Nuevos endpoints en `ubicaciones/api_urls.py` (mismo esquema de auth:
`SessionAuthentication`/`TokenAuthentication` + `IsAuthenticated`):

| Método y ruta | Uso |
|---|---|
| `GET /api/ubicaciones/incidencias/` | Lista `MovimientoUbicacion` con `pendiente_revision=True`, filtrable por `codigo` y `tipo` (`PICKING`/`AJUSTE_A2`). |
| `POST /api/ubicaciones/movimientos/<pk>/resolver/` | Supervisor marca una incidencia como revisada (`pendiente_revision=False`, `revisado_por`, `fecha_revision`), con nota opcional. |
| `POST /api/producto-ubicaciones/<pk>/marcar-principal/` | Marca esa `ProductoUbicacion` como `es_principal=True` para su `codigo_producto`, desmarcando cualquier otra del mismo código. |

`api_producto_ubicaciones` (ya existente,
`GET /api/productos/<codigo>/ubicaciones/`) no cambia de forma — sigue
siendo la fuente para que la app móvil muestre las opciones PICKING al
picker cuando hay ambigüedad.

## Manejo de errores

| Caso | Comportamiento |
|---|---|
| Producto sin ninguna ubicación PICKING | `descontar_por_picking` no hace nada; el guardado del ítem procede igual que hoy. |
| Varias ubicaciones PICKING, ninguna indicada | Guardado del ítem procede; se registra incidencia `pendiente_revision=True`, sin descuento. |
| `cantidad_preparada` > disponible en la ubicación resuelta | Guardado del ítem procede; ubicación queda en 0; incidencia `pendiente_revision=True` con el faltante. |
| Reedición de `cantidad_preparada` (cualquier valor, incluido 0) | Se revierte el descuento vigente (`activo=True` anterior) y se reaplica según el nuevo valor. |
| `consultar_stock_multiple` falla (DBISAM caído) durante `reconciliar_existencias` | El comando reporta el error y aborta ese lote sin modificar Postgres a medias (igual criterio que `_validar_cantidad_contra_a2`, que propaga la excepción). |
| Despacho anulado (`anular_despacho`) | **No** revierte el descuento de ubicación — mismo criterio que ya usa el sistema con el traslado a2 (`anular_despacho` tampoco lo revierte). Queda documentado como limitación aceptada, no como bug. |

## Testing

- **Servicio** (`ubicaciones/tests.py`): `descontar_por_picking` — sin
  ubicación, una sola ubicación, varias sin indicar (incidencia sin
  descuento), varias con `nivel_id` válido, faltante de stock (incidencia
  con descuento a 0), reedición que revierte y reaplica (varias veces,
  incluido a 0), `es_principal` (unicidad al marcar).
- **Comando `reconciliar_existencias`** (mock de `PedidosDBISAM`): sin
  diferencia, diferencia positiva (sin acción), diferencia negativa con una
  sola ubicación, diferencia negativa con varias y `es_principal` marcada,
  diferencia negativa con varias sin marcar (solo incidencia, sin
  descuento).
- **Integración `PedidosAlmacen`** (`PedidosAlmacen/tests.py`):
  `api_update_item`/`api_preparar_pedido` descuentan ubicación al guardar;
  guardar dos veces seguidas no duplica el descuento; despacho no revierte.
- DBISAM se mockea siguiendo el patrón ya usado en el proyecto
  (`test_settings.py` + SQLite, sin conexión real a DBISAM en tests).
