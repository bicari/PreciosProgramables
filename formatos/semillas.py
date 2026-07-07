"""Definiciones ReportBro semilla por tipo de documento.

Construidas en Python (compacto y testeable) en lugar de JSON estático; el
resultado sembrado en PlantillaImpresion.definicion es el mismo JSON que
produciría el diseñador. El superusuario parte de un layout básico con todos
los parámetros del contrato ya declarados (ver formatos/contratos.py).
"""


def _param(id_, nombre, tipo='string', children=None):
    p = {
        'id': id_, 'name': nombre, 'type': tipo, 'arrayItemType': 'string',
        'eval': False, 'nullable': True, 'pattern': '', 'expression': '',
        'showOnlyNameType': False, 'testData': '',
    }
    if children is not None:
        p['children'] = children
        p['nullable'] = False
    return p


def _texto(id_, contenido, x, y, ancho, alto, *, container='0_content',
           size=10, bold=False, align='left'):
    return {
        'elementType': 'text', 'id': id_, 'containerId': container,
        'x': x, 'y': y, 'width': ancho, 'height': alto,
        'content': contenido, 'richText': False, 'richTextContent': None,
        'richTextHtml': '', 'eval': False, 'styleId': '',
        'bold': bold, 'italic': False, 'underline': False, 'strikethrough': False,
        'horizontalAlignment': align, 'verticalAlignment': 'middle',
        'textColor': '#000000', 'backgroundColor': '', 'font': 'helvetica',
        'fontSize': size, 'lineSpacing': 1, 'borderColor': '#000000',
        'borderWidth': 1, 'borderAll': False, 'borderLeft': False,
        'borderTop': False, 'borderRight': False, 'borderBottom': False,
        'paddingLeft': 2, 'paddingTop': 2, 'paddingRight': 2, 'paddingBottom': 2,
        'printIf': '', 'removeEmptyElement': False, 'alwaysPrintOnSamePage': True,
        'pattern': '', 'link': '', 'cs_condition': '',
    }


def _celda(id_, contenido, ancho, *, bold=False, align='left', size=8, print_if=''):
    return {
        'elementType': 'table_text', 'id': id_, 'width': ancho,
        'content': contenido, 'eval': False, 'colspan': '', 'styleId': '',
        'bold': bold, 'italic': False, 'underline': False, 'strikethrough': False,
        'horizontalAlignment': align, 'verticalAlignment': 'middle',
        'textColor': '#000000', 'backgroundColor': '', 'font': 'helvetica',
        'fontSize': size, 'lineSpacing': 1,
        'paddingLeft': 2, 'paddingTop': 2, 'paddingRight': 2, 'paddingBottom': 2,
        'pattern': '', 'link': '', 'cs_condition': '', 'printIf': print_if,
        'growWeight': 0, 'borderWidth': 1,
    }


def _tabla(id_, y, columnas):
    """columnas: lista de (titulo, expresion, ancho, align[, print_if]).

    Si la tupla trae un quinto elemento, se usa como condición printIf de la
    celda de encabezado: reportbro-lib omite la columna completa cuando la
    condición evalúa a False.
    """
    ancho_total = sum(c[2] for c in columnas)
    header = [
        _celda(id_ + 10 + i, col[0], col[2], bold=True, align='center',
               print_if=col[4] if len(col) > 4 else '')
        for i, col in enumerate(columnas)
    ]
    contenido = [
        _celda(id_ + 40 + i, col[1], col[2], align=col[3])
        for i, col in enumerate(columnas)
    ]
    return {
        'elementType': 'table', 'id': id_, 'containerId': '0_content',
        'x': 0, 'y': y, 'width': ancho_total, 'dataSource': '${items}',
        'columns': len(columnas), 'header': True, 'contentRows': '1',
        'footer': False, 'border': 'grid', 'borderColor': '#000000',
        'borderWidth': 0.5, 'printIf': '', 'removeEmptyElement': False,
        'spreadsheet_hide': False, 'spreadsheet_column': '',
        'spreadsheet_addEmptyRow': False,
        'headerData': {'id': id_ + 1, 'height': 20, 'backgroundColor': '#eeeeee',
                       'repeatHeader': True, 'columnData': header},
        'contentDataRows': [{'id': id_ + 2, 'height': 18, 'backgroundColor': '',
                             'alternateBackgroundColor': '', 'groupExpression': '',
                             'printIf': '', 'alwaysPrintOnSamePage': False,
                             'pageBreak': False, 'repeatGroupHeader': False,
                             'columnData': contenido}],
        'footerData': {'id': id_ + 3, 'height': 0, 'backgroundColor': '',
                       'repeatHeader': False, 'columnData': []},
    }


_DOC_PROPS = {
    'pageFormat': 'letter', 'pageWidth': '', 'pageHeight': '', 'unit': 'mm',
    'orientation': 'portrait', 'contentHeight': '',
    'marginLeft': '10', 'marginTop': '10', 'marginRight': '10', 'marginBottom': '10',
    'header': True, 'headerSize': '60', 'headerDisplay': 'always',
    'footer': True, 'footerSize': '25', 'footerDisplay': 'always',
    'patternLocale': 'es', 'patternCurrencySymbol': 'Bs',
    'patternNumberGroupSymbol': '.',
}

_PARAMS_COMUNES = [
    _param(1, 'page_count', 'number'),
    _param(2, 'page_number', 'number'),
]

_CHILDREN_ITEM_BASE = [
    ('codigo', 'string'), ('descripcion', 'string'), ('referencia', 'string'),
    ('puesto', 'string'), ('ref_proveedor', 'string'),
    ('cantidad_solicitada', 'number'), ('cantidad_despachada', 'number'),
    ('cantidad_recibida', 'number'), ('observacion', 'string'),
]


def _children(base_id, campos):
    return [_param(base_id + i, nombre, tipo) for i, (nombre, tipo) in enumerate(campos)]


def _pie():
    return _texto(90, 'Página ${page_number} de ${page_count}', 0, 0, 575, 20,
                  container='0_footer', size=8, align='center')


SEMILLA_DESPACHO = {
    'docElements': [
        _texto(101, 'Despacho #${numero_despacho}', 0, 5, 575, 25,
               container='0_header', size=18, bold=True),
        _texto(102, 'Pedido #${numero_pedido} — ${deposito} — ${estado}',
               0, 32, 575, 18, container='0_header', size=10),
        _texto(103, 'Fecha despacho: ${fecha_despacho}    '
                    'Despachador: ${despachador}    Picker: ${picker}',
               0, 5, 575, 16),
        _texto(104, 'Solicitante: ${solicitante}    Condición: ${condicion}',
               0, 23, 575, 16),
        _tabla(200, 45, [
            ('Código', '${codigo}', 60, 'left'),
            ('Descripción', '${descripcion}', 175, 'left'),
            ('Referencia', '${referencia}', 70, 'left'),
            ('Puesto', '${puesto}', 60, 'left'),
            ('Solicitado', '${cantidad_solicitada}', 50, 'right'),
            ('Despachado', '${cantidad_despachada}', 55, 'right'),
            ('Observación', '${observacion}', 105, 'left'),
        ]),
        _texto(105, 'Items: ${total_items}    Total despachado: ${total_despachado}',
               0, 70, 575, 16, bold=True, align='right'),
        _pie(),
    ],
    'parameters': _PARAMS_COMUNES + [
        _param(10, 'numero_despacho', 'number'),
        _param(11, 'numero_pedido', 'number'),
        _param(12, 'estado'), _param(13, 'condicion'), _param(14, 'deposito'),
        _param(15, 'solicitante'), _param(16, 'despachador'),
        _param(17, 'picker'), _param(18, 'receptor'),
        _param(19, 'fecha_despacho'), _param(20, 'fecha_recepcion'),
        _param(21, 'observaciones'),
        _param(22, 'items', 'array', children=_children(30, _CHILDREN_ITEM_BASE)),
        _param(23, 'total_items', 'number'),
        _param(24, 'total_despachado', 'number'),
    ],
    'styles': [],
    'version': 4,
    'documentProperties': dict(_DOC_PROPS),
}

_CHILDREN_ITEM_PEDIDO = _CHILDREN_ITEM_BASE + [
    ('cantidad_back_order', 'number'), ('estado', 'string'),
]

SEMILLA_PEDIDO = {
    'docElements': [
        _texto(101, 'Pedido #${numero_pedido}', 0, 5, 575, 25,
               container='0_header', size=18, bold=True),
        _texto(102, '${deposito} — ${estado} — ${condicion}',
               0, 32, 575, 18, container='0_header', size=10),
        _texto(103, 'Creado: ${fecha_creacion}    Solicitante: ${solicitante}    '
                    'Categoría: ${categoria}',
               0, 5, 575, 16),
        _tabla(200, 27, [
            ('Código', '${codigo}', 60, 'left'),
            ('Descripción', '${descripcion}', 120, 'left'),
            ('Referencia', '${referencia}', 55, 'left'),
            ('Puesto', '${puesto}', 55, 'left'),
            ('Ref. Prov.', '${ref_proveedor}', 50, 'left'),
            ('Solicitado', '${cantidad_solicitada}', 55, 'right'),
            # Columnas sensibles: ocultas para usuarios sin privilegio
            ('Despachado', '${cantidad_despachada}', 55, 'right', '${mostrar_cantidades}'),
            ('Recibido', '${cantidad_recibida}', 45, 'right', '${mostrar_cantidades}'),
            ('Observación', '${observacion}', 80, 'left'),
        ]),
        _texto(105, 'Items: ${total_items}    Total solicitado: ${total_solicitado}',
               0, 52, 575, 16, bold=True, align='right'),
        _pie(),
    ],
    'parameters': _PARAMS_COMUNES + [
        _param(10, 'numero_pedido', 'number'),
        _param(11, 'estado'), _param(12, 'condicion'), _param(13, 'deposito'),
        _param(14, 'categoria'), _param(15, 'solicitante'),
        _param(16, 'despachador'), _param(17, 'picker'),
        _param(18, 'fecha_creacion'), _param(19, 'fecha_despacho'),
        _param(20, 'fecha_recepcion'), _param(21, 'observaciones'),
        _param(22, 'items', 'array', children=_children(30, _CHILDREN_ITEM_PEDIDO)),
        _param(23, 'total_items', 'number'),
        _param(24, 'total_solicitado', 'number'),
        _param(25, 'mostrar_cantidades', 'boolean'),
    ],
    'styles': [],
    'version': 4,
    'documentProperties': dict(_DOC_PROPS),
}

SEMILLAS = {'despacho': SEMILLA_DESPACHO, 'pedido': SEMILLA_PEDIDO}
