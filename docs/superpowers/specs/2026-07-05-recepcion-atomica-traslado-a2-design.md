# Recepción de Despachos Atómica con Traslado a2 — Diseño

## Problema

Al recibir un despacho (`PedidosAlmacen/views.py`, función `recibir_despacho`,
línea 845), el estado del despacho y del pedido se guarda en Postgres como
`RECIBIDO` o `PARCIAL` (líneas 1028-1039) **antes** de intentar el traslado
tránsito(10)→destino en a2 (`dbisam.insertar_traslado_recepcion`, líneas
1041-1056). Si ese traslado falla (timeout, error de conexión, excepción de
DBISAM), Postgres ya quedó actualizado, generando un **traslado huérfano**:
el pedido figura como recibido en la app pero las existencias del depósito
destino nunca se actualizaron en a2.

Además, cuando el traslado falla, el código actual agrega un
`messages.error(...)` (líneas 1053-1056) pero **inmediatamente después, sin
condicional**, agrega también un `messages.success('Recepción del Despacho
#{id} registrada correctamente')` (línea 1058). Ambos mensajes se renderizan
en `pedidos-detalle.html`, por lo que el usuario ve un mensaje verde de éxito
justo junto al error — fácil de ignorar o de interpretar como que todo salió
bien.

Este problema es específico de la **recepción** (tránsito→destino). El paso
de **despacho** (almacén→tránsito, `confirmar_despacho`) ya tiene protección:
el campo `Despacho.traslado_a2_registrado` se marca en éxito y existe un
botón de reintento manual (`reintentar_traslado_despacho`) para
superusuarios. La recepción no tiene ningún mecanismo equivalente; el único
paliativo hoy es el comando de solo lectura `validar_traslados_recepcion`
(agregado en `76ceac8`/`be59ea3`), que detecta pero no corrige.

## Alcance

- Corrige únicamente el flujo de recepción (`recibir_despacho`). El flujo de
  despacho (`confirmar_despacho`) no se modifica — ya tiene su propio
  mecanismo de detección + reintento y no es donde ocurre el problema
  reportado.
- Corrige el flujo **hacia adelante**: nuevas recepciones ya no podrán quedar
  en un estado inconsistente. Los pedidos históricos ya huérfanos (detectados
  por `validar_traslados_recepcion`) quedan fuera de alcance — se resuelven
  manualmente por un operador en a2.
- No se agrega ningún campo nuevo al modelo ni migración: al bloquear el
  guardado cuando falla el traslado, no puede quedar un estado a medias que
  necesite auditarse con un flag persistente.

## Diseño

### Comportamiento elegido: bloquear la recepción si a2 falla

Se decidió explícitamente **no** replicar el patrón de despacho (guardar en
Postgres igual y marcar un flag para reintento posterior). En su lugar, la
recepción debe ser todo-o-nada: si el traslado en a2 no puede registrarse,
**nada** se persiste en Postgres y el usuario debe reintentar la recepción
completa.

Trade-off aceptado: si a2/DBISAM está caído o lento, el personal de tienda no
podrá registrar ninguna recepción hasta que la conectividad se restablezca.
Se acepta este trade-off a cambio de eliminar por construcción la posibilidad
de traslados huérfanos nuevos.

### Cambio en `recibir_despacho` (`PedidosAlmacen/views.py`)

Envolver en `transaction.atomic()` (patrón ya usado en el mismo archivo, ver
`anular_despacho`, línea 778) todas las escrituras de Postgres que hoy ocurren
sin condición en el bloque POST:

- Actualización de cada `DespachoItem`/`PedidoItem` (líneas 936-986).
- Creación de `PedidoItem`/`DespachoItem` para SKUs no contemplados (líneas
  989-1026).
- Guardado de `Despacho` (estado, receptor, fecha_recepcion — líneas
  1028-1031) y de `Pedido` (estado, fecha_recepcion — líneas 1033-1039).

La llamada a `dbisam.insertar_traslado_recepcion(...)` pasa a ser la **última
operación dentro de ese bloque atómico**, y ya no se envuelve en su propio
`try/except` interno — la excepción se deja propagar para que
`transaction.atomic()` revierta todo lo anterior.

Dentro del bloque, justo antes de la llamada a a2, se reemplaza el guard
actual `if items_traslado and pedido.deposito_codigo:` por una validación
explícita que distingue dos causas de fallo:

```python
if items_traslado:
    if not pedido.deposito_codigo:
        raise ValueError(
            f'El pedido #{pedido.numero_pedido} no tiene depósito destino '
            f'configurado en a2 — no se puede registrar el traslado de '
            f'recepción. Contacta a un supervisor para configurarlo.'
        )
    dbisam.insertar_traslado_recepcion(
        pedido.numero_pedido,
        pedido.deposito_codigo,
        items_traslado,
        responsable=request.user.username,
        proposito=pedido.condicion,
    )
```

Antes, si `pedido.deposito_codigo` era `None`, el traslado se omitía
**silenciosamente** (sin error, sin log) y Postgres guardaba igual — un
segundo origen de traslados huérfanos, distinto del fallo de conexión a2.
Ahora ambos casos bloquean el guardado y notifican al usuario.

Si `items_traslado` está vacío (nada se recibió realmente, p. ej. todo fue
rechazado como incidencia sin cantidad), no hay nada que trasladar y el flujo
continúa sin tocar a2, igual que hoy.

### Manejo de errores y mensajes

Fuera del bloque atómico, un único `try/except` distingue las dos causas y
muestra **un solo** mensaje, sin agregar `messages.success` cuando algo
falló:

```python
try:
    with transaction.atomic():
        ... # mutaciones de items/despacho/pedido
        if items_traslado:
            if not pedido.deposito_codigo:
                raise ValueError(...)
            dbisam.insertar_traslado_recepcion(...)
except ValueError as e:
    logger.error(f'Recepción #{despacho_id} bloqueada: {e}')
    messages.error(request, str(e))
    return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)
except Exception as e:
    logger.error(f'Error al insertar traslado DBISAM para despacho #{despacho_id}: {e}')
    messages.error(
        request,
        'No se pudo registrar la recepción: ocurrió un error al conectar con a2. '
        'No se guardó ningún cambio — intenta nuevamente en unos minutos.'
    )
    return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)

messages.success(request, f'Recepción del Despacho #{despacho_id} registrada correctamente')
return redirect('pedidos-detalle', pk=pk)
```

En caso de error se redirige de vuelta al formulario de recepción
(`pedidos-recibir-despacho`), igual que las demás validaciones ya existentes
en esta vista (líneas 887, 908, 929) — el usuario reingresa cantidades e
incidencias, dado que nada quedó guardado.

### Orden de operaciones (por qué el traslado a2 va al final del bloque)

`insertar_traslado_recepcion` internamente ejecuta su propio
`START TRANSACTION; ... COMMIT;` contra DBISAM (independiente de Postgres, sin
2PC posible entre ambos sistemas). Poniendo la llamada a a2 como última
operación dentro del `atomic()`:

- Si a2 fallara **después** de haber confirmado su propio COMMIT interno pero
  antes de que Postgres confirme (ventana muy pequeña, inherente a no tener
  2PC real), el peor caso posible es que a2 quede actualizado pero Postgres
  no — el inverso del bug original, y estrictamente menos grave (a2 sí
  refleja la existencia real).
- En el resto de los casos (que es la inmensa mayoría), ambos sistemas quedan
  consistentes: los dos confirman o ninguno lo hace.

## Trade-offs aceptados (no se resuelven en este cambio)

- **Fotos de incidencia**: `di.foto_incidencia` y `foto_extras` se escriben a
  disco en el momento del `.save()` del modelo, independientemente de la
  transacción de Postgres. Si `transaction.atomic()` revierte, el archivo
  físico puede quedar huérfano en disco (sin fila que lo referencie). Es una
  limitación conocida de Django (el storage backend no participa de la
  transacción de DB), de bajo impacto — espacio en disco, no integridad de
  datos — y no específica de este bug. No se corrige en este cambio.
- **Casos históricos**: los pedidos ya huérfanos (detectados hoy por
  `validar_traslados_recepcion`) no se remedian automáticamente. Se resuelven
  manualmente por un operador en a2, usando el reporte del comando existente.

## Testing

Casos a cubrir en `PedidosAlmacen/tests.py` (mockeando
`PedidosDBISAM.insertar_traslado_recepcion`):

1. **Recepción exitosa**: `insertar_traslado_recepcion` no lanza excepción →
   `Despacho.estado`, `Pedido.estado`, `PedidoItem`/`DespachoItem` quedan
   actualizados como hoy; se muestra `messages.success` y ningún
   `messages.error`.
2. **Fallo de a2 (excepción de conexión/DBISAM)**: mock lanza
   `pyodbc.DatabaseError` → después del request, `Despacho.estado` y
   `Pedido.estado` deben seguir en su valor previo (`ENVIADO`), ningún
   `PedidoItem`/`DespachoItem` debe haber cambiado, se muestra un único
   `messages.error` y **no** se muestra `messages.success`.
3. **Pedido sin `deposito_codigo` con ítems recibidos**: no se llama siquiera
   a `insertar_traslado_recepcion` (se bloquea antes); mismo assert de "nada
   cambió en Postgres" que el caso 2, con el mensaje específico de depósito
   no configurado.
4. **Recepción sin nada que trasladar** (`items_traslado` vacío, p. ej. todo
   incidencia con cantidad 0): se guarda igual que hoy, sin tocar a2, sin
   error.
5. Regresión: los tests existentes de `recibir_despacho` en
   `PedidosAlmacen/tests.py` deben seguir pasando con el nuevo flujo atómico.

## Fuera de alcance

- No se modifica el flujo de despacho (`confirmar_despacho` /
  `reintentar_traslado_despacho`).
- No se agrega ningún campo nuevo al modelo ni migración.
- No se remedian los traslados huérfanos ya existentes en producción.
- No se corrige el problema de archivos de fotos huérfanos en disco ante un
  rollback.
