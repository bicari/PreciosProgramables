# Verificación por Pistoleo en Despacho — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar un widget de pistoleo (scanner de código de barras) a la tabla de despacho en estado `PENDIENTE_APROBACION` que resalte cada artículo verificado y alerte cuando un código no pertenece al pedido.

**Architecture:** Cambio 100% en frontend. Se añaden atributos `data-*` a las filas del template para exponer los campos buscables, se inserta el widget HTML en la card del despacho (solo visible para supervisores en estado `PENDIENTE_APROBACION`), y se implementa la función JS `iniciarPistoleo` que busca por coincidencia exacta contra esos atributos y gestiona el estado visual.

**Tech Stack:** Django 5.2, Jinja/Django Templates, Bootstrap 5, JavaScript vanilla (sin dependencias adicionales), Font Awesome 6.

## Global Constraints

- Solo se modifica `templates/pedidos-detalle.html` — cero cambios en modelos, vistas, URLs o migraciones.
- El widget es visible únicamente cuando `despacho.estado == 'PENDIENTE_APROBACION'` AND `es_supervisor == True`.
- El estado de pistoleo (filas resaltadas, contador) vive en memoria del navegador — no persiste en BD.
- El botón "Confirmar Despacho" y su lógica JS existente no se tocan.
- Las clases CSS nuevas usan el prefijo `pd-pistoleo-` o `pd-fila-verificada` para no colisionar con estilos existentes.
- Búsqueda exacta (no parcial), case-insensitive, solo en `Enter`.

---

## Mapa de archivos

| Archivo | Acción | Responsabilidad |
|---|---|---|
| `templates/pedidos-detalle.html` | Modificar | Atributos data-*, widget HTML, CSS, JS |

---

### Task 1: Atributos `data-*` en filas de la tabla del despacho

**Files:**
- Modify: `templates/pedidos-detalle.html` — bloque `{% for di in despacho.items.all %}` dentro de `pd-despacho-table`

**Interfaces:**
- Produce: cada `<tr>` del despacho expone `data-di-id`, `data-codigo`, `data-referencia`, `data-ref-proveedor` que la función JS de la Tarea 3 leerá con `fila.dataset.codigo`, `fila.dataset.referencia`, `fila.dataset.refProveedor`

---

- [ ] **Paso 1: Verificar el estado actual de las filas**

Abrir `templates/pedidos-detalle.html` y localizar el bloque que contiene:
```
{% for di in despacho.items.all %}
<tr>
```
Está dentro de la tabla `pd-despacho-table`, alrededor de la línea donde aparece `data-label="Código"`. Confirmar que el `<tr>` actual NO tiene atributos `data-*`.

- [ ] **Paso 2: Agregar los atributos `data-*` al `<tr>`**

Localizar en `templates/pedidos-detalle.html`:
```html
                        {% for di in despacho.items.all %}
                        <tr>
```

Reemplazar por:
```html
                        {% for di in despacho.items.all %}
                        <tr data-di-id="{{ di.id }}"
                            data-codigo="{{ di.pedido_item.codigo|lower }}"
                            data-referencia="{{ di.pedido_item.referencia|lower }}"
                            data-ref-proveedor="{{ di.pedido_item.ref_proveedor|lower }}">
```

- [ ] **Paso 3: Verificar en el navegador**

1. Arrancar el servidor: `python manage.py runserver`
2. Navegar a un pedido que tenga un despacho en estado `PENDIENTE_APROBACION` como usuario supervisor (ej. `/pedidos/25/`)
3. Abrir DevTools → Inspector
4. Encontrar cualquier `<tr>` dentro de la tabla del despacho
5. Confirmar que tiene los cuatro atributos:
   - `data-di-id="[número]"`
   - `data-codigo="[código en minúsculas]"`
   - `data-referencia="[referencia en minúsculas o vacío]"`
   - `data-ref-proveedor="[ref proveedor en minúsculas o vacío]"`

- [ ] **Paso 4: Commit**

```bash
git add templates/pedidos-detalle.html
git commit -m "feat(pedidos): data attributes en filas del despacho para pistoleo"
```

---

### Task 2: Widget HTML del pistoleo + ícono de verificación + CSS

**Files:**
- Modify: `templates/pedidos-detalle.html` — bloque `pd-despacho-body` y bloque `<style>`

**Interfaces:**
- Consume: `despacho.numero_despacho` (integer), `despacho.items.all|length` (integer) — ya disponibles en el contexto del template
- Produce:
  - `id="pd-pistoleo-{{ despacho.numero_despacho }}"` — input de pistoleo que la Tarea 3 buscará
  - `id="pd-counter-{{ despacho.numero_despacho }}"` — elemento contador con `data-count="0"` y `data-total="{{ despacho.items.all|length }}"`
  - `id="pd-alert-{{ despacho.numero_despacho }}"` — zona de alerta roja, oculta por defecto con clase `d-none`
  - `.pd-check-icon.d-none` dentro de cada celda "A Despachar" — se mostrará por JS al verificar
  - Clases CSS: `.pd-pistoleo-wrap`, `.pd-pistoleo-header`, `.pd-pistoleo-label`, `.pd-pistoleo-counter`, `.pd-counter-completo`, `.pd-pistoleo-alert`, `.pd-fila-verificada`, `.pd-check-icon`

---

- [ ] **Paso 1: Insertar el widget HTML antes del filtro de texto**

Localizar en `templates/pedidos-detalle.html` el inicio del bloque `pd-despacho-body`:
```html
            <div class="pd-despacho-body">
                <div class="pd-despacho-filter">
```

Reemplazar por:
```html
            <div class="pd-despacho-body">
                {% if despacho.estado == 'PENDIENTE_APROBACION' and es_supervisor %}
                <div class="pd-pistoleo-wrap mb-3">
                    <div class="pd-pistoleo-header">
                        <span class="pd-pistoleo-label">
                            <i class="fas fa-barcode me-1"></i>Verificación de artículos
                        </span>
                        <span class="pd-pistoleo-counter"
                              id="pd-counter-{{ despacho.numero_despacho }}"
                              data-count="0"
                              data-total="{{ despacho.items.all|length }}">
                            0 / {{ despacho.items.all|length }} verificados
                        </span>
                    </div>
                    <div class="input-group input-group-sm">
                        <span class="input-group-text bg-white text-muted">
                            <i class="fas fa-barcode"></i>
                        </span>
                        <input type="text"
                               id="pd-pistoleo-{{ despacho.numero_despacho }}"
                               class="form-control pd-pistoleo-field"
                               placeholder="Pistolée o escriba el código…"
                               autocomplete="off"
                               autocorrect="off"
                               spellcheck="false">
                        <button class="btn btn-outline-secondary" type="button"
                                onclick="document.getElementById('pd-pistoleo-{{ despacho.numero_despacho }}').value='';document.getElementById('pd-pistoleo-{{ despacho.numero_despacho }}').focus();">
                            <i class="fas fa-times"></i>
                        </button>
                    </div>
                    <div id="pd-alert-{{ despacho.numero_despacho }}"
                         class="pd-pistoleo-alert d-none mt-2">
                    </div>
                </div>
                {% endif %}
                <div class="pd-despacho-filter">
```

- [ ] **Paso 2: Agregar ícono de verificación en la celda "A Despachar"**

Localizar en `templates/pedidos-detalle.html` la celda de cantidad en `PENDIENTE_APROBACION`:
```html
                            <td data-label="A Despachar">
                                <input type="number" name="cantidad_{{ di.id }}" value="{{ di.cantidad_despachada }}"
                                       min="0" class="form-control form-control-sm" style="max-width:90px;">
                            </td>
```

Reemplazar por:
```html
                            <td data-label="A Despachar">
                                <div class="d-flex align-items-center gap-2">
                                    <input type="number" name="cantidad_{{ di.id }}" value="{{ di.cantidad_despachada }}"
                                           min="0" class="form-control form-control-sm" style="max-width:90px;">
                                    <span class="pd-check-icon d-none">
                                        <i class="fas fa-check-circle text-success"></i>
                                    </span>
                                </div>
                            </td>
```

- [ ] **Paso 3: Agregar CSS al bloque `<style>` del template**

Localizar al final del bloque `<style>` existente en el template (antes de `</style>`):
```css
.btn-despacho-toggle.collapsed .despacho-chevron {
    transform: rotate(-90deg);
}
```

Agregar inmediatamente después de esa regla (antes de `</style>`):
```css

/* ── Widget de pistoleo ──────────────────────────── */
.pd-pistoleo-wrap {
    background: #f8f9fa;
    border: 1px solid #e9ecef;
    border-radius: 8px;
    padding: 0.75rem 1rem;
}

.pd-pistoleo-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 0.6rem;
}

.pd-pistoleo-label {
    font-size: 0.68rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #495057;
}

.pd-pistoleo-counter {
    font-size: 0.75rem;
    font-weight: 600;
    color: #6c757d;
    background: #fff;
    border: 1px solid #dee2e6;
    border-radius: 20px;
    padding: 0.2em 0.75em;
    transition: color 0.3s, background 0.3s, border-color 0.3s;
}

.pd-counter-completo {
    color: #146c43 !important;
    border-color: #a3cfbb !important;
    background: #d1e7dd !important;
}

.pd-pistoleo-field {
    border-left: 0 !important;
    border-radius: 0 !important;
}

.pd-pistoleo-alert {
    font-size: 0.82rem;
    color: #842029;
    background: #f8d7da;
    border: 1px solid #f5c2c7;
    border-radius: 6px;
    padding: 0.35rem 0.75rem;
}

/* ── Fila verificada ─────────────────────────────── */
.pd-fila-verificada {
    background-color: #d1e7dd !important;
    transition: background-color 0.25s ease;
}

.pd-fila-verificada:hover {
    background-color: #b8dfc8 !important;
}

.pd-check-icon {
    font-size: 1rem;
    flex-shrink: 0;
    line-height: 1;
}
```

- [ ] **Paso 4: Verificar visualmente en el navegador**

1. Navegar a un pedido con despacho `PENDIENTE_APROBACION` como supervisor
2. Confirmar que el widget de pistoleo aparece entre el header del despacho y el filtro de texto
3. Confirmar que el contador muestra `0 / N verificados` donde N es el número de ítems del despacho
4. Confirmar que el campo tiene placeholder "Pistolée o escriba el código…"
5. Confirmar que la zona de alerta no es visible (tiene clase `d-none`)
6. Confirmar que junto al input de cada fila hay un ícono de check oculto
7. Navegar a un despacho en estado `ENVIADO` o `RECIBIDO` y confirmar que el widget NO aparece

- [ ] **Paso 5: Commit**

```bash
git add templates/pedidos-detalle.html
git commit -m "feat(pedidos): widget HTML y CSS de pistoleo en tabla de despacho"
```

---

### Task 3: Función JS `iniciarPistoleo` e inicialización

**Files:**
- Modify: `templates/pedidos-detalle.html` — bloque `<script>` existente al final del template

**Interfaces:**
- Consume:
  - `id="pd-pistoleo-{{ despacho.numero_despacho }}"` — campo input (producido en Task 2)
  - `id="pd-counter-{{ despacho.numero_despacho }}"` con `data-count` y `data-total` (producido en Task 2)
  - `id="pd-alert-{{ despacho.numero_despacho }}"` (producido en Task 2)
  - `id="tabla-despacho-{{ despacho.numero_despacho }}"` — tabla existente (preexistente en el template)
  - Atributos `data-codigo`, `data-referencia`, `data-ref-proveedor` en `<tr>` (producido en Task 1)
  - Clase `.pd-check-icon` en las filas (producida en Task 2)
- Produce: comportamiento interactivo completo del pistoleo

---

- [ ] **Paso 1: Agregar la función `iniciarPistoleo` al bloque `<script>`**

Localizar al inicio del bloque `<script>` existente en el template (la primera función es `filtrarDespacho`). Insertar la nueva función **antes** de `filtrarDespacho`:

```javascript
function iniciarPistoleo(inputId, tableId, alertZoneId, counterId) {
    var input = document.getElementById(inputId);
    if (!input) return;

    input.addEventListener('keydown', function(e) {
        if (e.key !== 'Enter') return;
        e.preventDefault();

        var query = this.value.trim().toLowerCase();
        if (!query) {
            this.value = '';
            return;
        }

        var tabla = document.getElementById(tableId);
        if (!tabla) return;

        var filas = tabla.querySelectorAll('tbody tr');
        var encontrado = false;

        filas.forEach(function(fila) {
            var codigo      = (fila.dataset.codigo      || '').trim();
            var referencia  = (fila.dataset.referencia  || '').trim();
            var refProv     = (fila.dataset.refProveedor || '').trim();

            if (codigo === query || referencia === query || refProv === query) {
                encontrado = true;
                // Duplicado: ya verificado, no hacer nada
                if (fila.classList.contains('pd-fila-verificada')) return;

                // Resaltar fila
                fila.classList.add('pd-fila-verificada');

                // Mostrar ícono de check
                var checkIcon = fila.querySelector('.pd-check-icon');
                if (checkIcon) checkIcon.classList.remove('d-none');

                // Actualizar contador
                var counterEl = document.getElementById(counterId);
                if (counterEl) {
                    var current = parseInt(counterEl.dataset.count || '0', 10) + 1;
                    var total   = parseInt(counterEl.dataset.total  || '0', 10);
                    counterEl.dataset.count = current;
                    counterEl.textContent   = current + ' / ' + total + ' verificados';
                    if (current >= total && total > 0) {
                        counterEl.classList.add('pd-counter-completo');
                    }
                }
            }
        });

        if (!encontrado) {
            var alertZone = document.getElementById(alertZoneId);
            if (alertZone) {
                alertZone.textContent = '"' + this.value.trim() + '" no pertenece a este despacho';
                alertZone.classList.remove('d-none');
                setTimeout(function() {
                    alertZone.classList.add('d-none');
                    alertZone.textContent = '';
                }, 3000);
            }
        }

        // Limpiar campo listo para el siguiente scan
        this.value = '';
    });
}
```

- [ ] **Paso 2: Agregar las llamadas de inicialización al final del bloque `<script>`**

Localizar el final del bloque `<script>` (después de las líneas de `btn-reintentar-traslado`). Insertar **antes** de `</script>`:

```javascript
// Inicializar pistoleo para cada despacho en PENDIENTE_APROBACION
{% for despacho in despachos %}{% if despacho.estado == 'PENDIENTE_APROBACION' and es_supervisor %}
iniciarPistoleo(
    'pd-pistoleo-{{ despacho.numero_despacho }}',
    'tabla-despacho-{{ despacho.numero_despacho }}',
    'pd-alert-{{ despacho.numero_despacho }}',
    'pd-counter-{{ despacho.numero_despacho }}'
);
{% endif %}{% endfor %}
```

- [ ] **Paso 3: Verificar el flujo de escaneo exitoso**

1. Navegar a un pedido con despacho `PENDIENTE_APROBACION` como supervisor
2. Hacer clic en el campo de pistoleo
3. Escribir el código exacto de uno de los ítems (ej. el valor que aparece en la columna "Código") y presionar `Enter`
4. **Resultado esperado:**
   - La fila correspondiente cambia a fondo verde (`#d1e7dd`)
   - Aparece el ícono de check verde junto al input de cantidad
   - El contador pasa de `0 / N` a `1 / N verificados`
   - El campo de pistoleo queda vacío y con el cursor activo
5. Escribir otro código válido → confirmar que el contador sube a `2 / N`

- [ ] **Paso 4: Verificar el flujo de código no encontrado**

1. Escribir un código inexistente en el campo (ej. `XXXXXX`) y presionar `Enter`
2. **Resultado esperado:**
   - Aparece alerta roja bajo el campo con texto `"XXXXXX" no pertenece a este despacho`
   - El campo queda vacío
   - Después de 3 segundos la alerta desaparece sola
   - Ninguna fila se resalta

- [ ] **Paso 5: Verificar escaneo duplicado**

1. Escanear el mismo código dos veces
2. **Resultado esperado:**
   - En el segundo scan la fila permanece verde sin cambios
   - El contador NO sube (sigue en el mismo número)
   - No aparece alerta ni error

- [ ] **Paso 6: Verificar completitud del contador**

1. Escanear todos los ítems del despacho uno a uno
2. **Resultado esperado:**
   - Al llegar a `N / N`, el contador cambia a fondo verde y texto oscuro (clase `pd-counter-completo`)
   - Todas las filas muestran fondo verde y ícono de check
   - El botón "Confirmar" sigue funcionando igual (el pistoleo no lo bloquea ni lo habilita)

- [ ] **Paso 7: Verificar independencia entre múltiples despachos**

Si el pedido tiene más de un despacho `PENDIENTE_APROBACION`:
1. Escanear un código en el widget del primer despacho
2. Confirmar que el segundo despacho no se ve afectado (su contador sigue en `0 / N`)

- [ ] **Paso 8: Verificar búsqueda por referencia (código de barras)**

Si algún `PedidoItem` tiene campo `referencia` no vacío:
1. En DevTools inspeccionar el `<tr>` y copiar el valor de `data-referencia`
2. Pegar ese valor en el campo de pistoleo y presionar `Enter`
3. Confirmar que la fila se resalta igual que con el código directo

- [ ] **Paso 9: Commit final**

```bash
git add templates/pedidos-detalle.html
git commit -m "feat(pedidos): verificación por pistoleo en tabla de despacho PENDIENTE_APROBACION"
```
