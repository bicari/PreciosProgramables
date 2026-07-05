# Validar Traslados de Recepción en a2 — Diseño

## Problema

Al recibir un despacho (`PedidosAlmacen/views.py`, función `recibir_despacho`), el
estado del despacho y del pedido se guarda en Postgres como `RECIBIDO` o
`PARCIAL` **antes** de intentar el traslado tránsito(10)→destino en a2
(`dbisam.insertar_traslado_recepcion`, líneas 1041-1054). Si ese traslado falla
(timeout, error de conexión, excepción de DBISAM), el código solo muestra un
`messages.error()` — fácil de perder — y no queda ningún registro persistente
del fallo.

Esto contrasta con el paso de **despacho** (almacén→tránsito), que sí tiene
protección: el modelo `Despacho.traslado_a2_registrado` (booleano) se marca en
`confirmar_despacho`, y existe un botón de reintento manual
(`reintentar_traslado_despacho`) visible para superusuarios cuando el flag es
`False`.

Resultado observado: pedidos marcados como `RECIBIDO` en la app cuyo traslado
tránsito→destino nunca se registró en a2 — las existencias de los productos
recibidos no se actualizan en el sistema a2.

## Alcance

Esta herramienta valida **únicamente el paso de recepción** (tránsito→destino).
El paso de despacho (almacén→tránsito) ya es auditable directamente en
Postgres vía `Despacho.traslado_a2_registrado=False`, sin necesitar consultar
DBISAM.

Es una herramienta de **solo lectura / diagnóstico**. No corrige nada
automáticamente, no modifica Postgres ni a2. El operador decide manualmente
qué hacer con cada caso detectado (ej. registrar el traslado a mano en a2, o
investigar el motivo del fallo original).

## Restricción de precisión (conocida y aceptada)

Cuando un pedido tiene varios despachos parciales, cada recepción llama a
`insertar_traslado_recepcion(numero_pedido, ...)` usando el **mismo**
`FTI_DOCUMENTO` (el número de pedido) en `SOPERACIONINV` — a2 no distingue a
qué despacho corresponde cada traslado. Por eso la validación es de
**existencia simple**: por cada pedido candidato, ¿existe al menos una fila en
`SOPERACIONINV` con ese documento y tipo tránsito→destino? No se valida
correspondencia 1:1 entre número de despachos recibidos y número de traslados
registrados.

## Componentes

### 1. Nuevo método en `PedidosAlmacen/dbisam.py`

```python
def traslados_recepcion_existentes(self, numeros_pedido: list[int]) -> set[int]:
    """
    Verifica cuáles de los pedidos dados tienen registrado el traslado de
    recepción (tránsito → destino) en a2 (SOPERACIONINV).

    Args:
        numeros_pedido: Números de pedido (PK de Pedido en Postgres) a
            verificar.

    Returns:
        Conjunto de números de pedido que SÍ tienen el traslado registrado
        en a2. Los que falten del conjunto de entrada son los problemáticos.

    Raises:
        pyodbc.DatabaseError: Si falla la conexión o la consulta.
    """
```

- Arma `FTI_DOCUMENTO` paddeando cada número a 8 dígitos (mismo formato usado
  por `insertar_traslado_recepcion` / `existe_traslado_despacho`).
- Consulta en lotes de 200 documentos por vez (evita queries `IN (...)`
  excesivamente largas contra DBISAM histórico).
- Filtra `FTI_TIPO = 1 AND FTI_DEPOSITOSOURCE = DEPOSITO_TRANSITO`.
- SQL base (SQL92, sin CTE/EXISTS/derived tables, consistente con las
  limitaciones de DBISAM documentadas en `CLAUDE.md`):

```sql
SELECT DISTINCT FTI_DOCUMENTO
FROM SOPERACIONINV
WHERE FTI_TIPO = 1
  AND FTI_DEPOSITOSOURCE = 10
  AND FTI_DOCUMENTO IN ('00001234','00001235', ...)
```

### 2. Nuevo management command

`PedidosAlmacen/management/commands/validar_traslados_recepcion.py`

Sigue el estilo de `reset_pedidos.py`: `BaseCommand`, docstring de uso,
`add_arguments`, métodos privados con prefijo `_`, `self.style` para output,
logging con `logger.info`/`logger.warning`.

**Argumentos:**
- `--dias N` (int, opcional): limita a pedidos cuya `fecha_recepcion` esté
  dentro de los últimos N días. Sin este flag, revisa todo el histórico.
- `--pedido N` (int, opcional): revisa un único número de pedido puntual
  (spot-check). Si se pasa junto con `--dias`, `--pedido` tiene prioridad y
  `--dias` se ignora.

**Flujo (`handle`):**
1. Construir queryset de candidatos: `Pedido.objects.filter(despachos__estado__in=['RECIBIDO', 'PARCIAL']).exclude(deposito_codigo__isnull=True).distinct()`.
   - Si `--pedido` está presente, filtrar `numero_pedido=<valor>` en vez de
     lo anterior.
   - Si `--dias` está presente (y no hay `--pedido`), agregar
     `.filter(fecha_recepcion__gte=timezone.now() - timedelta(days=dias))`.
2. Obtener `values_list('numero_pedido', 'solicitante__username', 'fecha_recepcion', 'deposito_codigo')`, ordenado por `fecha_recepcion` descendente.
3. Si no hay candidatos, imprimir mensaje informativo y salir.
4. Llamar `PedidosDBISAM().traslados_recepcion_existentes([n for n, *_ in candidatos])`.
5. Calcular `problematicos = [c for c in candidatos if c[0] not in existentes]`.
6. Imprimir reporte:
   - Encabezado con total de candidatos revisados.
   - Por cada pedido problemático: `#<numero> | <solicitante> | <fecha_recepcion> | depósito destino <deposito_codigo>` en rojo (`self.style.ERROR`).
   - Resumen final: `"X de Y pedidos sin traslado de recepción en a2"` (`self.style.WARNING` si X>0, `self.style.SUCCESS` si X==0).
7. Capturar excepciones de `pyodbc.DatabaseError` del paso DBISAM y mostrar error claro (`self.style.ERROR`) sin traceback crudo.

**Uso:**
```bash
python manage.py validar_traslados_recepcion
python manage.py validar_traslados_recepcion --dias 30
python manage.py validar_traslados_recepcion --pedido 1234
```

## Testing

- Test unitario para `traslados_recepcion_existentes` mockeando `pyodbc`/conexión (sigue el patrón de tests existentes para `PedidosDBISAM` si existen, o test manual dado que requiere DSN real).
- Test del management command con `Pedido`/`Despacho` de fixture en Postgres y `PedidosDBISAM` mockeado (parchear el método nuevo para devolver un `set` controlado), verificando que el comando identifica correctamente a los pedidos ausentes del set devuelto.

## Fuera de alcance

- No se corrige ni reintenta el traslado faltante automáticamente.
- No se valida el paso de despacho (almacén→tránsito) — ya cubierto por `traslado_a2_registrado`.
- No se verifica correspondencia de cantidades entre lo recibido en la app y lo trasladado en a2 — solo existencia del traslado.
- No se agrega UI ni vista web; es exclusivamente un comando de consola.
