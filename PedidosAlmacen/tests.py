from types import SimpleNamespace
from types import SimpleNamespace as NS
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.db import IntegrityError

from .models import DepositoPermitido
from .admin import sincronizar_depositos_permitidos
from . import views
from .dbisam import PedidosDBISAM


class DepositoPermitidoModelTest(TestCase):
    def test_creacion_y_str(self):
        dep = DepositoPermitido.objects.create(codigo=5, nombre='Tienda Centro')
        self.assertFalse(dep.activo)  # default
        self.assertEqual(str(dep), '5 - Tienda Centro')

    def test_codigo_unico(self):
        DepositoPermitido.objects.create(codigo=5, nombre='Uno')
        with self.assertRaises(IntegrityError):
            DepositoPermitido.objects.create(codigo=5, nombre='Dos')


class SincronizarDepositosTest(TestCase):
    def _row(self, codigo, nombre):
        return SimpleNamespace(FDP_CODIGO=codigo, FDP_DESCRIPCION=nombre)

    def test_upsert_preserva_activo_y_actualiza_nombre(self):
        DepositoPermitido.objects.create(codigo=5, nombre='Viejo', activo=True)

        creados, actualizados = sincronizar_depositos_permitidos([
            self._row(5, 'Nuevo Nombre'),
            self._row(7, 'Tienda Norte'),
        ])

        self.assertEqual((creados, actualizados), (1, 1))

        dep5 = DepositoPermitido.objects.get(codigo=5)
        self.assertTrue(dep5.activo)            # se preserva
        self.assertEqual(dep5.nombre, 'Nuevo Nombre')  # se actualiza

        dep7 = DepositoPermitido.objects.get(codigo=7)
        self.assertFalse(dep7.activo)           # nuevo nace inactivo


class DepositosParaSelectorTest(TestCase):
    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_usa_activos_y_no_consulta_dbisam(self, mock_db):
        DepositoPermitido.objects.create(codigo=3, nombre='Beta', activo=True)
        DepositoPermitido.objects.create(codigo=2, nombre='Alfa', activo=True)
        DepositoPermitido.objects.create(codigo=9, nombre='Inactivo', activo=False)

        resultado = views._depositos_para_selector()

        self.assertEqual(resultado, [(2, 'Alfa'), (3, 'Beta')])  # ordenado por nombre
        mock_db.assert_not_called()

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_fallback_sin_activos(self, mock_db):
        mock_db.return_value.obtener_depositos.return_value = [
            NS(FDP_CODIGO=4, FDP_DESCRIPCION='Tienda Sur'),
        ]
        resultado = views._depositos_para_selector()
        self.assertEqual(resultado, [(4, 'Tienda Sur')])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_fallback_con_error_dbisam_devuelve_vacio(self, mock_db):
        mock_db.return_value.obtener_depositos.side_effect = Exception('odbc down')
        self.assertEqual(views._depositos_para_selector(), [])


class BuscarEnCategoriaFiltroTest(TestCase):
    def _capturar_sql(self, **kwargs):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = (mock_connect.return_value.__enter__.return_value
                      .cursor.return_value.__enter__.return_value)
            cursor.execute.return_value.fetchmany.return_value = []
            db.buscar_en_categoria('CAT', 'abc', 'descripcion', **kwargs)
            return cursor.execute.call_args[0][0]

    def test_con_solo_existencia_agrega_filtro(self):
        sql = self._capturar_sql(solo_existencia=True)
        self.assertIn('FT_EXISTENCIA > 0', sql)

    def test_sin_solo_existencia_no_agrega_filtro(self):
        sql = self._capturar_sql(solo_existencia=False)
        self.assertNotIn('FT_EXISTENCIA > 0', sql)


class BuscarProductoVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        self.user = User.objects.create_superuser(username='admin', password='x')
        self.client.force_login(self.user)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_vista_pasa_flag_true(self, mock_db):
        mock_db.return_value.buscar_en_categoria.return_value = []
        self.client.get('/pedidos/buscar-producto/',
                        {'q': 'abc', 'categoria': 'CAT', 'solo_existencia': '1'})
        _, kwargs = mock_db.return_value.buscar_en_categoria.call_args
        self.assertTrue(kwargs.get('solo_existencia'))

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_vista_pasa_flag_false_si_ausente(self, mock_db):
        mock_db.return_value.buscar_en_categoria.return_value = []
        self.client.get('/pedidos/buscar-producto/',
                        {'q': 'abc', 'categoria': 'CAT'})
        _, kwargs = mock_db.return_value.buscar_en_categoria.call_args
        self.assertFalse(kwargs.get('solo_existencia'))


class BotonAgregarBloqueoTest(TestCase):
    def setUp(self):
        from users.models import User
        self.user = User.objects.create_superuser(username='admin2', password='x')
        self.client.force_login(self.user)

    def _buscar(self, existencia):
        # (FI_CODIGO, FI_DESCRIPCION, FI_REFERENCIA, FI_PUESTO, existencia, ZZCAMPO_001)
        fila = ('P1', 'Producto Uno', 'REF1', 'A1', existencia, 'RP1')
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.buscar_en_categoria.return_value = [fila]
            resp = self.client.get('/pedidos/buscar-producto/',
                                   {'q': 'pro', 'categoria': 'CAT'})
        return resp.content.decode()

    def test_existencia_cero_boton_deshabilitado(self):
        html = self._buscar(0)
        self.assertIn('disabled', html)
        self.assertIn('Sin stock', html)
        self.assertNotIn("agregarItem('P1'", html)

    def test_con_existencia_boton_habilitado(self):
        html = self._buscar(7)
        self.assertIn("agregarItem('P1'", html)
        self.assertNotIn('Sin stock', html)


class SincronizarViewTest(TestCase):
    """La sincronización se ejecuta desde una vista propia (botón), no desde
    una acción de changelist, para que funcione con la tabla vacía."""

    def setUp(self):
        from users.models import User
        from django.urls import reverse
        self.user = User.objects.create_superuser(username='admin3', password='x')
        self.client.force_login(self.user)
        self.url = reverse('admin:pedidosalmacen_depositopermitido_sincronizar')

    @patch('PedidosAlmacen.admin.PedidosDBISAM')
    def test_sincroniza_con_tabla_vacia(self, mock_db):
        mock_db.return_value.obtener_depositos.return_value = [
            NS(FDP_CODIGO=4, FDP_DESCRIPCION='Tienda Sur'),
            NS(FDP_CODIGO=7, FDP_DESCRIPCION='Tienda Norte'),
        ]
        # Tabla vacía: el botón debe poder ejecutarse igualmente.
        self.assertEqual(DepositoPermitido.objects.count(), 0)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)  # redirect al listado
        self.assertEqual(DepositoPermitido.objects.count(), 2)

    @patch('PedidosAlmacen.admin.PedidosDBISAM')
    def test_error_dbisam_no_rompe(self, mock_db):
        mock_db.return_value.obtener_depositos.side_effect = Exception('odbc down')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(DepositoPermitido.objects.count(), 0)


class GenerarPedidoPDFVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem
        u = User.objects.create_superuser(username='pdfu', password='x')
        self.pedido = Pedido.objects.create(solicitante=u)
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='A', descripcion='Articulo A',
            cantidad_solicitada=5, estado='PARCIAL',
            cantidad_despachada=2, cantidad_back_order=3, cantidad_recibida=0,
        )

    def test_genera_pdf_para_cada_vista(self):
        from .pdf import generar_pedido_pdf
        for vista in ['todos', 'despachado', 'back_order', 'recibido', 'parcial']:
            pdf = generar_pedido_pdf(self.pedido, self.pedido.items.all(), vista=vista)
            self.assertTrue(pdf.startswith(b'%PDF'), f'vista={vista} no produjo PDF')

    def test_vista_default_es_todos(self):
        from .pdf import generar_pedido_pdf
        pdf = generar_pedido_pdf(self.pedido, self.pedido.items.all())
        self.assertTrue(pdf.startswith(b'%PDF'))


class ExportarPedidoVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.almacen = User.objects.create_superuser(username='alm', password='x')
        self.tienda = User.objects.create_user(username='tnd', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda)
        for codigo, estado in [('A', 'DESPACHADO'), ('B', 'BACK_ORDER'),
                               ('C', 'RECIBIDO'), ('D', 'PARCIAL')]:
            PedidoItem.objects.create(
                pedido=self.pedido, codigo=codigo, descripcion=codigo.lower(),
                cantidad_solicitada=1, estado=estado,
            )

    def _url(self, vista=None):
        u = self.reverse('pedidos-pdf', args=[self.pedido.numero_pedido])
        return f'{u}?vista={vista}' if vista else u

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_filtra_por_estado_exacto(self, mock_pdf):
        self.client.force_login(self.almacen)
        resp = self.client.get(self._url('despachado'))
        self.assertEqual(resp.status_code, 200)
        args, kwargs = mock_pdf.call_args
        self.assertEqual([i.estado for i in args[1]], ['DESPACHADO'])
        self.assertEqual(kwargs.get('vista'), 'despachado')

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_vista_invalida_cae_a_todos(self, mock_pdf):
        self.client.force_login(self.almacen)
        resp = self.client.get(self._url('inexistente'))
        self.assertEqual(resp.status_code, 200)
        args, kwargs = mock_pdf.call_args
        self.assertEqual(len(list(args[1])), 4)
        self.assertEqual(kwargs.get('vista'), 'todos')

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_tienda_no_puede_despachado(self, mock_pdf):
        self.client.force_login(self.tienda)
        resp = self.client.get(self._url('despachado'))
        self.assertEqual(resp.status_code, 302)
        mock_pdf.assert_not_called()

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_tienda_puede_recibido(self, mock_pdf):
        self.client.force_login(self.tienda)
        resp = self.client.get(self._url('recibido'))
        self.assertEqual(resp.status_code, 200)
        args, kwargs = mock_pdf.call_args
        self.assertEqual([i.estado for i in args[1]], ['RECIBIDO'])

    @patch('PedidosAlmacen.views.generar_pedido_pdf', return_value=b'%PDF-x')
    def test_variante_vacia_responde_200(self, mock_pdf):
        from .models import Pedido, PedidoItem
        pedido2 = Pedido.objects.create(solicitante=self.almacen)
        PedidoItem.objects.create(pedido=pedido2, codigo='Z', descripcion='z',
                                  cantidad_solicitada=1, estado='DESPACHADO')
        self.client.force_login(self.almacen)
        url = self.reverse('pedidos-pdf', args=[pedido2.numero_pedido]) + '?vista=back_order'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        args, _ = mock_pdf.call_args
        self.assertEqual(len(list(args[1])), 0)


class DetallePedidoVistasPdfTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.almacen = User.objects.create_superuser(username='alm2', password='x')
        self.tienda = User.objects.create_user(username='tnd2', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda)
        for codigo, estado in [('A', 'DESPACHADO'), ('B', 'BACK_ORDER'),
                               ('C', 'RECIBIDO'), ('D', 'PARCIAL')]:
            PedidoItem.objects.create(
                pedido=self.pedido, codigo=codigo, descripcion=codigo.lower(),
                cantidad_solicitada=1, estado=estado,
            )

    def test_almacen_ve_todas_las_variantes_con_conteo(self):
        self.client.force_login(self.almacen)
        resp = self.client.get(self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido]))
        por_clave = {v['clave']: v['count'] for v in resp.context['vistas_pdf']}
        self.assertEqual(por_clave['todos'], 4)
        self.assertEqual(por_clave['despachado'], 1)
        self.assertEqual(por_clave['parcial'], 1)

    def test_tienda_no_ve_despachado_ni_parcial(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido]))
        claves = [v['clave'] for v in resp.context['vistas_pdf']]
        self.assertNotIn('despachado', claves)
        self.assertNotIn('parcial', claves)
        self.assertIn('recibido', claves)
        self.assertIn('back_order', claves)
        self.assertIn('todos', claves)


class DetallePedidoModalTest(TestCase):
    def test_detalle_incluye_modal_y_variantes(self):
        from users.models import User
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        almacen = User.objects.create_superuser(username='alm3', password='x')
        pedido = Pedido.objects.create(solicitante=almacen)
        PedidoItem.objects.create(pedido=pedido, codigo='A', descripcion='a',
                                  cantidad_solicitada=1, estado='DESPACHADO')
        self.client.force_login(almacen)
        resp = self.client.get(reverse('pedidos-detalle', args=[pedido.numero_pedido]))
        self.assertContains(resp, 'modalImprimirPedido')
        self.assertContains(resp, 'vista=despachado')


class AnulacionModeloTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, Despacho
        self.user = User.objects.create_superuser(username='sup_model', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.user)
        self.despacho = Despacho.objects.create(pedido=self.pedido)

    def test_pedido_acepta_estado_anulado_y_campos(self):
        from django.utils import timezone
        self.pedido.estado_anterior = self.pedido.estado
        self.pedido.estado = 'ANULADO'
        self.pedido.motivo_anulacion = 'Pedido duplicado'
        self.pedido.anulado_por = self.user
        self.pedido.fecha_anulacion = timezone.now()
        self.pedido.save()
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'ANULADO')
        self.assertEqual(self.pedido.motivo_anulacion, 'Pedido duplicado')
        self.assertEqual(self.pedido.anulado_por, self.user)
        self.assertIsNotNone(self.pedido.fecha_anulacion)
        self.assertEqual(self.pedido.estado_anterior, 'PENDIENTE')

    def test_despacho_acepta_estado_anulado_y_campos(self):
        self.despacho.estado_anterior = self.despacho.estado
        self.despacho.estado = 'ANULADO'
        self.despacho.motivo_anulacion = 'Error de carga'
        self.despacho.anulado_por = self.user
        self.despacho.save()
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ANULADO')
        self.assertEqual(self.despacho.estado_anterior, 'PREPARANDO')
        self.assertEqual(self.despacho.anulado_por, self.user)

    def test_anulado_en_choices(self):
        from .models import Pedido, Despacho
        self.assertIn('ANULADO', dict(Pedido.ESTADO_CHOICES))
        self.assertIn('ANULADO', dict(Despacho.ESTADO_CHOICES))


class AnularPedidoVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_p', password='x')
        self.tienda = User.objects.create_user(username='tnd_p', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PICKING')
        self.pedido.picker = self.sup
        self.pedido.save()

    def _url(self):
        return self.reverse('pedidos-anular', args=[self.pedido.numero_pedido])

    def test_supervisor_anula_con_motivo_y_libera_picker(self):
        self.client.force_login(self.sup)
        resp = self.client.post(self._url(), {'motivo': 'Duplicado'})
        self.assertEqual(resp.status_code, 302)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'ANULADO')
        self.assertEqual(self.pedido.estado_anterior, 'PICKING')
        self.assertEqual(self.pedido.motivo_anulacion, 'Duplicado')
        self.assertEqual(self.pedido.anulado_por, self.sup)
        self.assertIsNotNone(self.pedido.fecha_anulacion)
        self.assertIsNone(self.pedido.picker)

    def test_sin_motivo_no_anula(self):
        self.client.force_login(self.sup)
        self.client.post(self._url(), {'motivo': '   '})
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'PICKING')

    def test_tienda_no_puede_anular(self):
        self.client.force_login(self.tienda)
        resp = self.client.post(self._url(), {'motivo': 'x'})
        self.assertEqual(resp.status_code, 302)  # redirect a dashboard
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'PICKING')

    def test_ya_anulado_no_se_reanula(self):
        from django.utils import timezone
        self.pedido.estado = 'ANULADO'
        self.pedido.motivo_anulacion = 'Primera'
        self.pedido.fecha_anulacion = timezone.now()
        self.pedido.save()
        self.client.force_login(self.sup)
        self.client.post(self._url(), {'motivo': 'Segunda'})
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.motivo_anulacion, 'Primera')

    def test_get_no_anula(self):
        self.client.force_login(self.sup)
        self.client.get(self._url())
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'PICKING')
