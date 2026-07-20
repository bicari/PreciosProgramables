# Sistema de Sincronización de Ventas DBISAM

## Descripción del Proyecto
Aplicacion de DJANGO conectada al sistema a2Softway mediante ODBC dbisam, pedidos internos de almacen, notas de entrega de proveedor, progrmacion de lista de precios y envios de correos de notificacion, impresion de etiquetas de listas de precios.

La app esta divida en varios apps como son PedidosAlmacen, ProgramarPrecios, notas_entrega

## Stack Tecnológico
- Lenguaje: Python 3.11.1+
- Conector: pyodbc para ODBC
- Base de datos: DBISAM (para consulta de productos, insercion de notas de entrega, pedidos de almacen, ofertas)
- Base de datos: PostgreSQL (tareas programadas, pedidos almacen, detalle pedidos, usuarios)
- Estándar SQL: SQL92
- Logging: logging + archivo rotativo
- Configuración: decouple



## Configuración de Conexión ODBC

### DSN de DBISAM
DSN configurado en ODBC Data Sources (64-bit)


### Verificar Drivers DBISAM
```bash
# Windows - listar drivers ODBC disponibles
import pyodbc
print(pyodbc.drivers())
# Debe aparecer: "DBISAM 4 ODBC Driver" o similar
```



## Convenciones de Código Python

### Estilo General
- Seguir PEP 8 estrictamente
- Usar type hints en todas las funciones
- Docstrings en formato Google para funciones públicas
- Nombres de variables en snake_case
- Nombres de clases en PascalCase
- Constantes en UPPER_SNAKE_CASE
- Entorno virtual venv

### Ejemplo de Función
```python
def sincronizar_ventas(fecha: datetime.date, dry_run: bool = False) -> dict[str, int]:
    """
    Sincroniza las ventas de una fecha específica.
    
    Args:
        fecha: Fecha de las ventas a sincronizar
        dry_run: Si es True, simula sin escribir en BD destino
        
    Returns:
        Diccionario con estadísticas: {'sincronizadas': 150, 'errores': 2}
        
    Raises:
        ConnectionError: Si falla la conexión a BD
        ValueError: Si la fecha es inválida
    """
    # Implementación...
```

### Manejo de Conexiones
```python
# SIEMPRE usar context managers para conexiones
with crear_conexion(dsn, user, password) as conn:
    with conn.cursor() as cursor:
        cursor.execute(query)
        # Operaciones...
    # Commit automático al salir del context
```

## SQL92 y DBISAM - Consideraciones Especiales

<important if="escribiendo queries SQL">
DBISAM usa SQL92 estándar pero con limitaciones:
- NO soporta: CTEs (WITH), MERGE, ventanas analíticas, EXISTS
- SÍ soporta: JOIN, subqueries, GROUP BY, ORDER BY
- Usar CAST explícito para conversiones de tipo
- Fechas en formato: 'YYYY-MM-DD' o 'YYYY-MM-DD HH:MM:SS'
</important>

### Queries Permitidas
```sql
-- ✅ CORRECTO - SQL92 básico
SELECT v.id_venta, v.fecha, v.total, c.nombre
FROM ventas v
INNER JOIN clientes c ON v.id_cliente = c.id_cliente
WHERE v.fecha = '2024-03-15'
ORDER BY v.id_venta;

-- ✅ CORRECTO - Subquery
SELECT * FROM ventas
WHERE id_cliente IN (
    SELECT id_cliente FROM clientes WHERE activo = 1
);

-- ❌ INCORRECTO - CTE no soportado
WITH ventas_hoy AS (
    SELECT * FROM ventas WHERE fecha = CURRENT_DATE
)
SELECT * FROM ventas_hoy;
```

### Tipos de Datos DBISAM
- INTEGER, SMALLINT, LARGEINT (no BIGINT)
- DECIMAL(p,s), NUMERIC(p,s)
- VARCHAR(n), CHAR(n)
- DATE, TIME, TIMESTAMP
- BOOLEAN (TRUE/FALSE)
- BLOB, CLOB



## Manejo de Errores Común

### Errores ODBC Típicos
- `[HY000]`: Error general DBISAM - revisar logs DBISAM
- `[08001]`: No se puede conectar - verificar DSN
- `[42S02]`: Tabla no existe - verificar nombre de tabla
- `[23000]`: Violación de constraint - duplicado o FK inválida
- `[HYT00]`: Timeout - ajustar SYNC_TIMEOUT

### Manejo en Código
```python
import pyodbc

try:
    cursor.execute(query)
except pyodbc.IntegrityError as e:
    # Duplicado o FK inválida
    logger.warning(f"Registro ya existe: {e}")
    continue
except pyodbc.OperationalError as e:
    # Error de conexión o timeout
    logger.error(f"Error operacional: {e}")
    raise ConnectionError("Fallo en conexión DBISAM")
except pyodbc.DataError as e:
    # Tipo de dato incorrecto
    logger.error(f"Error de datos: {e}")
    raise ValueError("Datos inválidos para DBISAM")
```

## Logging

### Configuración
- **Archivo**: logs/sync_ventas.log (rotativo, max 10MB, 5 backups)
- **Consola**: solo INFO y superior
- **Formato**: `[%(asctime)s] %(levelname)s - %(message)s`

### Niveles de Log
```python
logger.debug("Conectando a DSN: {dsn}")          # Debug detallado
logger.info("Sincronizadas 150 ventas")          # Info general
logger.warning("Venta ID 123 ya existe, skip")   # Advertencias
logger.error("Fallo conexión: {error}")          # Errores
logger.critical("BD destino inaccesible")        # Críticos
```

## Contactos y Documentación

### Referencias pyodbc
- Documentación oficial: https://github.com/mkleehammer/pyodbc/wiki
- Guía de errores: https://github.com/mkleehammer/pyodbc/wiki/Exceptions
- Soporte de dbisam : https://www.elevatesoft.com/manual?action=topics&id=dbisam4&product=rsdelphi&version=XE&section=sql_reference
# Tablas de operaciones de base de datos
SOPERACIONINV = Aqui se encuentran las operaciones de Compras, Ventas, Devolucion de compras, devolucion de ventas, clasificadas por tipos
SDETALLECOMPRA = Esta tabla esta relacionada con SOPERACIONINV mediante FTI_AUTOINCREMENT = FDI_OPERACION_AUTOINCREMENT aqui se encuentran los productos relacionados a la compra y devolucion de compra
SDETALLEVENTA = Esta tabla esta relacionada con SOPERACIONINV mediante FTI_AUTOINCREMENT = FDI_OPERACION_AUTOINCREMENT aqui se encuentran los productos relacionados a la venta y devolucion de venta
SINVDEP = Esta tabla se encuentran los codigos de los productos por deposito con sus existencias actuales, se relaciona con las tablas SDETALLECOMPRA y SDETALLEVENTA mediante el codigo del producto.

# Referencia de tipos de operaciones en las tablas
1 : Traslados
2 : Cargos
3 : Descargos
4 : Ajustes
5 : Órdenes de Compras
6 : Compras
7 : Devolución de Compras
8 : Notas de Entrega en Compras
9 : Presupuestos
10 : Pedidos
11 : Facturas
12 : Devolución de Ventas
13 : Notas de Entrega en Ventas
14 : Apartados
23 : Órdenes de Servicios

