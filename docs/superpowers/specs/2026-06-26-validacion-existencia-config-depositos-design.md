# Diseño: Validación de existencia y configuración de depósitos en PedidosAlmacen

**Fecha:** 2026-06-26
**Módulo:** `PedidosAlmacen`
**Estado:** Aprobado para implementación

## Problema

Actualmente en el módulo de pedidos de almacén un usuario puede crear pedidos con
productos que no tienen existencia en el depósito almacén. No hay ninguna alerta ni
restricción. Además, el selector de "Depósito de origen" muestra todos los depósitos
de a2 (excepto el 1), sin posibilidad de limitar cuáles puede elegir el usuario.

## Objetivos

1. Impedir que se agreguen al pedido productos sin existencia en el depósito almacén.
2. Permitir filtrar la búsqueda para mostrar solo productos con existencia.
3. Crear una tabla de configuración (gestionable solo desde el admin de Django) que
   determine qué depósitos puede seleccionar el usuario al crear un pedido.

## Decisiones tomadas

- **Depósito de referencia para existencia:** siempre el **depósito 1 (almacén)**, sin
  importar el "Depósito de origen" que el usuario seleccione en el pedido. Es el
  comportamiento que `buscar_en_categoria` ya tiene (`FT_CODIGODEPOSITO = 1`).
- **Tipo de restricción:** bloquear al agregar. Un producto con existencia 0 no puede
  entrar al carrito del pedido.
- **Checkbox "Solo con existencia":** activado por defecto en la búsqueda.
- **Gestión de depósitos permitidos:** modelo Django poblado por sincronización desde
  SDEPOSITOS + flag `activo` que el admin marca. El selector muestra solo los activos.
- **Fallback de configuración:** si no hay ningún depósito activo (tabla vacía o nada
  marcado), el selector cae al comportamiento actual (todos los depósitos excepto el 1).

## Arquitectura general

Tres cambios coordinados. Ninguno modifica el flujo de despacho/picking/recepción.

| # | Pieza | Capa |
|---|-------|------|
| A | Filtro "Solo con existencia" en búsqueda | DBISAM query + frontend |
| B | Bloqueo de agregar productos sin existencia | Frontend (búsqueda + carrito) |
| C | Tabla de configuración de depósitos permitidos | Modelo Django + admin + sync DBISAM |

## Componente A — Filtro "Solo con existencia" (default ON)

**Frontend** (`templates/pedidos-crear.html`):
- Checkbox `Solo con existencia` junto al buscador de productos, **marcado por defecto**.
- Se envía como parámetro `solo_existencia=1` en la petición HTMX de búsqueda, junto con
  los parámetros existentes (`q`, `tipo`, `categoria`).

**Vista** (`PedidosAlmacen/views.py::buscar_producto`):
- Leer `request.GET.get('solo_existencia')` y traducirlo a un booleano.
- Pasarlo a `buscar_en_categoria(categoria, query, tipo, solo_existencia=...)`.

**DBISAM** (`PedidosAlmacen/dbisam.py::buscar_en_categoria`):
- Nuevo parámetro `solo_existencia: bool = False`.
- Cuando es `True`, añadir `AND FT_EXISTENCIA > 0` al WHERE. El filtrado se hace en SQL,
  no en Python.
- La query sigue uniendo `SINVENTARIO INNER JOIN SINVDEP` sobre `FT_CODIGODEPOSITO = 1`.

**Resultado** (`templates/pedidos-buscar-producto.html`):
- La columna "Existencia" se mantiene visible siempre.
- Con el check desmarcado, los productos con existencia 0 aparecen con su badge rojo.

### Consideración SQL/DBISAM

DBISAM no soporta queries parametrizadas con `?`. Mantener el estilo f-string del resto
del módulo. El nuevo flag `solo_existencia` es un booleano interno (no entrada de
usuario libre), así que se interpola como fragmento SQL fijo (`AND FT_EXISTENCIA > 0`),
sin riesgo de inyección.

## Componente B — Bloqueo al agregar (existencia 0)

**Resultado de búsqueda** (`templates/pedidos-buscar-producto.html`):
- Para productos con `existencia <= 0`, el botón "Agregar" se renderiza **deshabilitado**
  (`disabled`) con un tooltip/`title` "Sin existencia en almacén".
- El dato de existencia ya viene en `producto.existencia`, no requiere consulta extra.

**Nota sobre revalidación en servidor (opcional, NO incluida por defecto):**
La barrera elegida es el frontend ("bloquear al agregar"). No se agrega revalidación
obligatoria en `crear_pedido`. Queda señalado como posible mejora futura una
revalidación ligera en servidor (consultar `consultar_stock_multiple` de los códigos
del carrito antes de persistir) como red de seguridad ante manipulación del formulario
o cambios de existencia entre la búsqueda y el envío. Por ahora **fuera de alcance**.

## Componente C — Tabla de configuración de depósitos

**Modelo nuevo** (`PedidosAlmacen/models.py`):

```python
class DepositoPermitido(models.Model):
    codigo = models.IntegerField(unique=True)      # FDP_CODIGO de SDEPOSITOS
    nombre = models.CharField(max_length=150)      # FDP_DESCRIPCION
    activo = models.BooleanField(default=False)
    fecha_sync = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"
```

**Sincronización desde a2 (admin-only):**
- Nuevo método `PedidosDBISAM.obtener_todos_depositos()` que lee SDEPOSITOS
  (`FDP_CODIGO`, `FDP_DESCRIPCION`) excluyendo el depósito 1, igual que el
  `obtener_depositos()` actual.
- Una acción del admin (`admin.action`) "Sincronizar depósitos desde a2" que:
  - Llama `obtener_todos_depositos()`.
  - Hace upsert por `codigo`: crea los que no existen, actualiza `nombre` de los
    existentes, **sin pisar el flag `activo`** de los ya configurados.
- El admin luego marca el check `activo` en los depósitos que quiera habilitar.

**Admin** (`PedidosAlmacen/admin.py`):
- `DepositoPermitidoAdmin` registrado con:
  - `list_display = ('codigo', 'nombre', 'activo', 'fecha_sync')`
  - `list_editable = ('activo',)` para activar/desactivar rápido en lote.
  - `actions = [sincronizar_depositos]`.

**Consumo** (`PedidosAlmacen/views.py::crear_pedido`):
- Reemplazar `depositos = dbisam.obtener_depositos()` por:
  - `activos = DepositoPermitido.objects.filter(activo=True).order_by('nombre')`
  - Si `activos.exists()`: usar esos (exponer `codigo` y `nombre` al template con la
    misma forma que hoy consume `pedidos-crear.html`).
  - Si **no** hay activos (fallback): caer a `dbisam.obtener_depositos()` (comportamiento
    actual). Si la conexión DBISAM falla, mantener el manejo de error actual (lista vacía).
- El template `pedidos-crear.html` debe iterar la lista de depósitos de forma uniforme
  independientemente del origen (modelo o DBISAM); ajustar el acceso a `codigo`/`nombre`
  si las dos fuentes difieren en estructura (normalizar a una lista de dicts o tuplas).

## Migración, datos y pruebas

- Nueva migración en `PedidosAlmacen/migrations/` para `DepositoPermitido`.
- Sin data migration: la tabla nace vacía; el fallback cubre ese estado hasta que el
  admin sincronice y active depósitos.
- Pruebas:
  - `buscar_en_categoria` con `solo_existencia=True` añade el filtro y excluye existencia 0;
    con `False` (o ausente) mantiene el comportamiento actual.
  - `crear_pedido`: con depósitos activos muestra solo esos; sin activos cae al fallback
    (todos menos el 1).
  - El botón "Agregar" se renderiza `disabled` cuando `existencia <= 0`.

## Fuera de alcance

- Revalidación de existencia en el servidor al crear el pedido (señalada como mejora
  futura en el Componente B).
- Validación de existencia contra un depósito distinto al 1.
- Cambios en el flujo de despacho, picking o recepción.
