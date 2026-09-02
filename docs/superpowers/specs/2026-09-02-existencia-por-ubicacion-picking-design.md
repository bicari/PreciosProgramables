# Existencia por ubicación con reconciliación gradual contra a2

**Fecha:** 2026-09-02

## Problema

Hoy la app `ubicaciones` permite asignar productos a ubicaciones físicas con
una cantidad (`ProductoUbicacion.cantidad`), validada contra la existencia
real en a2 (DBISAM, `SINVDEP` depósito 1) mediante
`UbicacionesService._validar_cantidad_contra_a2` — la suma de cantidades
asignadas de un producto nunca puede superar su existencia real. Sin
embargo:

1. No hay visibilidad de cuánta existencia de un producto **no** tiene
   ubicación asignada todavía. Un producto con 180 unidades en a2, 50 en una
   ubicación PICKING y 120 en una ALMACENAJE, tiene 10 unidades "flotantes"
   que hoy no aparecen en ningún lado — solo son deducibles restando a mano.
2. El flujo de picking (`PedidosAlmacen.views.preparar_pedido`, donde el
   picker carga `PedidoItem.cantidad_preparada`) no toca la app `ubicaciones`
   en absoluto. Preparar un pedido no rebaja la existencia de la ubicación
   PICKING de la que físicamente se tomó la mercancía — las cantidades de
   `ProductoUbicacion` quedan estáticas hasta que alguien las edite a mano.

La asignación de ubicaciones a productos es un proceso gradual (no hay un
big-bang de migración de todo el inventario), por lo que la solución debe
convivir con productos que aún no tienen ninguna ubicación asignada sin
romper el flujo de picking actual.

## Alcance

- Nuevo modelo `ExistenciaSinUbicacion` en la app `ubicaciones`: registro
  persistente por producto con la cantidad que existe en a2 pero no tiene
  ubicación asignada, recalculado de forma síncrona en las operaciones que
  cambian la suma asignada de un producto.
- Nuevo modelo `PickingOrigen` en la app `ubicaciones`: ledger de qué
  ubicación PICKING se debitó, y cuánto, por cada `PedidoItem` preparado.
- Nuevo método de servicio `UbicacionesService.aplicar_picking(...)` que
  descuenta existencia de una o más ubicaciones PICKING al preparar un
  pedido, con reversión automática al reeditar.
- Cambios en `PedidosAlmacen.views.preparar_pedido` y su plantilla para que
  el picker elija de qué ubicación(es) PICKING tomó cada producto, cuando
  el producto tiene alguna asignada.
- Nueva vista de reporte "sin ubicación" en `ubicaciones`.

Fuera de alcance: job periódico de reconciliación contra a2 (se documenta
como limitación aceptada, ver más abajo), flujo de reposición
automática desde ALMACENAJE hacia PICKING, y cualquier cambio al despacho
final (`despachar_pedido`) o al traslado a2 ya existente.

## Decisiones (acordadas con el usuario)

1. **"Sin ubicación" es un registro persistente**, no un valor calculado al
   vuelo en cada request. Permite historial/consulta sin recorrer todo
   `ProductoUbicacion` cada vez y deja rastro de cuándo se actualizó por
   última vez.
2. **Deducción de picking: el picker elige la ubicación de origen.** Cuando
   un producto tiene más de una ubicación PICKING asignada, la UI muestra
   las opciones y el picker indica de cuál(es) tomó las unidades — no hay
   un orden automático ni una regla de "una sola ubicación PICKING por
   producto".
3. **División entre varias ubicaciones permitida.** El picker puede repartir
   la `cantidad_preparada` de un ítem entre varias ubicaciones PICKING del
   mismo producto en una misma preparación (ej. 30 de una y 20 de otra).
4. **Si falta stock registrado en PICKING: bloquear y avisar.** Si la suma
   de lo disponible en las ubicaciones PICKING del producto no alcanza la
   cantidad que el picker quiere preparar, no se permite continuar; se
   informa el faltante para que se reasignen/trasladen ubicaciones antes.
   No hay autocompletado silencioso desde ALMACENAJE ni incidencias
   automáticas de descuadre.
5. **Momento de la deducción: al preparar, no al despachar.** La existencia
   de ubicaciones PICKING se rebaja en `preparar_pedido` (cuando el picker
   confirma `cantidad_preparada`), que es el momento físico real en que se
   retira la mercancía de su posición. `despachar_pedido` (confirmación de
   Almacén, con el traslado a2 ya existente) no cambia.
6. **Reversión automática al reeditar.** El picker puede reeditar
   `cantidad_preparada` de un ítem varias veces antes del despacho final
   (`preparar_pedido` es reentrante mientras el pedido esté en
   `ASIGNADO`/`PICKING`/`EN_PREPARACION`). Cada vez que se reedita, se
   revierte con precisión lo debitado la vez anterior (usando el registro
   `PickingOrigen`) y se vuelve a aplicar según la nueva distribución que
   indique el picker.
7. **Producto sin ninguna ubicación PICKING asignada: preparar sin deducir.**
   Dado que la asignación es gradual, si un producto no tiene ninguna
   `ProductoUbicacion` con `nivel.tipo == PICKING`, `preparar_pedido`
   funciona exactamente como hoy — no se pide origen ni se descuenta nada.
   Esto evita que la funcionalidad nueva bloquee el flujo de picking
   mientras se completa la asignación de ubicaciones al catálogo.
8. **Captura de existencia a2: solo síncrona, sin job periódico.** No existe
   forma de "tiempo real" real (DBISAM/ODBC no notifica cambios). Se usa el
   patrón ya existente en `PedidosDBISAM.consultar_stock(codigo, deposito)`
   — una consulta SQL en el momento — disparada únicamente dentro de
   `UbicacionesService.asignar_producto`, `editar_cantidad` y
   `quitar_producto` (los 3 métodos que cambian la suma asignada de un
   producto). `trasladar_producto` y `fusionar_niveles`/`desfusionar_nivel`
   no la disparan porque no cambian la suma total del producto.
   **Limitación aceptada:** si la existencia en a2 cambia sin que nadie
   toque `ubicaciones` para ese producto (ej. entra una compra), el
   registro `ExistenciaSinUbicacion` de ese producto queda desactualizado
   hasta la próxima asignación/edición/quitar sobre él. Se puede agregar
   un job periódico más adelante si se vuelve un problema operativo.

## Modelo de datos

### `ExistenciaSinUbicacion` (app `ubicaciones`)

| Campo | Tipo | Notas |
|---|---|---|
| `codigo_producto` | `CharField`, único, indexado | Código DBISAM del producto |
| `existencia_a2` | `IntegerField` | Última lectura de `consultar_stock`, snapshot |
| `cantidad_asignada` | `IntegerField` | Suma de `ProductoUbicacion.cantidad` para ese producto al momento del recálculo |
| `cantidad_sin_ubicacion` | `IntegerField` | `existencia_a2 - cantidad_asignada`. **No se clampa a 0**: un valor negativo indica que hay más cantidad asignada en `ubicaciones` que existencia real en a2 (descuadre, ej. la existencia bajó en a2 después de haber asignado) y debe mostrarse como alerta, no ocultarse |
| `fecha_actualizacion` | `DateTimeField`, `auto_now` | |

Se hace *upsert* (`update_or_create`) por `codigo_producto` desde un método
nuevo `UbicacionesService._recalcular_sin_ubicacion(codigo_producto)`,
llamado al final de `asignar_producto`, `editar_cantidad` y
`quitar_producto`, dentro de la misma transacción atómica de esos métodos.

### `PickingOrigen` (app `ubicaciones`)

Ledger de qué ubicación PICKING se debitó por cada ítem de pedido
preparado. Sigue el mismo patrón que `MovimientoUbicacion`: FK dura al
`Nivel` (para poder navegar y agregar), pero `codigo_producto` como texto
plano en vez de FK a `ProductoUbicacion` — así el historial no se rompe si
esa asignación puntual se elimina o traslada después.

| Campo | Tipo | Notas |
|---|---|---|
| `pedido_item` | `FK` a `PedidosAlmacen.PedidoItem`, `on_delete=CASCADE`, `related_name='origenes_picking'` | |
| `nivel` | `FK` a `Nivel`, `on_delete=PROTECT` | Debe ser `tipo=PICKING` al momento de aplicar |
| `codigo_producto` | `CharField` | Denormalizado |
| `cantidad` | `PositiveIntegerField` | Cantidad debitada de ese nivel para ese ítem |
| `usuario` | `FK` a usuario, `on_delete=SET_NULL`, `null=True` | Quién preparó |
| `fecha` | `DateTimeField`, `auto_now_add` | |

Puede haber varias filas por `pedido_item` (una por cada ubicación de la que
se tomó una porción).

### `MovimientoUbicacion`

Se agrega un valor nuevo a `TIPO_CHOICES`: `('PICKING', 'Descuento por picking')`,
registrado por `aplicar_picking` igual que el resto de operaciones de la
app (con `nivel_origen` apuntando al `Nivel` debitado y `codigo_producto`
seteado).

## Servicio: `UbicacionesService.aplicar_picking`

```python
@staticmethod
@transaction.atomic
def aplicar_picking(
    pedido_item,               # PedidosAlmacen.PedidoItem
    origenes: list[dict],      # [{'nivel_id': int, 'cantidad': int}, ...]
    usuario,
) -> None:
    ...
```

Pasos:

1. **Revertir lo anterior.** Con `select_for_update`, toma todos los
   `PickingOrigen` existentes de `pedido_item`, devuelve la `cantidad` de
   cada uno a su `ProductoUbicacion(codigo_producto, nivel)` (si ya no
   existe esa asignación —fue trasladada o eliminada— se recrea con esa
   cantidad, igual que hace `trasladar_producto` con `get_or_create`), y
   borra los `PickingOrigen`.
2. **Validar la nueva distribución.** `sum(o['cantidad'] for o in origenes)`
   debe ser igual a la nueva `cantidad_preparada` que se está guardando
   para ese ítem. Cada `nivel_id` debe existir, pertenecer a un `Nivel` con
   `tipo == PICKING` y no estar fusionado.
3. **Aplicar y validar stock.** Para cada origen, toma el
   `ProductoUbicacion(codigo_producto, nivel)` con `select_for_update`; si
   `cantidad` solicitada > `cantidad` disponible en esa ubicación, aborta
   toda la operación con `ValidationError` detallando el faltante (no se
   deja la reversión del paso 1 aplicada a medias: todo ocurre en la misma
   transacción atómica, así que un error revierte también el paso 1).
   Si pasa la validación, descuenta `cantidad` de cada `ProductoUbicacion`.
4. **Registrar.** Crea un `PickingOrigen` por cada origen aplicado y un
   `MovimientoUbicacion` tipo `PICKING`.

Si `pedido_item.codigo` no tiene ninguna `ProductoUbicacion` con
`nivel__tipo=PICKING`, la vista (ver abajo) no llama a este método en
absoluto para ese ítem.

## Cambios en `PedidosAlmacen.views.preparar_pedido`

Al construir `items_con_stock` para el template, para cada ítem se agrega:

- `ubicaciones_picking`: lista de `ProductoUbicacion` con
  `nivel__tipo=PICKING` para `item.codigo` (vacía si no tiene ninguna).

En el `POST`, además de leer `cantidad_<item.id>` (como hoy), si
`ubicaciones_picking` no está vacía se leen también los campos de origen
por ubicación (ej. `origen_<item.id>_<nivel.id>`) y se arma la lista
`origenes` para pasar a `aplicar_picking`. Se valida en el view que la suma
de los orígenes coincida con la cantidad ingresada antes de llamar al
servicio; si `aplicar_picking` lanza `ValidationError` (stock insuficiente),
se muestra el mensaje de error y no se guarda el ítem (igual patrón que
usa hoy `despachar_pedido` con los excesos de stock a2).

Ítems cuyo producto no tiene ubicaciones PICKING asignadas se guardan
exactamente como hoy, sin pasar por `aplicar_picking`.

`templates/pedidos-preparar.html` (o el template que use esa vista) se
actualiza para mostrar, por ítem con `ubicaciones_picking`, un desglose de
inputs (una fila por ubicación con su disponible y un campo de cantidad a
tomar de ahí), sumando en el cliente para ayudar al picker a cuadrar el
total antes de enviar.

## Vista de reporte "sin ubicación"

Nueva vista en `ubicaciones` (mismo permiso que el resto de la app, grupo
`Pedidos Ubicaciones`), listando `ExistenciaSinUbicacion` con
`cantidad_sin_ubicacion != 0`, ordenada por mayor cantidad absoluta,
mostrando código, existencia a2, asignado, sin ubicación y última
actualización. Los valores negativos (descuadre) se resaltan visualmente
como alerta.

## Manejo de errores

| Caso | Comportamiento |
|---|---|
| Suma de orígenes ≠ cantidad_preparada | `ValidationError` en el servicio; el view no guarda el ítem y muestra el mensaje |
| Origen apunta a un `Nivel` que no es PICKING o está fusionado | `ValidationError` |
| Cantidad solicitada de un origen > disponible en esa ubicación | `ValidationError` con el faltante; no se aplica nada de ese ítem (transacción atómica) |
| Producto sin ninguna ubicación PICKING | Se ignora `aplicar_picking`; comportamiento idéntico al actual |
| `consultar_stock` falla (DBISAM caído) al recalcular `ExistenciaSinUbicacion` | Se propaga como hoy hace `_validar_cantidad_contra_a2` (la operación de `ubicaciones` que la dispara falla completa; no se deja el registro a medias) |

## Testing

- **Servicio** (`ubicaciones/tests.py`): `aplicar_picking` con una sola
  ubicación, con split entre dos, reversión al reeditar (cantidad menor,
  mayor, y a 0), bloqueo por stock insuficiente, producto sin ubicación
  PICKING no genera `PickingOrigen` ni `MovimientoUbicacion`.
- **Recálculo `ExistenciaSinUbicacion`**: tras `asignar_producto`,
  `editar_cantidad`, `quitar_producto` — incluyendo el caso de valor
  negativo (descuadre).
- **Vista `preparar_pedido`** (`PedidosAlmacen/tests.py`): guardar con
  distribución válida, con distribución que no cuadra (error), con
  producto sin ubicaciones (sin cambios), reedición que revierte y
  reaplica correctamente.
- DBISAM se mockea siguiendo el patrón ya usado en el proyecto
  (`test_settings.py` + SQLite, sin conexión real a DBISAM en tests).
