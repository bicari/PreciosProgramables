"""Lectura y validación pura del Excel de carga masiva de pedidos.

Sin dependencias de Django ni DBISAM — recibe `productos`/`categorias_map`
ya resueltos, para que la lógica de validación por fila sea testeable sin
mocks de conexión.
"""
import pandas as pd

MAX_FILAS = 500
MAX_SKU_LEN = 30
COLUMNAS_REQUERIDAS = ('SKU', 'Cantidad')


class ExcelPedidoError(Exception):
    """Error de archivo completo: columnas faltantes, exceso de filas, o
    archivo ilegible. No se procesa nada cuando se lanza esta excepción."""


def leer_filas_pedido(archivo) -> list[dict]:
    """Lee un .xlsx/.xls y devuelve las filas crudas de datos.

    Args:
        archivo: objeto tipo archivo (ej. UploadedFile de Django) con las
            columnas SKU, Cantidad en la fila de encabezado (fila 1).

    Returns:
        Lista de dicts {'fila': int, 'sku': valor_crudo, 'cantidad': valor_crudo},
        sin validar todavía — `construir_items` hace la validación por fila.
        `fila` es el número de fila real en el Excel (la de encabezado es 1).

    Raises:
        ExcelPedidoError: el archivo no se puede leer, faltan columnas
            requeridas, o supera MAX_FILAS filas de datos.
    """
    try:
        df = pd.read_excel(archivo, header=0, dtype={'SKU': str}, nrows=MAX_FILAS + 1)
    except Exception as e:
        raise ExcelPedidoError(f'No se pudo leer el archivo: {e}')

    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in df.columns]
    if faltantes:
        raise ExcelPedidoError(f'Faltan columnas requeridas: {", ".join(faltantes)}')

    if len(df) > MAX_FILAS:
        raise ExcelPedidoError(f'El archivo supera el máximo de {MAX_FILAS} filas')

    return [
        {'fila': idx + 2, 'sku': row['SKU'], 'cantidad': row['Cantidad']}
        for idx, row in df.iterrows()
    ]


def construir_items(filas: list[dict], productos: dict, categorias_map: dict) -> tuple[list[dict], list[dict]]:
    """Valida cada fila, resuelve contra `productos`, suma SKU repetidos.

    Args:
        filas: Salida de `leer_filas_pedido`.
        productos: Salida de `PedidosDBISAM.resolver_productos` — dict
            indexado por código normalizado (stripped + uppercase), con
            codigo/descripcion/referencia/puesto/ref_proveedor/categoria.
        categorias_map: Dict código→nombre de categoría (de
            `PedidosDBISAM.obtener_categorias()`), para resolver
            categoria_nombre.

    Returns:
        (items, omitidos). Cada item trae codigo/descripcion/referencia/
        puesto/ref_proveedor/cantidad/categoria/categoria_nombre. Cada
        omitido trae fila/sku/motivo.
    """
    items_por_codigo: dict[str, dict] = {}
    omitidos: list[dict] = []

    for fila in filas:
        sku = fila['sku']
        if not isinstance(sku, str) or not sku.strip():
            omitidos.append({'fila': fila['fila'], 'sku': str(sku), 'motivo': 'SKU vacío'})
            continue
        sku = sku.strip()

        if len(sku) > MAX_SKU_LEN:
            omitidos.append({'fila': fila['fila'], 'sku': sku[:MAX_SKU_LEN] + '...', 'motivo': 'SKU inválido (demasiado largo)'})
            continue

        try:
            cantidad = int(fila['cantidad'])
        except (TypeError, ValueError):
            cantidad = None
        if cantidad is None or cantidad <= 0:
            omitidos.append({'fila': fila['fila'], 'sku': sku, 'motivo': 'Cantidad inválida'})
            continue

        info = productos.get(sku.upper())
        if info is None:
            omitidos.append({'fila': fila['fila'], 'sku': sku, 'motivo': 'SKU no encontrado en a2'})
            continue

        codigo = info['codigo']
        if codigo in items_por_codigo:
            items_por_codigo[codigo]['cantidad'] += cantidad
        else:
            items_por_codigo[codigo] = {
                'codigo': codigo,
                'descripcion': info['descripcion'],
                'referencia': info['referencia'],
                'puesto': info['puesto'],
                'ref_proveedor': info['ref_proveedor'],
                'cantidad': cantidad,
                'categoria': info['categoria'],
                'categoria_nombre': categorias_map.get(info['categoria'], info['categoria']),
            }

    return list(items_por_codigo.values()), omitidos
