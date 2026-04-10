import pyodbc
import logging
from datetime import datetime
from django.conf import settings

logger = logging.getLogger(__name__)

DEPOSITO_ORIGEN = 1  # Depósito principal / almacén (siempre origen en traslados)


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

    def consultar_stock_multiple(self, codigos):
        try:
            if not codigos:
                return {}
            codes_str = ','.join(f"'{c}'" for c in codigos)
            with self.connect() as conn:
                with conn.cursor() as cursor:
                    rows = cursor.execute(f"""SELECT
                                            FT_CODIGOPRODUCTO,
                                            COALESCE(SUM(FT_EXISTENCIA), 0) AS existencia
                                        FROM SINVDEP
                                        WHERE FT_CODIGOPRODUCTO IN ({codes_str})
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

    def insertar_traslado(self, numero_pedido: int, deposito_destino: int, items: list[dict]) -> None:
        """
        Inserta un traslado en DBISAM al confirmar la recepción de un pedido.

        Genera una operación tipo 1 (Traslado) en SOPERACIONINV y una línea
        por producto en SDETALLEINV. Ajusta existencias en SINVDEP restando
        del depósito origen (almacén=1) y sumando en el depósito destino.
        Si el registro del producto no existe en SINVDEP para el depósito destino,
        se inserta con la cantidad como existencia inicial.

        Args:
            numero_pedido: Número de pedido PostgreSQL, usado como FTI_DOCUMENTO.
            deposito_destino: Código numérico del depósito destino (solicitante).
            items: Lista de dicts con claves 'codigo' y 'cantidad'.

        Raises:
            pyodbc.DatabaseError: Si ocurre algún error durante la inserción.
        """
        nro_documento = str(numero_pedido).rjust(8, '0')
        fecha = datetime.now().strftime('%Y-%m-%d')
        hora = datetime.now().strftime('%I:%M:%S %p')
        total_items = len(items)

        try:
            with self.connect() as conn:
                codigos = [item['codigo'] for item in items]
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
                            FDI_VISIBLE
                        ) VALUES (
                            '{nro_documento}',
                            LASTAUTOINC('SOPERACIONINV'),
                            '{codigo}',
                            {cantidad},
                            {DEPOSITO_ORIGEN},
                            {deposito_destino},
                            1,
                            {linea},
                            4,
                            1
                        );
                    """)

                    update_sinvdep.append(
                        f"UPDATE SINVDEP SET FT_EXISTENCIA = COALESCE(FT_EXISTENCIA, 0) - {cantidad} "
                        f"WHERE FT_CODIGOPRODUCTO = '{codigo}' AND FT_CODIGODEPOSITO = {DEPOSITO_ORIGEN};"
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
                        FTI_FECHALIBRO
                    ) VALUES (
                        '{nro_documento}',
                        1,
                        4,
                        1,
                        '{fecha}',
                        {DEPOSITO_ORIGEN},
                        {deposito_destino},
                        {total_items},
                        {total_items},
                        1,
                        1,
                        '{hora}',
                        '{fecha}'
                    );
                    {''.join(detalle_queries)}
                    {''.join(update_sinvdep)}
                """

                with conn.cursor() as cursor:
                    cursor.execute(query)
                    cursor.execute('COMMIT;')

            logger.info(
                f'Traslado DBISAM insertado: pedido={numero_pedido} destino={deposito_destino} items={total_items}'
            )
        except Exception as e:
            logger.error(f'Error insertando traslado DBISAM pedido={numero_pedido}: {e}')
            raise pyodbc.DatabaseError(str(e))

    def buscar_en_categoria(self, categoria, query, tipo='codigo'):
        try:
            if tipo == 'descripcion':
                query_upper = query.upper()
                where = f"FI_CATEGORIA = '{categoria}' AND UPPER(FI_DESCRIPCION) LIKE '%{query_upper}%'"
            else:
                where = f"FI_CATEGORIA = '{categoria}' AND (FI_REFERENCIA = '{query}' OR FI_CODIGO = '{query}')"
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
                                        WHERE {where} AND FT_CODIGODEPOSITO = 1
                                        ORDER BY FI_DESCRIPCION""").fetchmany(100)
                    return [
                        (_clean(r[0]), _clean(r[1]), _clean(r[2]), _clean(r[3]), r[4] or 0, _clean(r[5]))
                        for r in rows
                    ]
        except Exception as e:
            raise pyodbc.DatabaseError(str(e))
