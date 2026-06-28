# Reasignar/Liberar Picker en Pedidos PARCIAL — Diseño

**Fecha:** 2026-06-28
**App:** `PedidosAlmacen`
**Estado:** Aprobado (pendiente de plan de implementación)

## Problema

Cuando un pedido pasa a estado **PARCIAL** tras un despacho parcial con back orders,
**conserva su `picker` anterior** (no se limpia en `despachar`/`confirmar`/`preparar`;
solo en `anular_pedido` y `desasignar_picker`). En la lista de pedidos:

- El botón **asignar** solo aparece cuando `not pedido.picker`.
- El botón **liberar** solo aparece para estados `ASIGNADO`/`PICKING`.

Resultado: un PARCIAL con picker retenido no muestra ningún control, y el picker
**no ve los PARCIAL** en su cola (`lista_pedidos` para solo-picker filtra
`ASIGNADO`/`PICKING`/`EN_PREPARACION`). El pedido queda atascado: nadie puede
continuar la recolección de los back orders.

## Objetivo

Permitir que un **supervisor** reasigne (mismo u otro picker) o libere el picker de un
pedido PARCIAL con back orders, para que la recolección de los ítems pendientes pueda
continuar.

## Decisiones de alcance (confirmadas con el usuario)

1. **Picker en PARCIAL:** Se **retiene** el picker anterior al pasar a PARCIAL (no se
   libera automáticamente). Se añaden controles para que el supervisor lo cambie o lo
   libere manualmente.
2. **Reactivación:** El supervisor **reasigna** (vía el flujo existente `asignar_picker`),
   lo que mueve el pedido de `PARCIAL` a `ASIGNADO` y lo devuelve a la cola del picker.
   No se modifica el filtro de la cola del picker.
3. **Controles en PARCIAL con picker:** botón **reasignar** y botón **liberar**.

## Diseño

### 1. Backend (`PedidosAlmacen/views.py`)

**`asignar_picker`** — sin cambios funcionales. Ya valida `PARCIAL + back orders`
(guard existente: `if pedido.estado not in ('PENDIENTE',) and not
(pedido.estado == 'PARCIAL' and tiene_bo)`) y sobrescribe `pedido.picker`, dejando el
pedido en `ASIGNADO` con `fecha_asignacion` actualizada. Sirve tanto para asignar como
para reasignar (mismo o distinto picker).

**`desasignar_picker`** — ampliar el guard de estados permitidos para incluir también
`PARCIAL`:

```python
if pedido.estado not in ('ASIGNADO', 'PICKING', 'PARCIAL'):
    messages.warning(request, f'El pedido #{pk} no está en estado Asignado, Picking o Parcial y no puede liberarse')
    return redirect('pedidos-lista')
```

La lógica posterior ya recalcula `pedido.estado = 'PARCIAL' if tiene_bo else 'PENDIENTE'`,
por lo que liberar un PARCIAL con back orders deja `picker=None`, `fecha_asignacion=None`
y el estado **PARCIAL**.

### 2. UI (`templates/pedidos-lista.html`)

En la celda del picker, dentro del bloque `{% if pedido.picker %}` y solo para
supervisor:

- Estados `ASIGNADO`/`PICKING`: se mantiene el botón **liberar** actual (sin cambios).
- Estado `PARCIAL` con `pedido.items_back_order > 0`: mostrar **dos** botones:
  - **Reasignar** → reutiliza el modal existente `#modalAsignarPicker` con
    `data-pedido-id="{{ pedido.numero_pedido }}"` (mismo `data-bs-toggle`/`data-bs-target`
    que el botón de asignar). El modal postea a `asignar_picker`.
  - **Liberar** → formulario POST a `pedidos-desasignar-picker` (igual markup que el
    botón liberar existente, con su `confirm`).

El bloque `{% else %}` (sin picker) ya muestra el botón **asignar** para
`PENDIENTE` o `PARCIAL` con back orders (línea 113 actual); sin cambios.

### 3. Flujo resultante

```
PARCIAL (con picker) --[Reasignar]--> ASIGNADO (picker elegido) --> el picker continúa los back orders
PARCIAL (con picker) --[Liberar]----> PARCIAL (sin picker) --[Asignar]--> ASIGNADO
PARCIAL (sin picker) --[Asignar]----> ASIGNADO   (ya funciona hoy)
```

## Pruebas (TDD)

- `asignar_picker` sobre un pedido PARCIAL con picker ya asignado y back orders →
  estado `ASIGNADO`, `picker` actualizado al nuevo, `fecha_asignacion` no nula.
- `desasignar_picker` sobre un pedido PARCIAL con picker → `picker=None`, estado sigue
  `PARCIAL`.
- `desasignar_picker` sobre un PARCIAL sin back orders (caso borde) → estado `PENDIENTE`
  (lógica existente).
- Plantilla: para un pedido PARCIAL con picker y usuario supervisor, el HTML de la lista
  incluye el botón **reasignar** (target `#modalAsignarPicker`) y el botón **liberar**
  (acción `pedidos-desasignar-picker`).
- Plantilla: un usuario no supervisor no ve esos controles.

## Permisos (resumen)

| Acción | Tienda | Almacén | Picker | Supervisor | Superuser |
|--------|:------:|:-------:|:------:|:----------:|:---------:|
| Reasignar/liberar picker en PARCIAL | ✘ | ✘ | ✘ | ✔ | ✔ |

(`is_pedidos_supervisor` ya incluye `is_superuser`.)

## Criterios de aceptación

- Un supervisor ve, en un pedido PARCIAL con picker y back orders, los botones
  **reasignar** y **liberar**.
- Reasignar mueve el pedido a `ASIGNADO` con el picker elegido (mismo u otro) y reaparece
  en la cola de ese picker.
- Liberar deja el pedido en `PARCIAL` sin picker, mostrando luego el botón **asignar**.
- Un no supervisor no ve ninguno de esos controles.
- No se modifica el filtro de la cola del picker, ni el flujo de despacho, ni la
  integración con a2.

## Fuera de alcance

- No se modifica el filtro de la cola del picker (`lista_pedidos` solo-picker).
- No se libera el picker automáticamente al pasar a PARCIAL.
- No se toca a2 ni el flujo de despacho/recepción.
