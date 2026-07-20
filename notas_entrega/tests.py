from decimal import Decimal
from django.test import SimpleTestCase as TestCase
from .sanitize import quote_str, to_int, to_decimal, quote_date, escape_pascal_literal
from .serializers import NotaEntregaSerializer

PAYLOAD_CANONICO = {
    'ordenes': [
        {
            'codigo': '01010006', 'orden': '00009929', 'cantidad': 12,
            'diferencia': 0, 'recibido': 12, 'costo': 9.87, 'iva': 0,
            'moneda': '1', 'deposito': 1, 'descripcion': 'CARPETA FIBRA',
            'autoincrement': 269, 'puesto': 'ALMACEN', 'referencia': '10005',
            'ref_proveedor': '02614E', 'iva_16_monto': 0,
        },
    ],
    'productoSinOc': [],
    'proveedor': 'A2CONSULTORES ARAGUA, C.A.',
    'rif': 'J407903691',
    'comentario': '',
    'direccion_proveedor': 'CALLE MARIÑO SUR',
}


class SanitizeQuoteStrTest(TestCase):
    def test_escapa_apostrofes(self):
        result = quote_str("O'Brien", max_len=50)
        self.assertEqual(result, "'O''Brien'")

    def test_cadena_normal(self):
        result = quote_str('J407903691', max_len=20)
        self.assertEqual(result, "'J407903691'")

    def test_rechaza_control_chars(self):
        with self.assertRaises(ValueError):
            quote_str("texto\x00null", max_len=50)

    def test_rechaza_longitud_excedida(self):
        with self.assertRaises(ValueError):
            quote_str('A' * 256, max_len=255)

    def test_permite_crlf(self):
        result = quote_str("linea1\r\nlinea2", max_len=50)
        self.assertIn("linea1", result)


class SanitizeToIntTest(TestCase):
    def test_convierte_string_numerico(self):
        self.assertEqual(to_int('16', 'iva'), 16)

    def test_convierte_int(self):
        self.assertEqual(to_int(1, 'moneda'), 1)

    def test_rechaza_alfanumerico(self):
        with self.assertRaises(ValueError):
            to_int('abc', 'campo')

    def test_rechaza_float_string(self):
        with self.assertRaises(ValueError):
            to_int('1.5', 'campo')


class SanitizeToDecimalTest(TestCase):
    def test_convierte_float(self):
        result = to_decimal(9.87, 'costo')
        Decimal(result)  # debe parsear sin error

    def test_convierte_decimal(self):
        result = to_decimal(Decimal('9.87'), 'costo')
        self.assertEqual(result, '9.87')

    def test_rechaza_no_numerico(self):
        with self.assertRaises(ValueError):
            to_decimal('NaN_valor', 'costo')


class SanitizeQuoteDateTest(TestCase):
    def test_fecha_valida(self):
        result = quote_date('2026-05-22')
        self.assertEqual(result, "'2026-05-22'")

    def test_rechaza_formato_invalido(self):
        with self.assertRaises(ValueError):
            quote_date('22/05/2026')

    def test_rechaza_fecha_incompleta(self):
        with self.assertRaises(ValueError):
            quote_date('2026-05')


class SerializerNotaEntregaTest(TestCase):
    def test_acepta_payload_canonico(self):
        serializer = NotaEntregaSerializer(data=PAYLOAD_CANONICO)
        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_rechaza_rif_invalido(self):
        data = {**PAYLOAD_CANONICO, 'rif': '12345678'}
        serializer = NotaEntregaSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn('rif', serializer.errors)

    def test_rechaza_payload_sin_items(self):
        data = {**PAYLOAD_CANONICO, 'ordenes': [], 'productoSinOc': []}
        serializer = NotaEntregaSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_rechaza_iva_invalido(self):
        orden_invalida = {**PAYLOAD_CANONICO['ordenes'][0], 'iva': 21}
        data = {**PAYLOAD_CANONICO, 'ordenes': [orden_invalida]}
        serializer = NotaEntregaSerializer(data=data)
        self.assertFalse(serializer.is_valid())
