"""
Helpers de sanitización para queries DBISAM con f-strings.

DBISAM no soporta queries parametrizadas con '?', por lo que toda entrada
que llegue a una query SQL debe pasar por estas funciones antes de ser
interpolada. Cada función valida el tipo y formato esperado, fallando rápido
con ValueError si la entrada no es conforme.

Regla: ningún valor proveniente del cliente debe entrar en un f-string SQL
sin haber pasado primero por uno de estos helpers.
"""

import re
from decimal import Decimal, InvalidOperation
from datetime import datetime

# Caracteres de control prohibidos en cadenas SQL (excepto \t que DBISAM acepta en texto)
_CONTROL_CHAR_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')


def quote_str(value: str, max_len: int = 255) -> str:
    """Escapa comillas simples y devuelve el valor listo para insertarse en SQL.

    Devuelve el valor entre comillas simples, con ' escapado como ''.
    Rechaza caracteres de control (excepto \\r y \\n) y cadenas que superen max_len.

    Ejemplo::

        WHERE FP_CODIGO = {quote_str(codigo)}
    """
    if not isinstance(value, str):
        value = str(value)
    if _CONTROL_CHAR_RE.search(value):
        raise ValueError(f"Caracteres de control no permitidos en valor SQL: {value!r}")
    if len(value) > max_len:
        raise ValueError(f"Valor excede longitud máxima {max_len}: {len(value)} chars")
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def to_int(value, field: str = 'valor') -> int:
    """Convierte value a int; lanza ValueError si no es un entero válido."""
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"Se esperaba entero en '{field}', recibido: {value!r}")
    return result


def to_decimal(value, field: str = 'valor') -> str:
    """Convierte value a Decimal y devuelve su representación string para SQL (sin comillas).

    Ejemplo::

        FDI_COSTOOPERACION = {to_decimal(costo, 'costo')}
    """
    try:
        d = Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"Se esperaba número decimal en '{field}', recibido: {value!r}")
    return str(d)


def quote_date(value: str) -> str:
    """Valida que value sea una fecha YYYY-MM-DD y la devuelve entre comillas simples.

    Lanza ValueError si el formato no es válido.

    Ejemplo::

        FTI_FECHAEMISION = {quote_date(fecha)}
    """
    try:
        datetime.strptime(str(value), '%Y-%m-%d')
    except ValueError:
        raise ValueError(f"Formato de fecha inválido (esperado YYYY-MM-DD): {value!r}")
    return f"'{value}'"


def escape_pascal_literal(text: str, max_len: int = 500) -> str:
    """Prepara un texto libre (p.ej. comentario) para insertarlo en SQL DBISAM.

    Escapa comillas simples y traduce saltos de línea al formato literal
    Pascal que DBISAM espera en cadenas concatenadas ('+#13+'/'+#10+').
    Devuelve el resultado entre comillas simples.
    """
    if not isinstance(text, str):
        text = str(text)
    if len(text) > max_len:
        raise ValueError(f"Comentario excede longitud máxima {max_len}: {len(text)} chars")
    if _CONTROL_CHAR_RE.search(text):
        raise ValueError("Caracteres de control no permitidos en comentario")
    escaped = text.replace("'", "''")
    escaped = escaped.replace("\r\n", "'+#13+#10+'")
    escaped = escaped.replace("\r", "'+#13+'")
    escaped = escaped.replace("\n", "'+#10+'")
    return f"'{escaped}'"
