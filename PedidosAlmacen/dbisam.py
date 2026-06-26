import pyodbc
import logging
from datetime import datetime
from django.conf import settings

logger = logging.getLogger(__name__)

DEPOSITO_ALMACEN = 1    # Almacén principal (origen en despacho)
DEPOSITO_TRANSITO = 10  # Almacén tránsito (escala entre despacho y recepción)


def _clean(value):
    """Convierte None a string vacio para valores que van al frontend."""
    return '' if value is None else value


class PedidosDBISAM:
    def __init__(self):
        self.dsn = settings.DBISAM_DATABASE['DSN']
        self.catalog = settings.DBISAM_DATABASE['CatalogName']
        self.tmp_table_tasks = settings.DBISAM_DATABASE['TMP_TABLE_TASKS']

    def connect(self):
        return pyodbc.connect(f'DSN={self.dsn};CatalogName={self.catalog};PrivateDirectory={self.tmp_table_tasks}')

    def buscar_producto(self, codigo):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    row = cursor.execute(f"""SELECT
                                            FI_CODIGO,
                                            FI_DESCRIPCION,
                                            FI_REFERENCIA,
                                            FI_PUESTO
                                        FROM SINVENTARIO
                                        WHERE FI_REFERENCIA = '{codigo}' OR FI_CODIGO = '{codigo}'""").fetchone()
                    if row is None:
                        return None
                    return (_clean(row[0]), _clean(row[1]), _clean(row[2]), _clean(row[3]))
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def buscar_producto_por_campo(self, codigo: str, campo: str):
        """Busca un producto por SKU, código de barras o ref. proveedor.

        Args:
            codigo: Valor a buscar (coincidencia exacta).
            campo: 'sku' | 'codBarra' | 'refProveedor'.

        Returns:
            Tuple (FI_CODIGO, FI_DESCRIPCION, FI_REFERENCIA, FI_PUESTO, ZZCAMPO_001) o None.

        Raises:
            ValueError: campo no válido.
            pyodbc.DatabaseError: error de BD.
        """
        mapeo = {
            'sku': 'FI_CODIGO',
            'codBarra': 'FI_REFERENCIA',
            'refProveedor': 'ZZCAMPO_001',
        }
        columna = mapeo.get(campo)
        if not columna:
            raise ValueError(f"Campo inválido: {campo}")

        codigo_esc = codigo.replace("'", "''")
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    row = cursor.execute(f"""SELECT
                                            FI_CODIGO,
                                            FI_DESCRIPCION,
                                            FI_REFERENCIA,
                                            FI_PUESTO,
                                            ZZCAMPO_001
                                        FROM SINVENTARIO
                                        WHERE {columna} = '{codigo_esc}'""").fetchone()
                    if row is None:
                        return None
                    return (_clean(row[0]), _clean(row[1]), _clean(row[2]),
                            _clean(row[3]), _clean(row[4]))
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def buscar_por_descripcion(self, descripcion):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                            FI_CODIGO,
                                            FI_DESCRIPCION,
                                            FI_REFERENCIA,
                                            FI_PUESTO
                                        FROM SINVENTARIO
                                        WHERE FI_DESCRIPCION LIKE '%{descripcion}%'""").fetchmany(50)
                    return [(_clean(r[0]), _clean(r[1]), _clean(r[2]), _clean(r[3])) for r in rows]
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def consultar_stock(self, codigo, deposito=None):
        try:
            deposito_filter = f"AND FT_CODIGODEPOSITO = {deposito}" if deposito else ""
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    row = cursor.execute(f"""SELECT
                                            COALESCE(SUM(FT_EXISTENCIA), 0) AS existencia
                                        FROM SINVDEP
                                        WHERE FT_CODIGOPRODUCTO = '{codigo}' {deposito_filter}""").fetchone()
                    return row.existencia if row else 0
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def consultar_stock_multiple(self, codigos, deposito=None):
        try:
            if not codigos:
                return {}
            codes_str = ','.join(f"'{c}'" for c in codigos)
            deposito_filter = f"AND FT_CODIGODEPOSITO = {deposito}" if deposito else ""
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                            FT_CODIGOPRODUCTO,
                                            COALESCE(SUM(FT_EXISTENCIA), 0) AS existencia
                                        FROM SINVDEP
                                        WHERE FT_CODIGOPRODUCTO IN ({codes_str})
                                        {deposito_filter}
                                        GROUP BY FT_CODIGOPRODUCTO""").fetchall()
                    return {row.FT_CODIGOPRODUCTO: row.existencia for row in rows}
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def obtener_depositos(self):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute("""SELECT
                                            FDP_CODIGO,
                                            FDP_DESCRIPCION
                                        FROM SDEPOSITOS
                                        WHERE FDP_CODIGO <> 1
                                        ORDER BY FDP_DESCRIPCION""").fetchall()
                    return rows
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def obtener_categorias(self):
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute("""SELECT
                                            FD_CODIGO,
                                            FD_DESCRIPCION
                                        FROM SCATEGORIA
                                        ORDER BY FD_DESCRIPCION""").fetchall()
                    return rows
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def _codigos_existentes_sinvdep(self, codigos: list[str], deposito: int, conn) -> set[str]:
        """
        Retorna el conjunto de códigos de producto que ya tienen registro
        en SINVDEP para el depósito indicado.
        """
        codes_str = ','.join(f"'{c}'" for c in codigos)
        rows = conn.cursor().execute(
            f"SELECT FT_CODIGOPRODUCTO FROM SINVDEP "
            f"WHERE FT_CODIGOPRODUCTO IN ({codes_str}) AND FT_CODIGODEPOSITO = {deposito}"
        ).fetchall()
        return {row[0] for row in rows}

    def _insertar_traslado(
        self,
        nro_documento: str,
        deposito_origen: int,
        deposito_destino: int,
        items: list[dict],
        log_ref: str,
        responsable: str = '',
        proposito: str = '',
    ) -> None:
        """Inserta un traslado genérico en SOPERACIONINV/SDETALLEINV y ajusta SINVDEP."""
        fecha = datetime.now().strftime('%Y-%m-%d')
        hora = datetime.now().strftime('%I:%M:%S %p')
        total_items = len(items)

        try:
            with self.connect() as conn:
                codigos = [item['codigo'] for item in items]
                existentes_origen  = self._codigos_existentes_sinvdep(codigos, deposito_origen, conn)
                existentes_destino = self._codigos_existentes_sinvdep(codigos, deposito_destino, conn)

                detalle_queries = []
                update_sinvdep = []

                for linea, item in enumerate(items):
                    codigo = item['codigo']
                    cantidad = item['cantidad']

                    detalle_queries.append(f"""
                        INSERT INTO SDETALLEINV (
                            FDI_DOCUMENTO,
                            FDI_OPERACION_AUTOINCREMENT,
                            FDI_CODIGO,
                            FDI_CANTIDAD,
                            FDI_DEPOSITOSOURCE,
                            FDI_DEPOSITOTARGET,
                            FDI_TIPOOPERACION,
                            FDI_LINEA,
                            FDI_STATUS,
                            FDI_VISIBLE,
                            FDI_FECHAOPERACION,
                            FDI_USER,
                            FDI_UNDDESCARGA,
                            FDI_UNDCAPACIDAD,
                            FDI_MONEDA,
                            FDI_FACTORCAMBIO,
                            FDI_USADEPOSITOS
                        ) VALUES (
                            '{nro_documento}',
                            LASTAUTOINC('SOPERACIONINV'),
                            '{codigo}',
                            {cantidad},
                            {deposito_origen},
                            {deposito_destino},
                            1,
                            {linea},
                            1,
                            1,
                            '{fecha}',
                            1,
                            1,
                            1,
                            1,
                            1,
                            1
                        );
                    """)

                    # Descarga del depósito origen:
                    # Si el producto ya tiene fila en SINVDEP para el origen → restar existencia (UPDATE).
                    # Si no existe (ej. producto de incidencia nunca estuvo en tránsito) → insertar fila
                    # con existencia negativa para reflejar la discrepancia y evitar que el movimiento
                    # quede sin efecto en el inventario.
                    if codigo in existentes_origen:
                        update_sinvdep.append(
                            f"UPDATE SINVDEP SET FT_EXISTENCIA = COALESCE(FT_EXISTENCIA, 0) - {cantidad} "
                            f"WHERE FT_CODIGOPRODUCTO = '{codigo}' AND FT_CODIGODEPOSITO = {deposito_origen};"
                        )
                    else:
                        logger.info(
                            f'SINVDEP: registro no existe para producto={codigo} deposito={deposito_origen} (origen), '
                            f'se insertará con existencia negativa.'
                        )
                        update_sinvdep.append(
                            f"INSERT INTO SINVDEP (FT_TIPO, FT_CODIGOPRODUCTO, FT_CODIGODEPOSITO, FT_EXISTENCIA, FT_VISIBLE, FT_LOTEAUTOINCREMENT) "
                            f"VALUES (4, '{codigo}', {deposito_origen}, -{cantidad}, 1, 0);"
                        )

                    if codigo in existentes_destino:
                        update_sinvdep.append(
                            f"UPDATE SINVDEP SET FT_EXISTENCIA = COALESCE(FT_EXISTENCIA, 0) + {cantidad} "
                            f"WHERE FT_CODIGOPRODUCTO = '{codigo}' AND FT_CODIGODEPOSITO = {deposito_destino};"
                        )
                    else:
                        logger.info(
                            f'SINVDEP: registro no existe para producto={codigo} deposito={deposito_destino}, se insertará.'
                        )
                        update_sinvdep.append(
                            f"INSERT INTO SINVDEP (FT_TIPO, FT_CODIGOPRODUCTO, FT_CODIGODEPOSITO, FT_EXISTENCIA, FT_VISIBLE, FT_LOTEAUTOINCREMENT) "
                            f"VALUES (4, '{codigo}', {deposito_destino}, {cantidad}, 1, 0);"
                        )

                query = f"""
                    START TRANSACTION;
                    INSERT INTO SOPERACIONINV (
                        FTI_DOCUMENTO,
                        FTI_TIPO,
                        FTI_STATUS,
                        FTI_VISIBLE,
                        FTI_FECHAEMISION,
                        FTI_DEPOSITOSOURCE,
                        FTI_DEPOSITODESTINO,
                        FTI_TOTALITEMS,
                        FTI_TOTALITEMSINICIAL,
                        FTI_USER,
                        FTI_UPDATEITEMS,
                        FTI_HORA,
                        FTI_FECHALIBRO,
                        FTI_PROPOSITO,
                        FTI_RESPONSABLE
                    ) VALUES (
                        '{nro_documento}',
                        1,
                        1,
                        1,
                        '{fecha}',
                        {deposito_origen},
                        {deposito_destino},
                        {total_items},
                        {total_items},
                        1,
                        1,
                        '{hora}',
                        '{fecha}',
                        '{proposito}',
                        '{responsable}'
                    );
                    {''.join(detalle_queries)}
                    {''.join(update_sinvdep)}
                """

                with conn.cursor() as cursor:
                    cursor.execute(query)
                    cursor.execute('COMMIT;')

            logger.info(
                f'Traslado DBISAM insertado: {log_ref} origen={deposito_origen} destino={deposito_destino} items={total_items}'
            )
        except Exception as e:
            logger.error(f'Error insertando traslado DBISAM {log_ref}: {e}')
            raise pyodbc.DatabaseError(str(e))

    def existe_traslado_despacho(self, numero_despacho: int) -> bool:
        """
        Verifica si ya existe el traslado de un despacho en a2 (SOPERACIONINV).

        Args:
            numero_despacho: Número del despacho a verificar.

        Returns:
            True si el traslado ya existe en a2, False en caso contrario.

        Raises:
            pyodbc.DatabaseError: Si falla la conexión o la consulta.
        """
        nro_doc = str(numero_despacho).rjust(8, '0')
        try:
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    row = cursor.execute(
                        f"SELECT COUNT(*) FROM SOPERACIONINV "
                        f"WHERE FTI_DOCUMENTO = '{nro_doc}' AND FTI_TIPO = 1 "
                        f"AND FTI_DEPOSITOSOURCE = {DEPOSITO_ALMACEN} "
                        f"AND FTI_DEPOSITODESTINO = {DEPOSITO_TRANSITO}"
                    ).fetchone()
                    return bool(row and row[0] > 0)
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))

    def insertar_traslado_despacho(
        self,
        numero_despacho: int,
        items: list[dict],
        responsable: str = '',
        proposito: str = '',
    ) -> None:
        """
        Al despachar: mueve productos del almacén (depósito 1) al tránsito (depósito 10).

        Args:
            numero_despacho: Número de despacho, usado como FTI_DOCUMENTO.
            items: Lista de dicts con claves 'codigo' y 'cantidad'.
            responsable: Username del usuario que confirma el despacho.
            proposito: Condición del pedido (URGENTE, SURTIDO, CLIENTE_RETIRA).
        """
        nro_doc = str(numero_despacho).rjust(8, '0')
        self._insertar_traslado(
            nro_doc, DEPOSITO_ALMACEN, DEPOSITO_TRANSITO, items,
            f'despacho={numero_despacho}', responsable=responsable, proposito=proposito,
        )

    def insertar_traslado_recepcion(
        self,
        numero_pedido: int,
        deposito_destino: int,
        items: list[dict],
        responsable: str = '',
        proposito: str = '',
    ) -> None:
        """
        Al recibir: mueve productos del tránsito (depósito 10) al depósito destino del solicitante.

        Args:
            numero_pedido: Número de pedido PostgreSQL, usado como FTI_DOCUMENTO.
            deposito_destino: Código numérico del depósito destino (solicitante).
            items: Lista de dicts con claves 'codigo' y 'cantidad'.
            responsable: Username del usuario que recibe el despacho.
            proposito: Condición del pedido (URGENTE, SURTIDO, CLIENTE_RETIRA).
        """
        nro_doc = str(numero_pedido).rjust(8, '0')
        self._insertar_traslado(
            nro_doc, DEPOSITO_TRANSITO, deposito_destino, items,
            f'pedido={numero_pedido}', responsable=responsable, proposito=proposito,
        )

    def buscar_en_categoria(self, categoria, query, tipo='codigo', solo_existencia=False):
        try:
            if tipo == 'descripcion':
                query_upper = query.upper()
                where = f"FI_CATEGORIA = '{categoria}' AND UPPER(FI_DESCRIPCION) LIKE '%{query_upper}%'"
            elif tipo == 'referencia':
                where = f"FI_CATEGORIA = '{categoria}' AND FI_REFERENCIA = '{query}'"
            elif tipo == 'ref_proveedor':
                query_upper = query.upper()
                where = f"FI_CATEGORIA = '{categoria}' AND UPPER(ZZCAMPO_001) LIKE '%{query_upper}%'"
            else:
                where = f"FI_CATEGORIA = '{categoria}' AND (FI_REFERENCIA = '{query}' OR FI_CODIGO = '{query}')"
            filtro_existencia = " AND FT_EXISTENCIA > 0" if solo_existencia else ""
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                            FI_CODIGO,
                                            FI_DESCRIPCION,
                                            FI_REFERENCIA,
                                            FI_PUESTO,
                                            FT_EXISTENCIA,
                                            ZZCAMPO_001
                                          
                                        FROM SINVENTARIO
                                        INNER JOIN SINVDEP ON FT_CODIGOPRODUCTO = FI_CODIGO
                                        WHERE {where} AND FT_CODIGODEPOSITO = 1{filtro_existencia}
                                        ORDER BY FI_DESCRIPCION""").fetchmany(100)
                    return [
                        (_clean(r[0]), _clean(r[1]), _clean(r[2]), _clean(r[3]), r[4] or 0, _clean(r[5]))
                        for r in rows
                    ]
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))
