import json
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


class AnularDespachoVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, Despacho
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_d', password='x')
        self.tienda = User.objects.create_user(username='tnd_d', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='DESPACHADO')
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')

    def _url(self):
        return self.reverse('despachos-anular', args=[self.despacho.numero_despacho])

    def test_supervisor_anula_despacho(self):
        self.client.force_login(self.sup)
        resp = self.client.post(self._url(), {'motivo': 'Carga erronea'})
        self.assertEqual(resp.status_code, 302)
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ANULADO')
        self.assertEqual(self.despacho.estado_anterior, 'ENVIADO')
        self.assertEqual(self.despacho.anulado_por, self.sup)
        self.assertIsNotNone(self.despacho.fecha_anulacion)
        # Independencia: el pedido NO se toca
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'DESPACHADO')

    def test_sin_motivo_no_anula(self):
        self.client.force_login(self.sup)
        self.client.post(self._url(), {'motivo': ''})
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ENVIADO')

    def test_tienda_no_puede_anular(self):
        self.client.force_login(self.tienda)
        self.client.post(self._url(), {'motivo': 'x'})
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ENVIADO')

    def test_ya_anulado_no_se_reanula(self):
        from django.utils import timezone
        self.despacho.estado = 'ANULADO'
        self.despacho.motivo_anulacion = 'Primera'
        self.despacho.fecha_anulacion = timezone.now()
        self.despacho.save()
        self.client.force_login(self.sup)
        self.client.post(self._url(), {'motivo': 'Segunda'})
        self.despacho.refresh_from_db()
        self.assertEqual(self.despacho.motivo_anulacion, 'Primera')


class AnularDespachoReversionTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_rev', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='DESPACHADO')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='A', descripcion='a',
            cantidad_solicitada=10, cantidad_despachada=10,
            cantidad_back_order=0, estado='DESPACHADO',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')
        DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item, cantidad_despachada=10,
        )

    def _anular(self):
        self.client.force_login(self.sup)
        return self.client.post(
            self.reverse('despachos-anular', args=[self.despacho.numero_despacho]),
            {'motivo': 'error'},
        )

    def test_revierte_despachada_total_item_pendiente(self):
        self._anular()
        self.item.refresh_from_db()
        self.pedido.refresh_from_db()
        self.despacho.refresh_from_db()
        self.assertEqual(self.item.cantidad_despachada, 0)
        self.assertEqual(self.item.cantidad_back_order, 10)
        self.assertEqual(self.item.estado, 'PENDIENTE')
        self.assertEqual(self.pedido.estado, 'PENDIENTE')
        self.assertIsNone(self.pedido.fecha_despacho)
        self.assertEqual(self.despacho.estado, 'ANULADO')

    def test_revierte_despachada_parcial(self):
        self.item.cantidad_despachada = 4
        self.item.cantidad_back_order = 6
        self.item.estado = 'PARCIAL'
        self.item.save()
        self.pedido.estado = 'PARCIAL'
        self.pedido.save()
        di = self.despacho.items.first()
        di.cantidad_despachada = 4
        di.save()
        self._anular()
        self.item.refresh_from_db()
        self.pedido.refresh_from_db()
        self.assertEqual(self.item.cantidad_despachada, 0)
        self.assertEqual(self.item.cantidad_back_order, 10)
        self.assertEqual(self.item.estado, 'PENDIENTE')
        self.assertEqual(self.pedido.estado, 'PENDIENTE')

    def test_no_anula_despacho_recibido(self):
        self.despacho.estado = 'RECIBIDO'
        self.despacho.save()
        self._anular()
        self.despacho.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'RECIBIDO')
        self.assertEqual(self.item.cantidad_despachada, 10)


class ReporteExcluyeAnuladosTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_r', password='x')
        # Pedido válido
        self.ok = Pedido.objects.create(solicitante=self.sup, estado='RECIBIDO')
        PedidoItem.objects.create(pedido=self.ok, codigo='A', descripcion='a',
                                  cantidad_solicitada=5, cantidad_despachada=5,
                                  cantidad_recibida=5, estado='RECIBIDO')
        # Pedido anulado (no debe contar en KPIs)
        self.anu = Pedido.objects.create(solicitante=self.sup, estado='ANULADO',
                                         motivo_anulacion='x')
        PedidoItem.objects.create(pedido=self.anu, codigo='B', descripcion='b',
                                  cantidad_solicitada=100, cantidad_despachada=100,
                                  cantidad_recibida=100, estado='RECIBIDO')

    def test_kpis_excluyen_anulados(self):
        self.client.force_login(self.sup)
        resp = self.client.get(self.reverse('pedidos-reporte'))
        self.assertEqual(resp.context['total_pedidos'], 1)
        self.assertEqual(resp.context['total_solicitado'], 5)
        estados = [fila['estado'] for fila in resp.context['por_estado']]
        self.assertNotIn('ANULADO', estados)

    def test_contador_anulados_presente(self):
        self.client.force_login(self.sup)
        resp = self.client.get(self.reverse('pedidos-reporte'))
        self.assertEqual(resp.context['total_anulados'], 1)


class AnularDetalleTemplateTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_t', password='x')
        self.tienda = User.objects.create_user(username='tnd_t', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PENDIENTE')

    def _detalle(self):
        return self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido])

    def test_supervisor_ve_boton_anular(self):
        self.client.force_login(self.sup)
        resp = self.client.get(self._detalle())
        self.assertContains(resp, 'modalAnularPedido')
        self.assertContains(resp, self.reverse('pedidos-anular', args=[self.pedido.numero_pedido]))

    def test_tienda_no_ve_boton_anular(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self._detalle())
        self.assertNotContains(resp, 'modalAnularPedido')

    def test_pedido_anulado_muestra_motivo(self):
        from django.utils import timezone
        self.pedido.estado = 'ANULADO'
        self.pedido.estado_anterior = 'PENDIENTE'
        self.pedido.motivo_anulacion = 'Motivo de prueba visible'
        self.pedido.anulado_por = self.sup
        self.pedido.fecha_anulacion = timezone.now()
        self.pedido.save()
        self.client.force_login(self.sup)
        resp = self.client.get(self._detalle())
        self.assertContains(resp, 'Motivo de prueba visible')
        # Ya anulado: no debe ofrecer volver a anular
        self.assertNotContains(resp, 'modalAnularPedido')


class ReasignarPickerParcialTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_rp', password='x')
        g_picker, _ = Group.objects.get_or_create(name='Pedidos Picker')
        self.p1 = User.objects.create_user(username='picker1', password='x')
        self.p2 = User.objects.create_user(username='picker2', password='x')
        self.p1.groups.add(g_picker)
        self.p2.groups.add(g_picker)
        # Pedido PARCIAL con picker p1 y un item en BACK_ORDER
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='PARCIAL', picker=self.p1)
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='A', descripcion='a',
            cantidad_solicitada=10, cantidad_despachada=4,
            cantidad_back_order=6, estado='BACK_ORDER',
        )

    def test_reasignar_parcial_mueve_a_asignado(self):
        self.client.force_login(self.sup)
        url = self.reverse('pedidos-asignar-picker', args=[self.pedido.numero_pedido])
        resp = self.client.post(url, {'picker_id': self.p2.pk})
        self.assertEqual(resp.status_code, 302)
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'ASIGNADO')
        self.assertEqual(self.pedido.picker, self.p2)
        self.assertIsNotNone(self.pedido.fecha_asignacion)

    def test_liberar_parcial_deja_parcial_sin_picker(self):
        self.client.force_login(self.sup)
        url = self.reverse('pedidos-desasignar-picker', args=[self.pedido.numero_pedido])
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        self.pedido.refresh_from_db()
        self.assertIsNone(self.pedido.picker)
        self.assertEqual(self.pedido.estado, 'PARCIAL')

    def test_liberar_parcial_sin_backorder_pasa_a_pendiente(self):
        # Caso borde: PARCIAL sin items en BACK_ORDER → vuelve a PENDIENTE
        self.pedido.items.update(estado='PARCIAL')
        self.client.force_login(self.sup)
        url = self.reverse('pedidos-desasignar-picker', args=[self.pedido.numero_pedido])
        self.client.post(url)
        self.pedido.refresh_from_db()
        self.assertIsNone(self.pedido.picker)
        self.assertEqual(self.pedido.estado, 'PENDIENTE')


class ReasignarPickerParcialTemplateTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem
        from django.urls import reverse
        self.reverse = reverse
        self.sup = User.objects.create_superuser(username='sup_tpl', password='x')
        g_picker, _ = Group.objects.get_or_create(name='Pedidos Picker')
        self.p1 = User.objects.create_user(username='pk1', password='x')
        self.p1.groups.add(g_picker)
        self.tienda = User.objects.create_user(username='tnd_tpl', password='x')
        g_tienda, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g_tienda)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PARCIAL', picker=self.p1)
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='A', descripcion='a',
            cantidad_solicitada=10, cantidad_despachada=4,
            cantidad_back_order=6, estado='BACK_ORDER',
        )

    def test_supervisor_ve_reasignar_y_liberar_en_parcial(self):
        self.client.force_login(self.sup)
        resp = self.client.get(self.reverse('pedidos-lista'))
        self.assertContains(resp, 'Reasignar picker')
        self.assertContains(resp, self.reverse('pedidos-desasignar-picker', args=[self.pedido.numero_pedido]))

    def test_no_supervisor_no_ve_controles(self):
        self.client.force_login(self.tienda)
        resp = self.client.get(self.reverse('pedidos-lista'))
        self.assertNotContains(resp, 'Reasignar picker')


class CrearPedidoStockTest(TestCase):
    """La vista crear_pedido revalida stock en depósito 1 antes de persistir el pedido."""

    def setUp(self):
        from users.models import User
        from django.urls import reverse
        self.reverse = reverse
        self.user = User.objects.create_superuser(username='stock_u', password='x')
        self.client.force_login(self.user)
        self.url = self.reverse('pedidos-crear')
        self.items = [
            {'codigo': 'SKU1', 'descripcion': 'Producto Uno', 'cantidad': '5',
             'referencia': '', 'puesto': '', 'ref_proveedor': ''},
        ]
        self.form_data = {
            'categoria': 'CAT1',
            'categoria_nombre': 'Categoría 1',
            'condicion': 'URGENTE',
            'deposito': '2',
            'deposito_nombre': 'Tienda Norte',
            'items_json': json.dumps(self.items),
        }

    def _post(self, mock_stock):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.obtener_categorias.return_value = []
            mock_db.return_value.consultar_stock_multiple.return_value = mock_stock
            resp = self.client.post(self.url, self.form_data)
        return resp

    def test_stock_insuficiente_rechaza_pedido(self):
        """Cantidad solicitada > stock → no se crea el Pedido y se rehydrata el carrito."""
        from .models import Pedido
        resp = self._post({'SKU1': 3})  # stock=3, solicitado=5
        self.assertEqual(Pedido.objects.count(), 0)
        self.assertEqual(resp.status_code, 200)
        # El contexto incluye los datos para rehydratar el carrito en el frontend
        self.assertIn('items_json_inicial', resp.context)
        self.assertIn('stock_info_json', resp.context)

    def test_stock_suficiente_crea_pedido(self):
        """Cantidad solicitada ≤ stock disponible → el Pedido se crea."""
        from .models import Pedido
        resp = self._post({'SKU1': 10})  # stock=10, solicitado=5
        self.assertEqual(Pedido.objects.count(), 1)
        self.assertEqual(resp.status_code, 302)

    def test_fallo_dbisam_no_bloquea_creacion(self):
        """Si DBISAM no responde, se emite warning pero el pedido se crea igual."""
        from .models import Pedido
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.obtener_categorias.return_value = []
            mock_db.return_value.consultar_stock_multiple.side_effect = Exception('odbc down')
            resp = self.client.post(self.url, self.form_data)
        self.assertEqual(Pedido.objects.count(), 1)
        self.assertEqual(resp.status_code, 302)

    def test_sin_existencia_rechaza_pedido(self):
        """Producto con stock=0 y cantidad>0 → pedido rechazado con contexto de rehydratación."""
        from .models import Pedido
        resp = self._post({'SKU1': 0})  # stock=0, solicitado=5
        self.assertEqual(Pedido.objects.count(), 0)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('items_json_inicial', resp.context)


class ApiCrearDespachoStockTest(TestCase):
    """api_crear_despacho valida stock en depósito 1 igual que la vista clásica."""

    def setUp(self):
        from rest_framework.test import APIClient
        from users.models import User
        from .models import Pedido, PedidoItem
        self.user = User.objects.create_superuser(username='api_stock_u', password='x')
        # La API usa TokenAuthentication; force_authenticate omite la capa de auth
        self.api_client = APIClient()
        self.api_client.force_authenticate(user=self.user)
        self.pedido = Pedido.objects.create(solicitante=self.user, estado='PENDIENTE')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido,
            codigo='SKU1',
            descripcion='Producto Uno',
            cantidad_solicitada=10,
            estado='PENDIENTE',
        )
        self.url = '/api/despachos/crear/'

    def _post(self, cantidad_despachada, mock_stock=None, dbisam_error=None):
        payload = {
            'pedido_id': self.pedido.numero_pedido,
            'items': [{'pedido_item_id': self.item.id, 'cantidad_despachada': cantidad_despachada}],
        }
        with patch('PedidosAlmacen.api_views.PedidosDBISAM') as mock_db:
            if dbisam_error:
                mock_db.return_value.consultar_stock_multiple.side_effect = dbisam_error
            else:
                mock_db.return_value.consultar_stock_multiple.return_value = mock_stock
            resp = self.api_client.post(self.url, data=payload, format='json')
        return resp

    def test_cantidad_excede_stock_retorna_400(self):
        """cantidad_despachada > stock disponible → 400 y no se crea el Despacho."""
        from .models import Despacho
        resp = self._post(cantidad_despachada=5, mock_stock={'SKU1': 3})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())
        self.assertEqual(Despacho.objects.count(), 0)

    def test_cantidad_igual_a_stock_retorna_201(self):
        """cantidad_despachada ≤ stock disponible → 201 y Despacho creado."""
        from .models import Despacho
        resp = self._post(cantidad_despachada=5, mock_stock={'SKU1': 10})
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Despacho.objects.count(), 1)

    def test_fallo_dbisam_retorna_502(self):
        """Si DBISAM no responde, la API retorna 502 (a diferencia de la vista clásica)."""
        from .models import Despacho
        resp = self._post(cantidad_despachada=5, dbisam_error=Exception('odbc down'))
        self.assertEqual(resp.status_code, 502)
        self.assertIn('error', resp.json())
        self.assertEqual(Despacho.objects.count(), 0)

    def test_sin_existencia_retorna_400(self):
        """Producto con stock=0 en SINVDEP → 400."""
        from .models import Despacho
        resp = self._post(cantidad_despachada=1, mock_stock={'SKU1': 0})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Despacho.objects.count(), 0)


class TrasladosRecepcionExistentesTest(TestCase):
    def _mock_cursor(self, mock_connect):
        conn = mock_connect.return_value.__enter__.return_value
        return conn.cursor.return_value.__enter__.return_value

    def test_devuelve_documentos_encontrados_como_enteros(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = self._mock_cursor(mock_connect)
            cursor.execute.return_value.fetchall.return_value = [
                NS(FTI_DOCUMENTO='00001234'),
                NS(FTI_DOCUMENTO='00005678'),
            ]
            resultado = db.traslados_recepcion_existentes([1234, 5678, 9999], 10)
        self.assertEqual(resultado, {1234, 5678})

    def test_lista_vacia_no_consulta_bd(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            resultado = db.traslados_recepcion_existentes([], 10)
        self.assertEqual(resultado, set())
        mock_connect.assert_not_called()

    def test_sql_filtra_tipo_y_deposito_transito(self):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            cursor = self._mock_cursor(mock_connect)
            cursor.execute.return_value.fetchall.return_value = []
            db.traslados_recepcion_existentes([1234], 15)
            sql = cursor.execute.call_args[0][0]
        self.assertIn('FTI_TIPO = 1', sql)
        self.assertIn('FTI_DEPOSITOSOURCE = 15', sql)
        self.assertIn("'00001234'", sql)

    def test_pagina_en_lotes_de_200(self):
        db = PedidosDBISAM()
        numeros = list(range(1, 251))  # 250 números > 1 lote de 200
        with patch.object(db, 'connect') as mock_connect:
            cursor = self._mock_cursor(mock_connect)
            cursor.execute.return_value.fetchall.return_value = []
            db.traslados_recepcion_existentes(numeros, 10)
        self.assertEqual(cursor.execute.call_count, 2)

    def test_error_dbisam_propaga_databaseerror(self):
        import pyodbc
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            mock_connect.side_effect = Exception('odbc down')
            with self.assertRaises(pyodbc.DatabaseError):
                db.traslados_recepcion_existentes([1234], 10)


class InsertarTrasladoCamposOrigenTest(TestCase):
    """Los traslados deben registrar FTI_DOCUMENTOORIGEN, FTI_CLASIFICACION y FTI_DESCRIPCLASIFY."""

    def _capturar_sql(self, llamada):
        db = PedidosDBISAM()
        with patch.object(db, 'connect') as mock_connect:
            conn = mock_connect.return_value.__enter__.return_value
            # cursor sin context manager (usado por _codigos_existentes_sinvdep)
            conn.cursor.return_value.execute.return_value.fetchall.return_value = []
            cursor = conn.cursor.return_value.__enter__.return_value
            llamada(db)
        return cursor.execute.call_args_list[0][0][0]

    def test_traslado_despacho_escribe_pedido_origen_y_clasificacion_1(self):
        sql = self._capturar_sql(lambda db: db.insertar_traslado_despacho(
            77, 10, [{'codigo': 'SKU1', 'cantidad': 2}],
            responsable='juan', proposito='URGENTE', numero_pedido=1234,
        ))
        self.assertIn('FTI_DOCUMENTOORIGEN', sql)
        self.assertIn('FTI_CLASIFICACION', sql)
        self.assertIn('FTI_DESCRIPCLASIFY', sql)
        self.assertRegex(sql, r"'00001234',\s*1,\s*'DESPACHO'")

    def test_traslado_recepcion_escribe_despacho_origen_y_clasificacion_2(self):
        sql = self._capturar_sql(lambda db: db.insertar_traslado_recepcion(
            1234, 10, 2, [{'codigo': 'SKU1', 'cantidad': 2}],
            responsable='maria', proposito='SURTIDO', numero_despacho=77,
        ))
        self.assertIn('FTI_DOCUMENTOORIGEN', sql)
        self.assertIn('FTI_CLASIFICACION', sql)
        self.assertIn('FTI_DESCRIPCLASIFY', sql)
        self.assertRegex(sql, r"'00000077',\s*2,\s*'RECEPCION TIENDA'")


from io import StringIO
from django.core.management import call_command


class ValidarTrasladosRecepcionCommandTest(TestCase):
    def setUp(self):
        from users.models import User
        self.user = User.objects.create_superuser(username='cmd_valtras', password='x')

    def _crear_pedido_recibido(self, deposito_codigo=2, estado_despacho='RECIBIDO'):
        from .models import Pedido, Despacho
        pedido = Pedido.objects.create(
            solicitante=self.user, estado='RECIBIDO', deposito_codigo=deposito_codigo,
        )
        Despacho.objects.create(pedido=pedido, estado=estado_despacho)
        return pedido

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_detecta_pedido_sin_traslado(self, mock_db):
        pedido = self._crear_pedido_recibido()
        mock_db.return_value.traslados_recepcion_existentes.return_value = set()

        out = StringIO()
        call_command('validar_traslados_recepcion', stdout=out)

        salida = out.getvalue()
        self.assertIn(f'#{pedido.numero_pedido}', salida)
        self.assertIn('1 de 1 pedidos sin traslado', salida)

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_no_reporta_pedido_con_traslado_ok(self, mock_db):
        pedido = self._crear_pedido_recibido()
        mock_db.return_value.traslados_recepcion_existentes.return_value = {pedido.numero_pedido}

        out = StringIO()
        call_command('validar_traslados_recepcion', stdout=out)

        salida = out.getvalue()
        self.assertNotIn(f'#{pedido.numero_pedido}', salida)
        self.assertIn('0 de 1 pedidos sin traslado', salida)

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_sin_candidatos_no_consulta_dbisam(self, mock_db):
        out = StringIO()
        call_command('validar_traslados_recepcion', stdout=out)

        self.assertIn('No hay pedidos candidatos', out.getvalue())
        mock_db.assert_not_called()

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_filtro_pedido_ignora_otros(self, mock_db):
        p1 = self._crear_pedido_recibido()
        p2 = self._crear_pedido_recibido()
        mock_db.return_value.traslados_recepcion_existentes.return_value = set()

        out = StringIO()
        call_command('validar_traslados_recepcion', '--pedido', str(p1.numero_pedido), stdout=out)

        salida = out.getvalue()
        self.assertIn(f'#{p1.numero_pedido}', salida)
        self.assertNotIn(f'#{p2.numero_pedido}', salida)
        mock_db.return_value.traslados_recepcion_existentes.assert_called_once_with([p1.numero_pedido], 10)

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_filtro_dias_excluye_antiguos(self, mock_db):
        from django.utils import timezone
        from datetime import timedelta

        reciente = self._crear_pedido_recibido()
        reciente.fecha_recepcion = timezone.now()
        reciente.save()

        antiguo = self._crear_pedido_recibido()
        antiguo.fecha_recepcion = timezone.now() - timedelta(days=100)
        antiguo.save()

        mock_db.return_value.traslados_recepcion_existentes.return_value = set()

        out = StringIO()
        call_command('validar_traslados_recepcion', '--dias', '30', stdout=out)

        salida = out.getvalue()
        self.assertIn(f'#{reciente.numero_pedido}', salida)
        self.assertNotIn(f'#{antiguo.numero_pedido}', salida)

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_pedido_sin_deposito_codigo_se_excluye(self, mock_db):
        self._crear_pedido_recibido(deposito_codigo=None)

        out = StringIO()
        call_command('validar_traslados_recepcion', stdout=out)

        self.assertIn('No hay pedidos candidatos', out.getvalue())
        mock_db.assert_not_called()

    @patch('PedidosAlmacen.management.commands.validar_traslados_recepcion.PedidosDBISAM')
    def test_error_dbisam_no_rompe_comando(self, mock_db):
        self._crear_pedido_recibido()
        mock_db.return_value.traslados_recepcion_existentes.side_effect = Exception('odbc down')

        out = StringIO()
        err = StringIO()
        call_command('validar_traslados_recepcion', stdout=out, stderr=err)

        self.assertIn('Error al consultar a2', err.getvalue())


class RecibirDespachoTransaccionAtomicaTest(TestCase):
    """recibir_despacho debe ser todo-o-nada: si el traslado en a2 falla o el
    pedido no tiene depósito destino configurado, no debe persistir ningún
    cambio en Postgres, y debe mostrarse un único mensaje de error (nunca
    también un mensaje de éxito)."""

    def setUp(self):
        from users.models import User
        from django.urls import reverse
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.reverse = reverse
        self.user = User.objects.create_superuser(username='recep_atom_u', password='x')
        self.client.force_login(self.user)
        self.pedido = Pedido.objects.create(
            solicitante=self.user, estado='DESPACHADO', deposito_codigo=2,
            condicion='URGENTE',
        )
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=5, cantidad_despachada=5, estado='DESPACHADO',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item, cantidad_despachada=5,
        )
        self.url = reverse(
            'pedidos-recibir-despacho',
            args=[self.pedido.numero_pedido, self.despacho.numero_despacho],
        )

    def _post(self):
        return self.client.post(self.url, {
            f'recibido_{self.di.id}': '5',
            f'observacion_{self.di.id}': '',
            f'tipo_incidencia_{self.di.id}': '',
            'productos_extra': '[]',
        })

    def _mensajes(self, resp):
        from django.contrib.messages import get_messages
        return [str(m) for m in get_messages(resp.wsgi_request)]

    def test_recepcion_exitosa_actualiza_todo_y_solo_muestra_exito(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.insertar_traslado_recepcion.return_value = None
            resp = self._post()

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido]))

        self.despacho.refresh_from_db()
        self.pedido.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'RECIBIDO')
        self.assertEqual(self.pedido.estado, 'RECIBIDO')
        self.assertEqual(self.item.estado, 'RECIBIDO')

        mock_db.return_value.insertar_traslado_recepcion.assert_called_once_with(
            self.pedido.numero_pedido, 10, 2, [{'codigo': 'SKU1', 'cantidad': 5}],
            responsable=self.user.username, proposito='URGENTE',
            numero_despacho=self.despacho.numero_despacho,
        )

        mensajes = self._mensajes(resp)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('registrada correctamente', mensajes[0])

    def test_fallo_a2_no_persiste_nada_y_muestra_un_unico_error(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.insertar_traslado_recepcion.side_effect = Exception('odbc down')
            resp = self._post()

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            self.reverse('pedidos-recibir-despacho', args=[self.pedido.numero_pedido, self.despacho.numero_despacho]),
        )

        self.despacho.refresh_from_db()
        self.pedido.refresh_from_db()
        self.item.refresh_from_db()
        self.di.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ENVIADO')
        self.assertEqual(self.pedido.estado, 'DESPACHADO')
        self.assertEqual(self.item.estado, 'DESPACHADO')
        self.assertEqual(self.di.cantidad_recibida, 0)

        mensajes = self._mensajes(resp)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('No se pudo registrar la recepción', mensajes[0])
        self.assertFalse(any('registrada correctamente' in m for m in mensajes))

    def test_sin_deposito_codigo_bloquea_y_no_llama_a_a2(self):
        self.pedido.deposito_codigo = None
        self.pedido.save()

        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            resp = self._post()
            mock_db.assert_not_called()

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            self.reverse('pedidos-recibir-despacho', args=[self.pedido.numero_pedido, self.despacho.numero_despacho]),
        )

        self.despacho.refresh_from_db()
        self.pedido.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ENVIADO')
        self.assertEqual(self.pedido.estado, 'DESPACHADO')
        self.assertEqual(self.item.estado, 'DESPACHADO')

        mensajes = self._mensajes(resp)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('no tiene depósito destino configurado', mensajes[0])


class RecibirDespachoSkuExtraDuplicadoTest(TestCase):
    """Un producto extra ("SKU no contemplado") cuyo código ya existe en el
    pedido debe bloquearse en la recepción: no se crea el PedidoItem duplicado,
    no se persiste ningún cambio y no se llama a a2. Lo mismo aplica si el
    mismo código viene repetido dentro de la propia lista de extras."""

    GIF_1PX = (
        b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04'
        b'\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D'
        b'\x01\x00;'
    )

    def setUp(self):
        import json
        from users.models import User
        from django.urls import reverse
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.json = json
        self.reverse = reverse
        self.user = User.objects.create_superuser(username='extra_dup_u', password='x')
        self.client.force_login(self.user)
        self.pedido = Pedido.objects.create(
            solicitante=self.user, estado='DESPACHADO', deposito_codigo=2,
            condicion='URGENTE',
        )
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=5, cantidad_despachada=5, estado='DESPACHADO',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item, cantidad_despachada=5,
        )
        self.url = reverse(
            'pedidos-recibir-despacho',
            args=[self.pedido.numero_pedido, self.despacho.numero_despacho],
        )
        # Autorización de supervisor requerida para incidencias especiales
        session = self.client.session
        session['despacho_auth_user_id'] = self.user.id
        session.save()

    def _post(self, extras):
        from django.core.files.uploadedfile import SimpleUploadedFile
        return self.client.post(self.url, {
            f'recibido_{self.di.id}': '5',
            f'observacion_{self.di.id}': '',
            f'tipo_incidencia_{self.di.id}': '',
            'productos_extra': self.json.dumps(extras),
            'foto_extras': SimpleUploadedFile('foto.gif', self.GIF_1PX, content_type='image/gif'),
        })

    def _mensajes(self, resp):
        from django.contrib.messages import get_messages
        return [str(m) for m in get_messages(resp.wsgi_request)]

    def test_extra_con_sku_ya_en_pedido_se_bloquea(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            resp = self._post([{'codigo': 'SKU1', 'descripcion': 'Producto Uno', 'cantidad': 2}])
            mock_db.return_value.insertar_traslado_recepcion.assert_not_called()

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp.url,
            self.reverse('pedidos-recibir-despacho', args=[self.pedido.numero_pedido, self.despacho.numero_despacho]),
        )
        self.assertEqual(self.pedido.items.count(), 1)  # sin duplicado
        self.despacho.refresh_from_db()
        self.di.refresh_from_db()
        self.assertEqual(self.despacho.estado, 'ENVIADO')
        self.assertEqual(self.di.cantidad_recibida, 0)

        mensajes = self._mensajes(resp)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('ya existe en el pedido', mensajes[0])
        self.assertIn('SKU1', mensajes[0])

    def test_extra_con_sku_ya_en_pedido_distinto_case_se_bloquea(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            resp = self._post([{'codigo': ' sku1 ', 'descripcion': 'Producto Uno', 'cantidad': 2}])
            mock_db.return_value.insertar_traslado_recepcion.assert_not_called()

        self.assertEqual(self.pedido.items.count(), 1)
        mensajes = self._mensajes(resp)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('ya existe en el pedido', mensajes[0])

    def test_extra_repetido_en_lista_se_bloquea(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            resp = self._post([
                {'codigo': 'SKU9', 'descripcion': 'Extra', 'cantidad': 1},
                {'codigo': 'SKU9', 'descripcion': 'Extra', 'cantidad': 2},
            ])
            mock_db.return_value.insertar_traslado_recepcion.assert_not_called()

        self.assertEqual(self.pedido.items.count(), 1)
        self.assertFalse(self.pedido.items.filter(codigo='SKU9').exists())
        mensajes = self._mensajes(resp)
        self.assertEqual(len(mensajes), 1)
        self.assertIn('repetido', mensajes[0])
        self.assertIn('SKU9', mensajes[0])

    def test_get_renderiza_codigos_del_pedido_para_validacion_js(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'CODIGOS_PEDIDO')
        self.assertContains(resp, 'SKU1')

    def test_extra_sku_genuinamente_nuevo_sigue_funcionando(self):
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.insertar_traslado_recepcion.return_value = None
            resp = self._post([{'codigo': 'SKU9', 'descripcion': 'Extra', 'cantidad': 2}])

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, self.reverse('pedidos-detalle', args=[self.pedido.numero_pedido]))
        self.assertEqual(self.pedido.items.count(), 2)
        extra = self.pedido.items.get(codigo='SKU9')
        self.assertEqual(extra.estado, 'INCIDENCIA')
        self.assertEqual(extra.cantidad_solicitada, 0)
        self.assertEqual(extra.cantidad_recibida, 2)
        mock_db.return_value.insertar_traslado_recepcion.assert_called_once_with(
            self.pedido.numero_pedido, 10, 2,
            [{'codigo': 'SKU1', 'cantidad': 5}, {'codigo': 'SKU9', 'cantidad': 2}],
            responsable=self.user.username, proposito='URGENTE',
            numero_despacho=self.despacho.numero_despacho,
        )


class ConfiguracionPedidosModelTest(TestCase):
    def test_load_crea_singleton_con_transito_10(self):
        from .models import ConfiguracionPedidos
        config = ConfiguracionPedidos.load()
        self.assertEqual(config.pk, 1)
        self.assertEqual(config.deposito_transito, 10)
        # Llamadas posteriores devuelven la misma fila, sin duplicar
        ConfiguracionPedidos.load()
        self.assertEqual(ConfiguracionPedidos.objects.count(), 1)

    def test_save_fuerza_singleton(self):
        from .models import ConfiguracionPedidos
        ConfiguracionPedidos(deposito_transito=10).save()
        ConfiguracionPedidos(deposito_transito=15).save()  # sobreescribe pk=1
        self.assertEqual(ConfiguracionPedidos.objects.count(), 1)
        self.assertEqual(ConfiguracionPedidos.objects.get(pk=1).deposito_transito, 15)

    def test_clean_rechaza_deposito_no_sincronizado(self):
        from django.core.exceptions import ValidationError
        from .models import ConfiguracionPedidos, DepositoPermitido
        DepositoPermitido.objects.create(codigo=10, nombre='Tránsito')
        config = ConfiguracionPedidos(deposito_transito=99)
        with self.assertRaises(ValidationError):
            config.clean()

    def test_clean_acepta_deposito_sincronizado(self):
        from .models import ConfiguracionPedidos, DepositoPermitido
        DepositoPermitido.objects.create(codigo=15, nombre='Tránsito Nuevo')
        ConfiguracionPedidos(deposito_transito=15).clean()  # no lanza

    def test_clean_no_bloquea_sin_depositos_sincronizados(self):
        from .models import ConfiguracionPedidos
        ConfiguracionPedidos(deposito_transito=99).clean()  # tabla vacía → no lanza


class SnapshotDepositoTransitoTest(TestCase):
    """El despacho graba en el pedido el tránsito configurado (snapshot) y la
    recepción usa ese snapshot como origen, no la configuración vigente."""

    def setUp(self):
        from users.models import User
        from django.urls import reverse
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.reverse = reverse
        self.user = User.objects.create_superuser(username='snap_transito_u', password='x')
        self.client.force_login(self.user)
        self.pedido = Pedido.objects.create(
            solicitante=self.user, estado='DESPACHADO', deposito_codigo=2,
            condicion='URGENTE',
        )
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto Uno',
            cantidad_solicitada=5, cantidad_despachada=5, estado='DESPACHADO',
        )

    def _set_config(self, deposito_transito):
        from .models import ConfiguracionPedidos
        config = ConfiguracionPedidos.load()
        config.deposito_transito = deposito_transito
        config.save()

    def test_confirmar_despacho_graba_snapshot_desde_config(self):
        from .models import Despacho, DespachoItem
        self._set_config(15)
        despacho = Despacho.objects.create(pedido=self.pedido, estado='PENDIENTE_APROBACION')
        DespachoItem.objects.create(
            despacho=despacho, pedido_item=self.item, cantidad_despachada=5,
        )
        url = self.reverse(
            'pedidos-confirmar-despacho',
            args=[self.pedido.numero_pedido, despacho.numero_despacho],
        )
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.consultar_stock_multiple.return_value = {}
            mock_db.return_value.insertar_traslado_despacho.return_value = None
            self.client.post(url, {})

        mock_db.return_value.insertar_traslado_despacho.assert_called_once_with(
            despacho.numero_despacho, 15, [{'codigo': 'SKU1', 'cantidad': 5}],
            responsable=self.user.username, proposito='URGENTE',
            numero_pedido=self.pedido.numero_pedido,
        )
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.deposito_transito, 15)

    def test_recepcion_usa_snapshot_del_pedido_no_la_config(self):
        from .models import Despacho, DespachoItem
        # El pedido se despachó con tránsito 15; luego la config cambió a 99.
        self.pedido.deposito_transito = 15
        self.pedido.save(update_fields=['deposito_transito'])
        self._set_config(99)

        despacho = Despacho.objects.create(pedido=self.pedido, estado='ENVIADO')
        di = DespachoItem.objects.create(
            despacho=despacho, pedido_item=self.item, cantidad_despachada=5,
        )
        url = self.reverse(
            'pedidos-recibir-despacho',
            args=[self.pedido.numero_pedido, despacho.numero_despacho],
        )
        with patch('PedidosAlmacen.views.PedidosDBISAM') as mock_db:
            mock_db.return_value.insertar_traslado_recepcion.return_value = None
            self.client.post(url, {
                f'recibido_{di.id}': '5',
                f'observacion_{di.id}': '',
                f'tipo_incidencia_{di.id}': '',
                'productos_extra': '[]',
            })

        mock_db.return_value.insertar_traslado_recepcion.assert_called_once_with(
            self.pedido.numero_pedido, 15, 2, [{'codigo': 'SKU1', 'cantidad': 5}],
            responsable=self.user.username, proposito='URGENTE',
            numero_despacho=despacho.numero_despacho,
        )


class VolverUrlSesionListasTest(TestCase):
    """Las vistas de lista guardan su URL completa (con filtro) en sesión."""

    def setUp(self):
        from users.models import User
        self.user = User.objects.create_superuser(username='volver_u', password='x')
        self.client.force_login(self.user)

    def test_lista_pedidos_guarda_url_con_filtro_en_sesion(self):
        from django.urls import reverse
        url = reverse('pedidos-lista') + '?estado=PENDIENTE'
        self.client.get(url)
        self.assertEqual(self.client.session['pedidos_volver_url'], url)

    def test_lista_pedidos_sin_filtro_guarda_url_limpia(self):
        from django.urls import reverse
        url = reverse('pedidos-lista')
        self.client.get(url)
        self.assertEqual(self.client.session['pedidos_volver_url'], url)

    def test_lista_despachos_guarda_url_con_filtro_en_sesion(self):
        from django.urls import reverse
        url = reverse('despachos-lista') + '?estado=ENVIADO'
        self.client.get(url)
        self.assertEqual(self.client.session['pedidos_volver_url'], url)


class VolverUrlDetallePedidoTest(TestCase):
    """El detalle del pedido usa la URL de origen guardada en sesión, con fallback."""

    def setUp(self):
        from users.models import User
        from django.urls import reverse
        from .models import Pedido
        self.reverse = reverse
        self.user = User.objects.create_superuser(username='volver_det_u', password='x')
        self.client.force_login(self.user)
        self.pedido = Pedido.objects.create(solicitante=self.user)
        self.url = reverse('pedidos-detalle', args=[self.pedido.numero_pedido])

    def test_boton_volver_usa_url_de_sesion(self):
        origen = self.reverse('despachos-lista') + '?estado=ENVIADO'
        session = self.client.session
        session['pedidos_volver_url'] = origen
        session.save()

        resp = self.client.get(self.url)
        self.assertContains(resp, f'href="{origen}"')

    def test_sin_sesion_cae_a_lista_de_pedidos(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'href="{}"'.format(self.reverse('pedidos-lista')))


class ResolucionIncidenciaModelTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.user = User.objects.create_superuser(username='sup_ri', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.user, estado='PARCIAL')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto 1',
            cantidad_solicitada=5, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )

    def test_estado_incidencia_resuelta_en_choices(self):
        from .models import PedidoItem
        self.assertIn(
            ('INCIDENCIA_RESUELTA', 'Incidencia Resuelta'),
            PedidoItem.ESTADO_ITEM_CHOICES,
        )

    def test_crear_resolucion_con_items_y_eventos(self):
        from .models import ResolucionIncidencia, IncidenciaEvento
        res = ResolucionIncidencia.objects.create(
            tipo='TRASLADO', documento_traslado='00000099', resuelto_por=self.user,
        )
        self.assertEqual(res.estado, 'ACTIVA')
        self.di.resolucion = res
        self.di.save()
        ev = IncidenciaEvento.objects.create(
            despacho_item=self.di, resolucion=res, tipo_evento='RESOLUCION',
            usuario=self.user, detalle='Traslado a2 00000099',
        )
        self.assertEqual(list(res.items_resueltos.all()), [self.di])
        self.assertEqual(list(self.di.eventos_incidencia.all()), [ev])
        self.assertEqual(list(res.eventos.all()), [ev])

    def test_resolucion_nula_significa_pendiente(self):
        from .models import DespachoItem
        pendientes = DespachoItem.objects.exclude(tipo_incidencia='').filter(
            resolucion__isnull=True,
        )
        self.assertEqual(list(pendientes), [self.di])


class ValidarTrasladoResolucionTest(TestCase):
    def _db_con_cursor(self):
        db = PedidosDBISAM()
        ctx = patch.object(db, 'connect')
        mock_connect = ctx.start()
        self.addCleanup(ctx.stop)
        cursor = (mock_connect.return_value.__enter__.return_value
                  .cursor.return_value.__enter__.return_value)
        return db, cursor

    def test_documento_invalido_lanza_valueerror(self):
        db = PedidosDBISAM()
        with self.assertRaises(ValueError):
            db.validar_traslado_resolucion("00'; DROP TABLE X--")

    def test_documento_inexistente(self):
        db, cursor = self._db_con_cursor()
        cursor.execute.return_value.fetchall.side_effect = [[]]
        resultado = db.validar_traslado_resolucion('00000099')
        self.assertFalse(resultado['existe'])
        self.assertEqual(resultado['codigos_traslado'], set())

    def test_documento_existente_devuelve_codigos(self):
        db, cursor = self._db_con_cursor()
        cursor.execute.return_value.fetchall.side_effect = [
            [(501,)],                       # SOPERACIONINV → FTI_AUTOINCREMENT
            [('SKU1 ',), ('SKU2',)],        # SDETALLEINV → FDI_CODIGO (con espacios)
        ]
        resultado = db.validar_traslado_resolucion('99')
        self.assertTrue(resultado['existe'])
        self.assertEqual(resultado['codigos_traslado'], {'SKU1', 'SKU2'})
        # La consulta debe incluir la variante con padding de 8 ceros
        primera_query = cursor.execute.call_args_list[0][0][0]
        self.assertIn("'00000099'", primera_query)
        self.assertIn('FTI_TIPO = 1', primera_query)


class ResolverIncidenciasVistaTest(TestCase):
    def setUp(self):
        from users.models import User
        from django.contrib.auth.models import Group
        from .models import Pedido, PedidoItem, Despacho, DespachoItem, ResolucionIncidencia
        self.sup = User.objects.create_superuser(username='sup_res', password='x')
        self.tienda = User.objects.create_user(username='tnd_res', password='x')
        g, _ = Group.objects.get_or_create(name='Pedidos Tienda')
        self.tienda.groups.add(g)
        self.pedido = Pedido.objects.create(solicitante=self.tienda, estado='PARCIAL')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto 1',
            cantidad_solicitada=5, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.pendiente = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )
        self.resolucion = ResolucionIncidencia.objects.create(
            tipo='MANUAL', observacion='ajuste', resuelto_por=self.sup,
        )
        item2 = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU2', descripcion='Producto 2',
            cantidad_solicitada=3, estado='INCIDENCIA_RESUELTA',
        )
        self.resuelta = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=item2,
            cantidad_despachada=3, tipo_incidencia='CANTIDAD_MAYOR',
            resolucion=self.resolucion,
        )

    def test_no_supervisor_redirige(self):
        self.client.force_login(self.tienda)
        resp = self.client.get('/pedidos/incidencias/resolver/')
        self.assertEqual(resp.status_code, 302)

    def test_pendientes_por_defecto(self):
        self.client.force_login(self.sup)
        resp = self.client.get('/pedidos/incidencias/resolver/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context['incidencias']), [self.pendiente])
        self.assertEqual(resp.context['total_pendientes'], 1)
        self.assertEqual(resp.context['total_resueltas'], 1)

    def test_vista_resueltas(self):
        self.client.force_login(self.sup)
        resp = self.client.get('/pedidos/incidencias/resolver/?vista=resueltas')
        self.assertEqual(list(resp.context['incidencias']), [self.resuelta])

    def test_sku_incidencia_helper(self):
        from .views import _sku_incidencia
        self.assertEqual(_sku_incidencia(self.pendiente), 'SKU1')
        self.pendiente.tipo_incidencia = 'PRODUCTO_ERRONEO'
        self.pendiente.codigo_real = 'REAL9'
        self.assertEqual(_sku_incidencia(self.pendiente), 'REAL9')


class ValidarTrasladoEndpointTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.sup = User.objects.create_superuser(username='sup_val', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='PARCIAL')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='Producto 1',
            cantidad_solicitada=5, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )
        self.url = '/pedidos/incidencias/resolver/validar/'
        self.client.force_login(self.sup)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_traslado_valido_cubre_skus(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1', 'OTRO'},
        }
        resp = self.client.post(self.url, {'documento': '99', 'item_ids': [self.di.id]})
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertTrue(data['existe'])
        self.assertTrue(data['valido'])
        self.assertEqual(data['faltantes'], [])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_traslado_no_cubre_sku(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'OTRO'},
        }
        resp = self.client.post(self.url, {'documento': '99', 'item_ids': [self.di.id]})
        data = resp.json()
        self.assertTrue(data['existe'])
        self.assertFalse(data['valido'])
        self.assertEqual(data['faltantes'], ['SKU1'])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_documento_inexistente(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': False, 'codigos_traslado': set(),
        }
        resp = self.client.post(self.url, {'documento': '99', 'item_ids': [self.di.id]})
        data = resp.json()
        self.assertTrue(data['ok'])
        self.assertFalse(data['existe'])

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_error_odbc_devuelve_502(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.side_effect = Exception('odbc down')
        resp = self.client.post(self.url, {'documento': '99', 'item_ids': [self.di.id]})
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(resp.json()['ok'])

    def test_sin_documento_devuelve_400(self):
        resp = self.client.post(self.url, {'documento': '', 'item_ids': [self.di.id]})
        self.assertEqual(resp.status_code, 400)


class ConfirmarResolucionTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem, Despacho, DespachoItem
        self.sup = User.objects.create_superuser(username='sup_conf', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='PARCIAL')
        self.item1 = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='P1',
            cantidad_solicitada=5, cantidad_recibida=5, estado='INCIDENCIA',
        )
        self.item2 = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU2', descripcion='P2',
            cantidad_solicitada=3, cantidad_recibida=3, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.di1 = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item1,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )
        self.di2 = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item2,
            cantidad_despachada=3, tipo_incidencia='CANTIDAD_MAYOR',
        )
        self.url = '/pedidos/incidencias/resolver/confirmar/'
        self.client.force_login(self.sup)

    def _post_traslado(self, item_ids, documento='99'):
        return self.client.post(self.url, {
            'item_ids': item_ids, 'tipo': 'TRASLADO', 'documento': documento,
        })

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_resuelve_todas_despacho_recibido(self, mock_db):
        from .models import ResolucionIncidencia, IncidenciaEvento
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1', 'SKU2'},
        }
        resp = self._post_traslado([self.di1.id, self.di2.id])
        self.assertEqual(resp.status_code, 302)
        self.di1.refresh_from_db(); self.di2.refresh_from_db()
        self.item1.refresh_from_db(); self.item2.refresh_from_db()
        self.despacho.refresh_from_db()
        res = ResolucionIncidencia.objects.get()
        self.assertEqual(res.tipo, 'TRASLADO')
        self.assertEqual(res.documento_traslado, '99')
        self.assertEqual(self.di1.resolucion, res)
        self.assertEqual(self.di2.resolucion, res)
        self.assertEqual(self.item1.estado, 'INCIDENCIA_RESUELTA')
        self.assertEqual(self.item2.estado, 'INCIDENCIA_RESUELTA')
        self.assertEqual(self.despacho.estado, 'RECIBIDO')
        self.assertEqual(IncidenciaEvento.objects.filter(tipo_evento='RESOLUCION').count(), 2)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_resolucion_parcial_despacho_sigue_parcial(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1'},
        }
        self._post_traslado([self.di1.id])
        self.despacho.refresh_from_db()
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.estado, 'INCIDENCIA_RESUELTA')
        self.assertEqual(self.despacho.estado, 'PARCIAL')

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_documento_inexistente_no_resuelve(self, mock_db):
        from .models import ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': False, 'codigos_traslado': set(),
        }
        self._post_traslado([self.di1.id])
        self.assertEqual(ResolucionIncidencia.objects.count(), 0)
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.estado, 'INCIDENCIA')

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_sku_no_cubierto_no_resuelve(self, mock_db):
        from .models import ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'OTRO'},
        }
        self._post_traslado([self.di1.id])
        self.assertEqual(ResolucionIncidencia.objects.count(), 0)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_error_odbc_no_resuelve(self, mock_db):
        from .models import ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.side_effect = Exception('odbc down')
        self._post_traslado([self.di1.id])
        self.assertEqual(ResolucionIncidencia.objects.count(), 0)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_manual_no_llama_a2(self, mock_db):
        from .models import ResolucionIncidencia
        self.client.post(self.url, {
            'item_ids': [self.di1.id], 'tipo': 'MANUAL',
            'observacion': 'Se ajustó directo en a2',
        })
        mock_db.return_value.validar_traslado_resolucion.assert_not_called()
        res = ResolucionIncidencia.objects.get()
        self.assertEqual(res.tipo, 'MANUAL')
        self.item1.refresh_from_db()
        self.assertEqual(self.item1.estado, 'INCIDENCIA_RESUELTA')

    def test_manual_sin_observacion_no_resuelve(self):
        from .models import ResolucionIncidencia
        self.client.post(self.url, {'item_ids': [self.di1.id], 'tipo': 'MANUAL', 'observacion': ''})
        self.assertEqual(ResolucionIncidencia.objects.count(), 0)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_ya_resuelta_por_otra_sesion_no_duplica(self, mock_db):
        from .models import ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1'},
        }
        previa = ResolucionIncidencia.objects.create(tipo='MANUAL', observacion='x', resuelto_por=self.sup)
        self.di1.resolucion = previa
        self.di1.save()
        self._post_traslado([self.di1.id])
        self.assertEqual(ResolucionIncidencia.objects.count(), 1)
        self.di1.refresh_from_db()
        self.assertEqual(self.di1.resolucion, previa)

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_pedido_recibido_si_todo_resuelto(self, mock_db):
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1', 'SKU2'},
        }
        self._post_traslado([self.di1.id, self.di2.id])
        self.pedido.refresh_from_db()
        self.assertEqual(self.pedido.estado, 'RECIBIDO')
        self.assertIsNotNone(self.pedido.fecha_recepcion)


class AnularResolucionTest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import (
            Pedido, PedidoItem, Despacho, DespachoItem,
            ResolucionIncidencia, IncidenciaEvento,
        )
        self.sup = User.objects.create_superuser(username='sup_anul', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='RECIBIDO')
        self.item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='P1',
            cantidad_solicitada=5, estado='INCIDENCIA_RESUELTA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='RECIBIDO')
        self.res = ResolucionIncidencia.objects.create(
            tipo='TRASLADO', documento_traslado='00000099', resuelto_por=self.sup,
        )
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=self.item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
            resolucion=self.res,
        )
        IncidenciaEvento.objects.create(
            despacho_item=self.di, resolucion=self.res,
            tipo_evento='RESOLUCION', usuario=self.sup, detalle='Traslado a2 00000099',
        )
        self.url = f'/pedidos/incidencias/resolver/anular/{self.res.id}/'
        self.client.force_login(self.sup)

    def test_anula_y_revierte_estados(self):
        from .models import IncidenciaEvento
        resp = self.client.post(self.url, {'motivo': 'Documento equivocado'})
        self.assertEqual(resp.status_code, 302)
        self.res.refresh_from_db(); self.di.refresh_from_db()
        self.item.refresh_from_db(); self.despacho.refresh_from_db()
        self.pedido.refresh_from_db()
        self.assertEqual(self.res.estado, 'ANULADA')
        self.assertEqual(self.res.anulada_por, self.sup)
        self.assertEqual(self.res.motivo_anulacion, 'Documento equivocado')
        self.assertIsNotNone(self.res.fecha_anulacion)
        self.assertIsNone(self.di.resolucion)
        self.assertEqual(self.item.estado, 'INCIDENCIA')
        self.assertEqual(self.despacho.estado, 'PARCIAL')
        self.assertEqual(self.pedido.estado, 'PARCIAL')
        self.assertEqual(
            IncidenciaEvento.objects.filter(despacho_item=self.di).count(), 2,
        )

    def test_sin_motivo_no_anula(self):
        self.client.post(self.url, {'motivo': ''})
        self.res.refresh_from_db()
        self.assertEqual(self.res.estado, 'ACTIVA')

    def test_ya_anulada_no_se_reanula(self):
        self.client.post(self.url, {'motivo': 'Primera'})
        self.client.post(self.url, {'motivo': 'Segunda'})
        self.res.refresh_from_db()
        self.assertEqual(self.res.motivo_anulacion, 'Primera')

    @patch('PedidosAlmacen.views.PedidosDBISAM')
    def test_re_resolucion_tras_anulacion_acumula_historial(self, mock_db):
        from .models import IncidenciaEvento, ResolucionIncidencia
        mock_db.return_value.validar_traslado_resolucion.return_value = {
            'existe': True, 'codigos_traslado': {'SKU1'},
        }
        self.client.post(self.url, {'motivo': 'Documento equivocado'})
        self.client.post('/pedidos/incidencias/resolver/confirmar/', {
            'item_ids': [self.di.id], 'tipo': 'TRASLADO', 'documento': '100',
        })
        self.di.refresh_from_db(); self.item.refresh_from_db()
        nueva = ResolucionIncidencia.objects.exclude(pk=self.res.pk).get()
        self.assertEqual(self.di.resolucion, nueva)
        self.assertEqual(self.item.estado, 'INCIDENCIA_RESUELTA')
        # Historial: resolución original + anulación + nueva resolución
        eventos = list(
            IncidenciaEvento.objects.filter(despacho_item=self.di)
            .values_list('tipo_evento', flat=True)
        )
        self.assertEqual(eventos, ['RESOLUCION', 'ANULACION', 'RESOLUCION'])


class ResolverIncidenciasUITest(TestCase):
    def setUp(self):
        from users.models import User
        from .models import Pedido, PedidoItem, Despacho, DespachoItem, ResolucionIncidencia
        self.sup = User.objects.create_superuser(username='sup_ui', password='x')
        self.pedido = Pedido.objects.create(solicitante=self.sup, estado='PARCIAL')
        item = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU1', descripcion='P1',
            cantidad_solicitada=5, estado='INCIDENCIA',
        )
        self.despacho = Despacho.objects.create(pedido=self.pedido, estado='PARCIAL')
        self.di = DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=item,
            cantidad_despachada=5, tipo_incidencia='CANTIDAD_MENOR',
        )
        self.res = ResolucionIncidencia.objects.create(
            tipo='TRASLADO', documento_traslado='00000099', resuelto_por=self.sup,
        )
        self.client.force_login(self.sup)

    def test_pendientes_tiene_form_y_checkboxes(self):
        resp = self.client.get('/pedidos/incidencias/resolver/')
        self.assertContains(resp, '/pedidos/incidencias/resolver/confirmar/')
        self.assertContains(resp, f'name="item_ids" value="{self.di.id}"')
        self.assertContains(resp, 'btn-validar')

    def test_resueltas_tiene_boton_anular(self):
        from .models import PedidoItem, DespachoItem
        item2 = PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU2', descripcion='P2',
            cantidad_solicitada=1, estado='INCIDENCIA_RESUELTA',
        )
        DespachoItem.objects.create(
            despacho=self.despacho, pedido_item=item2,
            cantidad_despachada=1, tipo_incidencia='CANTIDAD_MAYOR',
            resolucion=self.res,
        )
        resp = self.client.get('/pedidos/incidencias/resolver/?vista=resueltas')
        self.assertContains(resp, f'/pedidos/incidencias/resolver/anular/{self.res.id}/')
        self.assertContains(resp, '00000099')

    def test_detalle_pedido_muestra_badge_resuelta(self):
        from .models import PedidoItem
        PedidoItem.objects.create(
            pedido=self.pedido, codigo='SKU3', descripcion='P3',
            cantidad_solicitada=1, estado='INCIDENCIA_RESUELTA',
        )
        resp = self.client.get(f'/pedidos/{self.pedido.numero_pedido}/')
        self.assertContains(resp, 'Inc. Resuelta')
