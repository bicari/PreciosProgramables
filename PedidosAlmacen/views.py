from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.contrib.auth import authenticate as django_authenticate
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Count, IntegerField, Q, Max
from django.db.models import Case, When, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import datetime, timedelta, time as dtime
from .models import (
    Pedido, PedidoItem, Despacho, DespachoItem, DepositoPermitido,
    ConfiguracionPedidos, ResolucionIncidencia, IncidenciaEvento,
)
from .forms import PedidoForm
from .dbisam import PedidosDBISAM, DEPOSITO_ALMACEN
from .notifications import notificar_nuevo_pedido, notificar_despacho, notificar_despacho_parcial
from .pdf import generar_reporte_pedidos_pdf, generar_reporte_pickers_pdf, generar_pedido_pdf, generar_despacho_pdf
import logging
import json

logger = logging.getLogger(__name__)

_HORA_INICIO_LABORAL = dtime(8, 0)
_HORA_FIN_LABORAL = dtime(17, 0)


def _segundos_laborales(inicio: datetime, fin: datetime) -> float:
    """Segundos laborales entre dos momentos. Horario L-V 08:00-17:00."""
    if fin <= inicio:
        return 0.0
    total = 0.0
    current = inicio
    while current < fin:
        wd = current.weekday()
        if wd >= 5:  # sábado=5, domingo=6
            current = datetime.combine(current.date() + timedelta(days=7 - wd), _HORA_INICIO_LABORAL)
            continue
        dia_inicio = datetime.combine(current.date(), _HORA_INICIO_LABORAL)
        dia_fin = datetime.combine(current.date(), _HORA_FIN_LABORAL)
        if current < dia_inicio:
            current = dia_inicio
        if current >= dia_fin:
            current = datetime.combine(current.date() + timedelta(days=1), _HORA_INICIO_LABORAL)
            continue
        corte = min(fin, dia_fin)
        total += (corte - current).total_seconds()
        current = datetime.combine(current.date() + timedelta(days=1), _HORA_INICIO_LABORAL)
    return total


def _depositos_para_selector() -> list[tuple[int, str]]:
    """Depósitos seleccionables al crear un pedido.

    Devuelve los DepositoPermitido activos (codigo, nombre). Si no hay ninguno
    activo, cae al listado de a2 (todos menos el almacén) como fallback.
    """
    activos = list(
        DepositoPermitido.objects.filter(activo=True)
        .order_by('nombre')
        .values_list('codigo', 'nombre')
    )
    if activos:
        return [(c, n) for c, n in activos]
    try:
        rows = PedidosDBISAM().obtener_depositos()
        return [(int(r.FDP_CODIGO), r.FDP_DESCRIPCION or '') for r in rows]
    except Exception:
        logger.exception('Fallback de depositos: error al consultar DBISAM')
        return []


GROUP_TIENDA = 'Pedidos Tienda'
GROUP_ALMACEN = 'Pedidos Almacen'
GROUP_SUPERVISOR = 'Pedidos Supervisor'
GROUP_PICKER = 'Pedidos Picker'
GROUP_RECEPTOR = 'Pedidos Receptor'


def is_pedidos_tienda(user):
    return user.groups.filter(name=GROUP_TIENDA).exists() or user.is_superuser


def is_pedidos_almacen(user):
    return user.groups.filter(name=GROUP_ALMACEN).exists() or user.is_superuser


def is_pedidos_supervisor(user):
    return user.groups.filter(name=GROUP_SUPERVISOR).exists() or user.is_superuser


def is_pedidos_supervisor_o_almacen(user):
    """Puede cerrar pedidos: Supervisor, Almacén o superuser."""
    return is_pedidos_supervisor(user) or is_pedidos_almacen(user)


def is_pedidos_picker(user):
    return user.groups.filter(name=GROUP_PICKER).exists() or user.is_superuser


def is_pedidos_any(user):
    grupos = [GROUP_TIENDA, GROUP_ALMACEN, GROUP_SUPERVISOR, GROUP_PICKER, GROUP_RECEPTOR]
    return user.groups.filter(name__in=grupos).exists() or user.is_superuser


def _solo_tienda(user):
    """True si el usuario es Tienda pero NO Almacen ni Supervisor (acceso restringido a sus propios pedidos)."""
    return is_pedidos_tienda(user) and not is_pedidos_almacen(user) and not is_pedidos_supervisor(user)


def _solo_picker(user):
    """True si el usuario es Picker pero NO Almacen ni Supervisor."""
    return is_pedidos_picker(user) and not is_pedidos_almacen(user) and not is_pedidos_supervisor(user)


def is_pedidos_receptor(user):
    """Puede recibir despachos: grupo Pedidos Receptor, Supervisor o superuser."""
    if user.is_superuser or is_pedidos_supervisor(user):
        return True
    return user.groups.filter(name=GROUP_RECEPTOR).exists()


def _es_receptor_grupo(user) -> bool:
    """True si el usuario pertenece al grupo Pedidos Receptor (sin incluir Supervisor ni superuser)."""
    return user.groups.filter(name=GROUP_RECEPTOR).exists()


def _codigos_depositos_receptor(user) -> list[int]:
    """Códigos de depósito asignados al usuario para recepción."""
    return list(user.depositos_recepcion.values_list('codigo', flat=True))


def puede_recibir_pedido(user, pedido) -> bool:
    """True si el usuario puede recibir despachos de este pedido.

    Supervisor y superuser reciben cualquiera; un receptor solo si el
    depósito destino del pedido está entre sus depósitos asignados.
    """
    if user.is_superuser or is_pedidos_supervisor(user):
        return True
    if _es_receptor_grupo(user):
        return pedido.deposito_codigo in _codigos_depositos_receptor(user)
    return False


def _puede_ver_pedido(user, pedido) -> bool:
    """Acceso al detalle: True si algún rol del usuario alcanza este pedido."""
    if user.is_superuser or is_pedidos_supervisor(user) or is_pedidos_almacen(user):
        return True
    if is_pedidos_tienda(user) and pedido.solicitante == user:
        return True
    if is_pedidos_picker(user) and pedido.picker == user:
        return True
    if _es_receptor_grupo(user) and pedido.deposito_codigo in _codigos_depositos_receptor(user):
        return True
    return False


# Variantes de impresión de un pedido. 'estado' None = sin filtro (todos los items).
# 'tienda' indica si un usuario solo-Tienda puede generarla.
VISTAS_PEDIDO = {
    'todos':      {'label': 'Todos',      'estado': None,         'tienda': True},
    'despachado': {'label': 'Despachado', 'estado': 'DESPACHADO', 'tienda': False},
    'back_order': {'label': 'Back Order', 'estado': 'BACK_ORDER', 'tienda': True},
    'recibido':   {'label': 'Recibido',   'estado': 'RECIBIDO',   'tienda': True},
    'parcial':    {'label': 'Parcial',    'estado': 'PARCIAL',    'tienda': False},
}


def _puede_vista_pedido(user, vista: str) -> bool:
    """True si el usuario puede generar la variante de impresión indicada."""
    cfg = VISTAS_PEDIDO.get(vista)
    if cfg is None:
        return False
    if _solo_tienda(user):
        return cfg['tienda']
    return True


def _pickers_disponibles():
    """Pickers activos anotados con su carga actual (pedidos ASIGNADO/PICKING en cola), ordenados por menor carga."""
    from users.models import User as UserModel
    return UserModel.objects.filter(
        groups__name=GROUP_PICKER, status=True,
    ).annotate(
        carga=Count('pedidos_picking', filter=Q(pedidos_picking__estado__in=['ASIGNADO', 'PICKING']))
    ).order_by('carga', 'username')


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_any, login_url='dashboard')
def lista_pedidos(request):
    if is_pedidos_supervisor(request.user):
        pedidos = Pedido.objects.select_related('solicitante', 'despachador', 'picker').order_by('-fecha_creacion')
    elif is_pedidos_almacen(request.user):
        pedidos = Pedido.objects.select_related('solicitante', 'despachador', 'picker').exclude(estado='CERRADO').order_by('-fecha_creacion')
    elif _solo_picker(request.user) and not _es_receptor_grupo(request.user):
        pedidos = Pedido.objects.filter(
            picker=request.user, estado__in=['ASIGNADO', 'PICKING', 'EN_PREPARACION'],
        ).select_related('solicitante', 'despachador', 'picker').order_by('fecha_asignacion', 'fecha_creacion')
    else:
        condiciones = Q()
        if is_pedidos_tienda(request.user):
            condiciones |= Q(solicitante=request.user)
        if _solo_picker(request.user):
            condiciones |= Q(picker=request.user, estado__in=['ASIGNADO', 'PICKING', 'EN_PREPARACION'])
        if _es_receptor_grupo(request.user):
            condiciones |= Q(deposito_codigo__in=_codigos_depositos_receptor(request.user))
        pedidos = Pedido.objects.filter(condiciones) if condiciones else Pedido.objects.none()
        pedidos = pedidos.select_related('solicitante', 'despachador', 'picker').order_by('-fecha_creacion')

    estado_filter = request.GET.get('estado', '')
    if estado_filter:
        pedidos = pedidos.filter(estado=estado_filter)

    pedidos = pedidos.annotate(
        items_back_order=Count(
            Case(When(items__estado='BACK_ORDER', then=Value(1)), output_field=IntegerField())
        )
    )

    lista_pickers_disponibles = []
    if is_pedidos_supervisor(request.user):
        lista_pickers_disponibles = list(_pickers_disponibles())

    request.session['pedidos_volver_url'] = request.get_full_path()
    return render(request, 'pedidos-lista.html', {
        'pedidos': pedidos,
        'estado_filter': estado_filter,
        'estados': Pedido.ESTADO_CHOICES,
        'es_tienda': _solo_tienda(request.user),
        'es_picker': _solo_picker(request.user) and not _es_receptor_grupo(request.user),
        'es_supervisor': is_pedidos_supervisor(request.user),
        'pickers_disponibles': lista_pickers_disponibles,
        'puede_recibir': is_pedidos_receptor(request.user),
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_tienda, login_url='dashboard')
def crear_pedido(request):
    categorias = []
    try:
        categorias = PedidosDBISAM().obtener_categorias()
    except Exception:
        pass
    depositos = _depositos_para_selector()

    ctx = {
        'form': PedidoForm(),
        'categorias': categorias,
        'depositos': depositos,
        'condiciones': Pedido.CONDICION_CHOICES,
    }

    if request.method == 'POST':
        form = PedidoForm(request.POST)
        ctx['form'] = form
        items_json = request.POST.get('items_json', '[]')
        categoria_codigo = request.POST.get('categoria', '').strip()
        categoria_nombre = request.POST.get('categoria_nombre', '').strip()
        condicion = request.POST.get('condicion', '').strip()
        deposito_codigo = request.POST.get('deposito', '').strip()
        deposito_nombre = request.POST.get('deposito_nombre', '').strip()

        try:
            items_data = json.loads(items_json)
        except json.JSONDecodeError:
            items_data = []

        if not categoria_codigo:
            messages.error(request, 'Debe seleccionar una categoria para el pedido', extra_tags='danger')
            return render(request, 'pedidos-crear.html', ctx)

        if not condicion:
            messages.error(request, 'Debe seleccionar la condicion del pedido', extra_tags='danger')
            return render(request, 'pedidos-crear.html', ctx)

        if not deposito_codigo:
            messages.error(request, 'Debe seleccionar el deposito de origen', extra_tags='danger')
            return render(request, 'pedidos-crear.html', ctx)

        if not items_data:
            messages.error(request, 'Debe agregar al menos un producto al pedido', extra_tags='danger')
            return render(request, 'pedidos-crear.html', ctx)

        # Revalidar existencia en depósito 1 (Almacén) en el servidor.
        # El frontend bloquea el botón "Agregar" para existencia=0, pero la validación
        # aquí cubre manipulaciones del form o cambios de stock entre búsqueda y envío.
        codigos_pedido = [item['codigo'] for item in items_data]
        stock_pedido = {}
        dbisam_consulta_ok = False
        try:
            stock_pedido = PedidosDBISAM().consultar_stock_multiple(codigos_pedido, deposito=DEPOSITO_ALMACEN)
            dbisam_consulta_ok = True
        except Exception as e:
            messages.warning(request, f'No se pudo verificar el stock en almacén: {e}')

        if dbisam_consulta_ok:
            excesos_stock = [
                item['codigo']
                for item in items_data
                if int(item['cantidad']) > stock_pedido.get(item['codigo'], 0)
            ]
            if excesos_stock:
                messages.warning(
                    request,
                    'Hay ítems con cantidad que supera el stock disponible en almacén. '
                    'Corrija las cantidades marcadas en rojo antes de enviar el pedido.',
                )
                ctx.update({
                    'items_json_inicial': items_json,
                    'stock_info_json': json.dumps(stock_pedido),
                    'categoria_inicial': categoria_codigo,
                    'categoria_nombre_inicial': categoria_nombre,
                    'condicion_inicial': condicion,
                    'deposito_inicial': deposito_codigo,
                    'deposito_nombre_inicial': deposito_nombre or deposito_codigo,
                })
                return render(request, 'pedidos-crear.html', ctx)

        deposito_codigo_int = None
        try:
            deposito_codigo_int = int(deposito_codigo)
        except (ValueError, TypeError):
            pass

        pedido = Pedido.objects.create(
            solicitante=request.user,
            observaciones=form.data.get('observaciones', ''),
            categoria=categoria_codigo,
            categoria_nombre=categoria_nombre,
            condicion=condicion,
            deposito=deposito_nombre or deposito_codigo,
            deposito_codigo=deposito_codigo_int,
        )

        items = [
            PedidoItem(
                pedido=pedido,
                codigo=item['codigo'],
                descripcion=item['descripcion'],
                referencia=item.get('referencia', ''),
                puesto=item.get('puesto', ''),
                ref_proveedor=item.get('ref_proveedor', ''),
                cantidad_solicitada=int(item['cantidad']),
            )
            for item in items_data
        ]
        PedidoItem.objects.bulk_create(items)
        notificar_nuevo_pedido(pedido)
        messages.success(request, f'Pedido #{pedido.numero_pedido} creado exitosamente')
        return redirect('pedidos-lista')

    return render(request, 'pedidos-crear.html', ctx)


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_any, login_url='dashboard')
def detalle_pedido(request, pk):
    pedido = get_object_or_404(Pedido.objects.select_related('solicitante', 'despachador', 'picker'), numero_pedido=pk)

    if not _puede_ver_pedido(request.user, pedido):
        messages.error(request, 'No tienes permiso para ver este pedido')
        return redirect('pedidos-lista')

    items = pedido.items.all()
    despachos = pedido.despachos.prefetch_related('items__pedido_item').order_by('fecha_despacho')

    from django.db.models import Count
    conteos = {
        fila['estado']: fila['c']
        for fila in items.values('estado').annotate(c=Count('id'))
    }
    total_items = items.count()
    vistas_pdf = []
    for clave, cfg in VISTAS_PEDIDO.items():
        if not _puede_vista_pedido(request.user, clave):
            continue
        count = total_items if cfg['estado'] is None else conteos.get(cfg['estado'], 0)
        vistas_pdf.append({'clave': clave, 'label': cfg['label'], 'count': count})

    es_supervisor = is_pedidos_supervisor(request.user)
    es_despachador = is_pedidos_almacen(request.user)
    es_picker_asignado = _solo_picker(request.user) and pedido.picker == request.user
    return render(request, 'pedidos-detalle.html', {
        'pedido': pedido,
        'items': items,
        'despachos': despachos,
        'ver_despachado': es_supervisor,
        'es_supervisor': es_supervisor,
        'es_despachador': es_despachador,
        'puede_recibir': puede_recibir_pedido(request.user, pedido),
        'ver_cantidad_despacho': es_despachador or request.user.is_superuser,
        'puede_imprimir_despacho': request.user.is_superuser or is_pedidos_almacen(request.user) or is_pedidos_supervisor(request.user),
        'es_superuser': request.user.is_superuser,
        'es_picker_asignado': es_picker_asignado,
        'puede_cerrar': (es_supervisor or es_despachador) and _puede_cerrar_pedido(pedido),
        'vistas_pdf': vistas_pdf,
        'volver_url': request.session.get('pedidos_volver_url') or reverse('pedidos-lista'),
    })


def _puede_cerrar_pedido(pedido: Pedido) -> bool:
    """True si el pedido es elegible para cierre (no chequea permisos).

    Elegible: estado PARCIAL y sin despachos aún no finalizados.
    """
    if pedido.estado != 'PARCIAL':
        return False
    return not pedido.despachos.filter(
        estado__in=('ENVIADO', 'PENDIENTE_APROBACION', 'PREPARANDO')
    ).exists()


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def anular_pedido(request, pk):
    pedido = get_object_or_404(Pedido, numero_pedido=pk)
    if request.method != 'POST':
        return redirect('pedidos-detalle', pk=pk)
    if pedido.estado == 'ANULADO':
        messages.warning(request, 'Este pedido ya está anulado')
        return redirect('pedidos-detalle', pk=pk)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Debes indicar un motivo para anular el pedido')
        return redirect('pedidos-detalle', pk=pk)
    pedido.estado_anterior = pedido.estado
    if pedido.estado in ('ASIGNADO', 'PICKING'):
        pedido.picker = None
    pedido.estado = 'ANULADO'
    pedido.anulado_por = request.user
    pedido.fecha_anulacion = timezone.now()
    pedido.motivo_anulacion = motivo
    pedido.save()
    logger.info(
        'Pedido #%s anulado por %s. Motivo: %s',
        pedido.numero_pedido, request.user.username, motivo,
    )
    messages.success(request, f'Pedido #{pedido.numero_pedido} anulado')
    return redirect('pedidos-detalle', pk=pk)


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor_o_almacen, login_url='dashboard')
def cerrar_pedido(request, pk):
    """Cierra un pedido PARCIAL cuyos back orders no se van a completar.

    Deja cantidad_back_order = 0 en los items pendientes (PARCIAL/BACK_ORDER),
    los marca CERRADO y registra auditoría en el pedido.
    """
    if request.method != 'POST':
        return redirect('pedidos-detalle', pk=pk)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Debes indicar un motivo para cerrar el pedido')
        return redirect('pedidos-detalle', pk=pk)
    with transaction.atomic():
        pedido = get_object_or_404(
            Pedido.objects.select_for_update(), numero_pedido=pk,
        )
        if not _puede_cerrar_pedido(pedido):
            messages.error(
                request,
                'Este pedido no se puede cerrar: debe estar en estado Parcial '
                'y no tener despachos pendientes',
            )
            return redirect('pedidos-detalle', pk=pk)
        pedido.items.filter(estado__in=('PARCIAL', 'BACK_ORDER')).update(
            cantidad_back_order=0, estado='CERRADO',
        )
        pedido.estado = 'CERRADO'
        pedido.cerrado_por = request.user
        pedido.fecha_cierre = timezone.now()
        pedido.motivo_cierre = motivo
        pedido.save()
    logger.info(
        'Pedido #%s cerrado por %s. Motivo: %s',
        pedido.numero_pedido, request.user.username, motivo,
    )
    messages.success(request, f'Pedido #{pedido.numero_pedido} cerrado')
    return redirect('pedidos-detalle', pk=pk)


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_almacen, login_url='dashboard')
def despachar_pedido(request, pk):
    pedido = get_object_or_404(Pedido, numero_pedido=pk)

    if pedido.estado not in ('PENDIENTE', 'ASIGNADO', 'PICKING', 'EN_PREPARACION', 'PARCIAL'):
        messages.warning(request, 'Este pedido no puede ser despachado en su estado actual')
        return redirect('pedidos-detalle', pk=pk)

    # En PARCIAL solo se despachan los items pendientes (BACK_ORDER y PARCIAL)
    if pedido.estado == 'PARCIAL':
        items = pedido.items.filter(estado__in=['BACK_ORDER', 'PARCIAL'])
    else:
        items = pedido.items.filter(estado__in=['PENDIENTE', 'BACK_ORDER', 'PARCIAL'])

    # Consultar stock en DBISAM
    stock_info = {}
    try:
        dbisam = PedidosDBISAM()
        codigos = [item.codigo for item in items]
        stock_info = dbisam.consultar_stock_multiple(codigos, deposito=DEPOSITO_ALMACEN)
    except Exception as e:
        messages.warning(request, f'No se pudo consultar el stock: {e}')

    if request.method == 'POST':
        accion = request.POST.get('accion', 'despachar')

        if accion == 'guardar':
            pedido.estado = 'EN_PREPARACION'
            pedido.save()
            for item in items:
                cantidad = request.POST.get(f'cantidad_{item.id}', '0')
                try:
                    item.cantidad_preparada = int(cantidad)
                except ValueError:
                    item.cantidad_preparada = 0
                item.save()
            messages.success(request, f'Pedido #{pedido.numero_pedido} guardado en preparación')
            return redirect('pedidos-despachar', pk=pk)

        # accion == 'despachar' → crear Despacho registrado
        # Leer cantidades de todos los items del formulario
        cantidades = {}
        for item in items:
            try:
                cantidades[item.id] = (item, int(request.POST.get(f'cantidad_{item.id}', '0')))
            except ValueError:
                cantidades[item.id] = (item, 0)

        items_a_despachar = [(item, qty) for item, qty in cantidades.values() if qty > 0]

        if not items_a_despachar:
            messages.warning(request, 'No se despacharon items')
            return redirect('pedidos-despachar', pk=pk)

        # Validar que ningún ítem supere el stock disponible en DBISAM
        excesos = [
            f"{item.descripcion or item.codigo} (enviando {qty}, stock disponible: {stock_info.get(item.codigo, 0)})"
            for item, qty in items_a_despachar
            if qty > stock_info.get(item.codigo, 0)
        ]
        if excesos:
            detalle = '; '.join(excesos)
            messages.error(
                request,
                f'No se puede despachar más del stock disponible en los siguientes ítems: {detalle}',
            )
            return redirect('pedidos-despachar', pk=pk)

        despacho = Despacho.objects.create(
            pedido=pedido,
            picker=pedido.picker or request.user,
            fecha_inicio_picking=pedido.fecha_inicio_picking,
            fecha_fin_picking=pedido.fecha_fin_picking,
            estado='PENDIENTE_APROBACION',
            fecha_despacho=timezone.now(),
        )

        ids_despachados = set()
        for item, cantidad_enviar in items_a_despachar:
            DespachoItem.objects.create(
                despacho=despacho,
                pedido_item=item,
                cantidad_despachada=cantidad_enviar,
            )
            item.cantidad_despachada = (item.cantidad_despachada or 0) + cantidad_enviar
            item.cantidad_back_order = max(0, item.cantidad_solicitada - item.cantidad_despachada)
            item.cantidad_preparada = None
            item.estado = 'DESPACHADO' if item.cantidad_back_order == 0 else 'PARCIAL'
            item.save()
            ids_despachados.add(item.id)

        # Items con cantidad 0 quedan en BACK_ORDER con su pendiente actualizado
        for item, _ in cantidades.values():
            if item.id not in ids_despachados:
                item.cantidad_back_order = item.cantidad_solicitada - (item.cantidad_despachada or 0)
                item.cantidad_preparada = None
                item.estado = 'BACK_ORDER'
                item.save()

        if not pedido.fecha_despacho:
            pedido.fecha_despacho = datetime.now()

        pedido.estado = 'EN_PREPARACION'
        pedido.save()

        messages.success(
            request,
            f'Despacho #{despacho.numero_despacho} creado — pendiente de aprobación por supervisor'
        )
        return redirect('pedidos-detalle', pk=pk)

    items_con_stock = []
    for item in items:
        cantidad_pendiente = item.cantidad_back_order if item.estado == 'PARCIAL' else item.cantidad_solicitada
        items_con_stock.append({
            'item': item,
            'stock': stock_info.get(item.codigo, 0),
            'cantidad_pendiente': cantidad_pendiente,
            'cantidad_inicial': item.cantidad_preparada if item.cantidad_preparada is not None else 0,
        })

    return render(request, 'pedidos-despachar.html', {
        'pedido': pedido,
        'items_con_stock': items_con_stock,
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def asignar_picker(request, pk):
    if request.method != 'POST':
        return redirect('pedidos-lista')
    pedido = get_object_or_404(Pedido, numero_pedido=pk)
    tiene_bo = pedido.items.filter(estado='BACK_ORDER').exists()
    if pedido.estado not in ('PENDIENTE',) and not (pedido.estado == 'PARCIAL' and tiene_bo):
        messages.warning(request, f'El pedido #{pk} no puede asignarse picker en su estado actual')
        return redirect('pedidos-lista')
    picker_id = request.POST.get('picker_id', '').strip()
    if not picker_id:
        messages.error(request, 'Debe seleccionar un picker')
        return redirect('pedidos-lista')
    from users.models import User as UserModel
    try:
        picker = UserModel.objects.get(pk=picker_id, groups__name=GROUP_PICKER, status=True)
    except UserModel.DoesNotExist:
        messages.error(request, 'El picker seleccionado no existe o no tiene el rol correspondiente')
        return redirect('pedidos-lista')
    pedido.picker = picker
    pedido.estado = 'ASIGNADO'
    pedido.fecha_asignacion = timezone.now()
    pedido.save()
    posicion = picker.pedidos_picking.filter(estado__in=['ASIGNADO', 'PICKING']).count()
    messages.success(request, f'Pedido #{pk} asignado a {picker.username} — posición {posicion} en su cola')
    return redirect('pedidos-lista')


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def desasignar_picker(request, pk):
    if request.method != 'POST':
        return redirect('pedidos-lista')
    pedido = get_object_or_404(Pedido, numero_pedido=pk)
    if pedido.estado not in ('ASIGNADO', 'PICKING', 'PARCIAL'):
        messages.warning(request, f'El pedido #{pk} no está en estado Asignado, Picking o Parcial y no puede liberarse')
        return redirect('pedidos-lista')
    picker_anterior = pedido.picker.username if pedido.picker else '—'
    pedido.picker = None
    pedido.fecha_asignacion = None
    pedido.fecha_inicio_picking = None
    pedido.fecha_fin_picking = None
    tiene_bo = pedido.items.filter(estado='BACK_ORDER').exists()
    pedido.estado = 'PARCIAL' if tiene_bo else 'PENDIENTE'
    pedido.save()
    messages.success(request, f'Pedido #{pk} liberado (picker {picker_anterior} desasignado) — estado: {"Parcial" if tiene_bo else "Pendiente"}')
    return redirect('pedidos-lista')


@login_required(login_url='/login/')
def preparar_pedido(request, pk):
    pedido = get_object_or_404(Pedido.objects.select_related('picker', 'solicitante'), numero_pedido=pk)
    es_supervisor = is_pedidos_supervisor(request.user)
    es_picker_asignado = is_pedidos_picker(request.user) and pedido.picker == request.user

    if not es_supervisor and not es_picker_asignado:
        messages.error(request, 'No tienes permiso para preparar este pedido')
        return redirect('pedidos-lista')

    if pedido.estado not in ('ASIGNADO', 'PICKING', 'EN_PREPARACION'):
        messages.warning(request, 'Este pedido no está en estado de preparación')
        return redirect('pedidos-detalle', pk=pk)

    if pedido.estado == 'ASIGNADO' and request.method == 'GET':
        otro_en_picking = Pedido.objects.filter(
            picker=pedido.picker, estado='PICKING'
        ).exclude(pk=pedido.pk).exists()
        if otro_en_picking:
            messages.warning(request, 'Ya tienes otro pedido en Picking. Finalízalo antes de iniciar este.')
            return redirect('pedidos-lista')
        pedido.estado = 'PICKING'
        pedido.fecha_inicio_picking = timezone.now()
        pedido.fecha_fin_picking = None
        pedido.save()

    items = pedido.items.filter(estado__in=['PENDIENTE', 'BACK_ORDER', 'PARCIAL'])

    stock_info = {}
    try:
        dbisam = PedidosDBISAM()
        codigos = [item.codigo for item in items]
        stock_info = dbisam.consultar_stock_multiple(codigos, deposito=DEPOSITO_ALMACEN)
    except Exception as e:
        messages.warning(request, f'No se pudo consultar el stock: {e}')

    if request.method == 'POST':
        for item in items:
            try:
                item.cantidad_preparada = int(request.POST.get(f'cantidad_{item.id}', '0'))
            except ValueError:
                item.cantidad_preparada = 0
            item.save()
        if pedido.estado == 'PICKING':
            pedido.fecha_fin_picking = timezone.now()
        pedido.estado = 'EN_PREPARACION'
        pedido.save()
        messages.success(request, f'Pedido #{pk} marcado como En Preparación')
        return redirect('pedidos-lista')

    items_con_stock = []
    for item in items:
        cantidad_pendiente = item.cantidad_back_order if item.estado == 'PARCIAL' else item.cantidad_solicitada
        items_con_stock.append({
            'item': item,
            'stock': stock_info.get(item.codigo, 0),
            'cantidad_pendiente': cantidad_pendiente,
            'cantidad_inicial': item.cantidad_preparada if item.cantidad_preparada is not None else 0,
        })

    return render(request, 'pedidos-preparar.html', {
        'pedido': pedido,
        'items_con_stock': items_con_stock,
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def confirmar_despacho(request, pk, despacho_id):
    if request.method != 'POST':
        return redirect('pedidos-detalle', pk=pk)

    pedido = get_object_or_404(Pedido, numero_pedido=pk)
    despacho = get_object_or_404(Despacho, numero_despacho=despacho_id, pedido=pedido)

    if despacho.estado != 'PENDIENTE_APROBACION':
        messages.warning(request, f'El despacho #{despacho_id} ya fue confirmado o no está pendiente de aprobación')
        if request.POST.get('next') == 'despachos-lista':
            return redirect('despachos-lista')
        return redirect('pedidos-detalle', pk=pk)

    # Correcciones de cantidad del supervisor (POST desde el detalle).
    # Campo ausente = sin cambio (p. ej. al confirmar desde la lista global).
    nuevas = {}
    for di in despacho.items.select_related('pedido_item'):
        raw = request.POST.get(f'cantidad_{di.id}')
        if raw is None:
            nuevas[di.id] = (di, di.cantidad_despachada)
            continue
        try:
            nuevas[di.id] = (di, max(0, int(raw)))
        except (TypeError, ValueError):
            nuevas[di.id] = (di, di.cantidad_despachada)

    if not any(val > 0 for _, val in nuevas.values()):
        messages.error(request, 'No puedes confirmar un despacho sin ítems. Asigna al menos una cantidad mayor a cero.')
        return redirect('pedidos-detalle', pk=pk)

    # Validar que ninguna cantidad corregida supere el stock disponible en DBISAM
    stock_info_conf: dict = {}
    try:
        codigos_conf = [
            di.pedido_item.codigo
            for di, _ in nuevas.values()
            if di.pedido_item and di.pedido_item.codigo
        ]
        if codigos_conf:
            dbisam_conf = PedidosDBISAM()
            stock_info_conf = dbisam_conf.consultar_stock_multiple(codigos_conf, deposito=DEPOSITO_ALMACEN)
    except Exception as e_stock:
        logger.warning(f'No se pudo consultar stock al confirmar despacho #{despacho_id}: {e_stock}')

    if stock_info_conf:
        excesos_conf = []
        for di, val in nuevas.values():
            if val <= 0 or not di.pedido_item:
                continue
            stock_disp = stock_info_conf.get(di.pedido_item.codigo, 0)
            if val > stock_disp:
                desc = di.pedido_item.descripcion or di.pedido_item.codigo
                excesos_conf.append(f'{desc} (confirmando {val}, stock disponible: {stock_disp})')
        if excesos_conf:
            detalle_conf = '; '.join(excesos_conf)
            messages.error(
                request,
                f'No se puede confirmar: la cantidad supera el stock disponible en los siguientes ítems: {detalle_conf}',
            )
            return redirect('pedidos-detalle', pk=pk)

    for di, val in nuevas.values():
        delta = val - di.cantidad_despachada
        pi = di.pedido_item
        if delta != 0 and pi:
            pi.cantidad_despachada = max(0, (pi.cantidad_despachada or 0) + delta)
            pi.cantidad_back_order = max(0, pi.cantidad_solicitada - pi.cantidad_despachada)
            if pi.cantidad_back_order == 0:
                pi.estado = 'DESPACHADO'
            elif pi.cantidad_despachada > 0:
                pi.estado = 'PARCIAL'
            else:
                pi.estado = 'BACK_ORDER'
            pi.save()
        if val == 0:
            di.delete()        # cantidad 0 → quitar ítem del despacho
        elif delta != 0:
            di.cantidad_despachada = val
            di.save()

    despacho.despachador = request.user
    despacho.estado = 'ENVIADO'
    despacho.save()

    quedan_sin_despachar = pedido.items.filter(estado__in=['PENDIENTE', 'BACK_ORDER', 'PARCIAL']).exists()
    pedido.estado = 'PARCIAL' if quedan_sin_despachar else 'DESPACHADO'
    pedido.despachador = request.user
    pedido.save()

    if pedido.estado == 'DESPACHADO':
        notificar_despacho(pedido)
    elif pedido.estado == 'PARCIAL':
        notificar_despacho_parcial(pedido)

    items_dbisam = [
        {'codigo': di.pedido_item.codigo, 'cantidad': di.cantidad_despachada}
        for di in despacho.items.select_related('pedido_item')
        if di.pedido_item and di.cantidad_despachada > 0
    ]
    try:
        deposito_transito = ConfiguracionPedidos.load().deposito_transito
        dbisam = PedidosDBISAM()
        dbisam.insertar_traslado_despacho(
            despacho.numero_despacho,
            deposito_transito,
            items_dbisam,
            responsable=request.user.username,
            proposito=pedido.condicion,
            numero_pedido=pedido.numero_pedido,
        )
        despacho.traslado_a2_registrado = True
        despacho.save(update_fields=['traslado_a2_registrado'])
        # Snapshot: la recepción debe salir del mismo depósito donde entró el
        # despacho, aunque la configuración cambie entre ambos pasos.
        pedido.deposito_transito = deposito_transito
        pedido.save(update_fields=['deposito_transito'])
    except Exception as e:
        logger.error(f'Error al registrar traslado del despacho #{despacho_id} en a2: {e}')
        messages.warning(
            request,
            f'Despacho confirmado, pero ocurrió un error al registrar el traslado en a2 — se recomienda realizarlo manualmente: {e}'
        )

    messages.success(request, f'Despacho #{despacho_id} confirmado y enviado')
    next_url = request.POST.get('next', '')
    if next_url == 'despachos-lista':
        return redirect('despachos-lista')
    return redirect('pedidos-detalle', pk=pk)


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def lista_despachos(request):
    despachos = Despacho.objects.select_related(
        'pedido__solicitante', 'despachador', 'picker'
    ).order_by('-fecha_despacho')

    estado_filter = request.GET.get('estado', '')
    if estado_filter:
        despachos = despachos.filter(estado=estado_filter)

    request.session['pedidos_volver_url'] = request.get_full_path()
    return render(request, 'despachos-lista.html', {
        'despachos': despachos,
        'estado_filter': estado_filter,
        'estados': Despacho.ESTADO_CHOICES,
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def anular_despacho(request, despacho_id):
    despacho = get_object_or_404(Despacho, numero_despacho=despacho_id)
    if request.method != 'POST':
        return redirect('pedidos-detalle', pk=despacho.pedido_id)
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'Debes indicar un motivo para anular el despacho')
        return redirect('pedidos-detalle', pk=despacho.pedido_id)

    pedido_liberado = False
    with transaction.atomic():
        despacho = Despacho.objects.select_for_update().get(numero_despacho=despacho_id)
        if despacho.estado == 'ANULADO':
            messages.warning(request, 'Este despacho ya está anulado')
            return redirect('pedidos-detalle', pk=despacho.pedido_id)
        if despacho.estado in ('RECIBIDO', 'PARCIAL'):
            messages.error(request, 'No se puede anular un despacho que ya fue recibido')
            return redirect('pedidos-detalle', pk=despacho.pedido_id)
        pedido = Pedido.objects.select_for_update().get(pk=despacho.pedido_id)

        # Revertir la contribución de este despacho al pedido original.
        for di in despacho.items.select_related('pedido_item'):
            pi = di.pedido_item
            if not pi:
                continue
            pi.cantidad_despachada = max(0, (pi.cantidad_despachada or 0) - di.cantidad_despachada)
            pi.cantidad_back_order = max(0, pi.cantidad_solicitada - pi.cantidad_despachada)
            recibida = pi.cantidad_recibida or 0
            if pi.cantidad_solicitada > 0 and recibida >= pi.cantidad_solicitada:
                pi.estado = 'RECIBIDO'
            elif pi.cantidad_despachada == 0 and recibida == 0:
                pi.estado = 'PENDIENTE'
            elif pi.cantidad_back_order == 0:
                pi.estado = 'DESPACHADO'
            elif pi.cantidad_despachada > 0:
                pi.estado = 'PARCIAL'
            else:
                pi.estado = 'BACK_ORDER'
            pi.save()

        despacho.estado_anterior = despacho.estado
        despacho.estado = 'ANULADO'
        despacho.anulado_por = request.user
        despacho.fecha_anulacion = timezone.now()
        despacho.motivo_anulacion = motivo
        despacho.save()

        # Recalcular el estado del pedido a partir de sus ítems.
        estados = list(pedido.items.values_list('estado', flat=True))
        if estados:
            if all(e == 'PENDIENTE' for e in estados):
                pedido.estado = 'PENDIENTE'
                pedido.fecha_despacho = None
            elif all(e == 'RECIBIDO' for e in estados):
                pedido.estado = 'RECIBIDO'
            elif all(e in ('DESPACHADO', 'RECIBIDO') for e in estados):
                pedido.estado = 'DESPACHADO'
            else:
                pedido.estado = 'PARCIAL'
            if pedido.estado == 'PARCIAL':
                # Los items revertidos deben quedar en BACK_ORDER: el gate de
                # asignar_picker y la UI solo reasignan PARCIAL con BACK_ORDER.
                pedido.items.filter(estado='PENDIENTE').update(estado='BACK_ORDER')
            if pedido.estado in ('PENDIENTE', 'PARCIAL'):
                # Liberar al picker para que el pedido pueda reasignarse y
                # volver al ciclo de picking (patrón desasignar_picker).
                pedido.picker = None
                pedido.fecha_asignacion = None
                pedido_liberado = True
            pedido.save()

    logger.info(
        'Despacho #%s anulado por %s. Motivo: %s',
        despacho.numero_despacho, request.user.username, motivo,
    )
    if pedido_liberado:
        messages.success(
            request,
            f'Despacho #{despacho.numero_despacho} anulado — '
            f'pedido #{pedido.numero_pedido} liberado para asignar picker',
        )
    else:
        messages.success(request, f'Despacho #{despacho.numero_despacho} anulado')
    return redirect('pedidos-detalle', pk=pedido.numero_pedido)


@login_required(login_url='/login/')
def verificar_autorizacion_despacho(request):
    """AJAX: valida credenciales de supervisor/admin para autorizar incidencias especiales."""
    if request.method != 'POST':
        return JsonResponse({'ok': False})
    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '')
    auth_user = django_authenticate(request, username=username, password=password)
    if auth_user and (auth_user.is_superuser or is_pedidos_supervisor(auth_user)):
        request.session['despacho_auth_user_id'] = auth_user.id
        return JsonResponse({'ok': True, 'nombre': auth_user.username})
    request.session.pop('despacho_auth_user_id', None)
    return JsonResponse({'ok': False, 'error': 'Credenciales inválidas o usuario sin permisos de autorización'})


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_receptor, login_url='dashboard')
def recibir_despacho(request, pk, despacho_id):
    pedido = get_object_or_404(Pedido, numero_pedido=pk)

    if not puede_recibir_pedido(request.user, pedido):
        messages.error(request, 'No tienes permiso para recibir este pedido')
        return redirect('pedidos-lista')

    despacho = get_object_or_404(Despacho, numero_despacho=despacho_id, pedido=pedido)

    if despacho.estado != 'ENVIADO':
        messages.warning(request, 'Este despacho ya fue recibido o no está disponible para recepción')
        return redirect('pedidos-detalle', pk=pk)

    despacho_items = list(despacho.items.select_related('pedido_item'))

    if request.method == 'POST':
        # ── Verificar si hay incidencias especiales ──────────────────────────
        tiene_producto_erroneo = any(
            request.POST.get(f'tipo_incidencia_{di.id}') == 'PRODUCTO_ERRONEO'
            for di in despacho_items
        )
        productos_extra_raw = request.POST.get('productos_extra', '[]').strip()
        try:
            productos_extra_parsed = json.loads(productos_extra_raw)
            tiene_sku_extra = bool(productos_extra_parsed)
        except (json.JSONDecodeError, ValueError):
            productos_extra_parsed = []
            tiene_sku_extra = False

        # ── Bloquear extras cuyo SKU ya existe en el pedido o viene repetido ─
        if tiene_sku_extra:
            codigos_pedido = {
                c.strip().upper() for c in pedido.items.values_list('codigo', flat=True)
            }
            ya_en_pedido, repetidos, vistos = [], [], set()
            for extra in productos_extra_parsed:
                codigo = str(extra.get('codigo', '')).strip()
                if not codigo:
                    continue
                codigo_norm = codigo.upper()
                if codigo_norm in codigos_pedido:
                    ya_en_pedido.append(codigo)
                elif codigo_norm in vistos:
                    repetidos.append(codigo)
                vistos.add(codigo_norm)
            if ya_en_pedido:
                messages.error(
                    request,
                    f'No se puede agregar como producto nuevo: {", ".join(ya_en_pedido)} '
                    'ya existe en el pedido. Registra la cantidad de más en la línea '
                    'correspondiente del despacho.'
                )
                return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)
            if repetidos:
                messages.error(
                    request,
                    f'Producto repetido en la lista de adicionales: {", ".join(repetidos)}. '
                    'Agrega el código una sola vez con la cantidad total.'
                )
                return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)

        auth_user = None
        if tiene_producto_erroneo or tiene_sku_extra:
            auth_user_id = request.session.get('despacho_auth_user_id')
            try:
                from users.models import User as UserModel
                auth_user = UserModel.objects.get(pk=auth_user_id)
                if not (auth_user.is_superuser or is_pedidos_supervisor(auth_user)):
                    raise ValueError('Sin permisos')
            except Exception:
                messages.error(
                    request,
                    'Se requiere autorización de un supervisor o administrador para registrar incidencias especiales.'
                )
                return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)
            request.session.pop('despacho_auth_user_id', None)

        # ── Validar que se reciba al menos 1 unidad ──────────────────────────
        total_cant_recibida = 0
        for di in despacho_items:
            if request.POST.get(f'tipo_incidencia_{di.id}', '') == 'PRODUCTO_ERRONEO':
                continue
            try:
                total_cant_recibida += max(int(request.POST.get(f'recibido_{di.id}', '0') or '0'), 0)
            except (ValueError, TypeError):
                pass
        for extra in productos_extra_parsed:
            try:
                cant_extra = int(extra.get('cantidad', 0))
            except (ValueError, TypeError):
                cant_extra = 0
            if str(extra.get('codigo', '')).strip() and cant_extra > 0:
                total_cant_recibida += cant_extra
        if total_cant_recibida == 0:
            messages.error(request, 'Debe ingresar al menos una cantidad mayor a 0 para confirmar la recepción.')
            return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)

        # ── Validar fotos obligatorias en incidencias ────────────────────────
        errores_foto = []
        for di in despacho_items:
            tipo_inc_pre = request.POST.get(f'tipo_incidencia_{di.id}', '')
            try:
                cant_pre = int(request.POST.get(f'recibido_{di.id}', '0') or '0')
            except ValueError:
                cant_pre = 0
            if tipo_inc_pre == 'PRODUCTO_ERRONEO':
                if not request.FILES.get(f'foto_{di.id}'):
                    codigo = di.pedido_item.codigo if di.pedido_item else '—'
                    errores_foto.append(f'{codigo} (Cambio SKU)')
        if tiene_sku_extra and not request.FILES.get('foto_extras'):
            errores_foto.append('productos adicionales (SKU no contemplado)')
        if errores_foto:
            messages.error(
                request,
                'Se requiere foto de evidencia para: ' + ', '.join(errores_foto),
            )
            return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)

        foto_extras = request.FILES.get('foto_extras')
        items_traslado = []
        hay_incidencia = False

        # ── Procesar items normales y con producto erróneo ───────────────────
        try:
            with transaction.atomic():
                for di in despacho_items:
                    try:
                        cantidad_recibida = int(request.POST.get(f'recibido_{di.id}', '0'))
                    except ValueError:
                        cantidad_recibida = 0
                    observacion = request.POST.get(f'observacion_{di.id}', '')
                    tipo_inc = request.POST.get(f'tipo_incidencia_{di.id}', '')

                    di.cantidad_recibida = cantidad_recibida
                    di.observacion = observacion

                    if tipo_inc == 'PRODUCTO_ERRONEO':
                        di.tipo_incidencia = 'PRODUCTO_ERRONEO'
                        di.codigo_real = request.POST.get(f'codigo_real_{di.id}', '').strip()
                        di.descripcion_real = request.POST.get(f'descripcion_real_{di.id}', '').strip()
                        di.autorizado_por = auth_user
                        di.foto_incidencia = request.FILES.get(f'foto_{di.id}')
                        hay_incidencia = True
                    elif cantidad_recibida < di.cantidad_despachada:
                        di.tipo_incidencia = 'CANTIDAD_MENOR'
                        hay_incidencia = True
                    elif cantidad_recibida > di.cantidad_despachada:
                        di.tipo_incidencia = 'CANTIDAD_MAYOR'
                        hay_incidencia = True
                    di.save()

                    item = di.pedido_item
                    item.cantidad_recibida = (item.cantidad_recibida or 0) + cantidad_recibida
                    item.observacion = observacion

                    if tipo_inc == 'PRODUCTO_ERRONEO':
                        item.estado = 'INCIDENCIA'
                    elif item.cantidad_recibida >= item.cantidad_solicitada:
                        item.estado = 'RECIBIDO'
                    elif item.cantidad_back_order > 0:
                        item.estado = 'BACK_ORDER'
                    else:
                        tiene_otros_enviados = DespachoItem.objects.filter(
                            pedido_item=item, despacho__estado='ENVIADO',
                        ).exclude(despacho=despacho).exists()
                        if tiene_otros_enviados:
                            item.estado = 'DESPACHADO'
                        elif item.cantidad_recibida < item.cantidad_despachada:
                            item.estado = 'INCIDENCIA'
                        else:
                            item.estado = 'RECIBIDO'
                    item.save()

                    if cantidad_recibida > 0:
                        codigo_traslado = di.codigo_real if tipo_inc == 'PRODUCTO_ERRONEO' and di.codigo_real else item.codigo
                        items_traslado.append({'codigo': codigo_traslado, 'cantidad': cantidad_recibida})

                # ── Procesar SKUs no contemplados ────────────────────────────────────
                if tiene_sku_extra:
                    extras = productos_extra_parsed

                    for extra in extras:
                        codigo = str(extra.get('codigo', '')).strip()
                        descripcion = str(extra.get('descripcion', '')).strip()
                        try:
                            cantidad = int(extra.get('cantidad', 0))
                        except (ValueError, TypeError):
                            cantidad = 0

                        if not codigo or cantidad <= 0:
                            continue

                        # Crear PedidoItem ficticio para trazabilidad
                        nuevo_item = PedidoItem.objects.create(
                            pedido=pedido,
                            codigo=codigo,
                            descripcion=descripcion,
                            cantidad_solicitada=0,
                            cantidad_despachada=cantidad,
                            cantidad_recibida=cantidad,
                            estado='INCIDENCIA',
                            observacion='SKU no contemplado en el pedido original',
                        )
                        di_extra = DespachoItem(
                            despacho=despacho,
                            pedido_item=nuevo_item,
                            cantidad_despachada=cantidad,
                            cantidad_recibida=cantidad,
                            tipo_incidencia='SKU_NO_CONTEMPLADO',
                            autorizado_por=auth_user,
                        )
                        if foto_extras:
                            di_extra.foto_incidencia = foto_extras
                        di_extra.save()
                        items_traslado.append({'codigo': codigo, 'cantidad': cantidad})
                        hay_incidencia = True

                despacho.receptor = request.user
                despacho.fecha_recepcion = datetime.now()
                despacho.estado = 'PARCIAL' if hay_incidencia else 'RECIBIDO'
                despacho.save()

                estados_items = list(pedido.items.values_list('estado', flat=True))
                if all(e == 'RECIBIDO' for e in estados_items):
                    pedido.estado = 'RECIBIDO'
                    pedido.fecha_recepcion = datetime.now()
                elif any(e in ('PENDIENTE', 'BACK_ORDER', 'PARCIAL', 'DESPACHADO') for e in estados_items):
                    pedido.estado = 'PARCIAL'
                pedido.save()

                if items_traslado:
                    if not pedido.deposito_codigo:
                        raise ValueError(
                            f'El pedido #{pedido.numero_pedido} no tiene depósito destino configurado '
                            f'en a2 — no se puede registrar el traslado de recepción. '
                            f'Contacta a un supervisor para configurarlo.'
                        )
                    # Origen del traslado: el snapshot grabado al despachar;
                    # fallback a la config para pedidos antiguos sin snapshot.
                    deposito_transito = (
                        pedido.deposito_transito
                        or ConfiguracionPedidos.load().deposito_transito
                    )
                    dbisam = PedidosDBISAM()
                    dbisam.insertar_traslado_recepcion(
                        pedido.numero_pedido,
                        deposito_transito,
                        pedido.deposito_codigo,
                        items_traslado,
                        responsable=request.user.username,
                        proposito=pedido.condicion,
                        numero_despacho=despacho.numero_despacho,
                    )
        except ValueError as e:
            logger.error(f'Recepción del despacho #{despacho_id} bloqueada: {e}')
            messages.error(request, str(e))
            return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)
        except Exception as e:
            logger.error(f'Error al insertar traslado DBISAM para despacho #{despacho_id}: {e}')
            messages.error(
                request,
                'No se pudo registrar la recepción: ocurrió un error al conectar con a2. '
                'No se guardó ningún cambio — intenta nuevamente en unos minutos.'
            )
            return redirect('pedidos-recibir-despacho', pk=pk, despacho_id=despacho_id)

        messages.success(request, f'Recepción del Despacho #{despacho_id} registrada correctamente')
        return redirect('pedidos-detalle', pk=pk)

    return render(request, 'pedidos-recibir-despacho.html', {
        'pedido': pedido,
        'despacho': despacho,
        'despacho_items': despacho_items,
        'ver_despachado': is_pedidos_supervisor(request.user) or is_pedidos_almacen(request.user),
    })


@login_required(login_url='/login/')
def exportar_despacho_pdf(request, pk, despacho_id):
    if not (request.user.is_superuser or is_pedidos_almacen(request.user) or is_pedidos_supervisor(request.user)):
        messages.error(request, 'No tienes permiso para imprimir este despacho')
        return redirect('pedidos-detalle', pk=pk)

    pedido = get_object_or_404(Pedido, numero_pedido=pk)
    despacho = get_object_or_404(Despacho, numero_despacho=despacho_id, pedido=pedido)
    despacho_items = despacho.items.select_related('pedido_item')

    from formatos.contratos import datos_despacho
    from formatos.generacion import generar_pdf as generar_pdf_formato
    pdf_bytes = generar_pdf_formato('despacho', datos_despacho(despacho, despacho_items))
    if pdf_bytes is None:
        pdf_bytes = generar_despacho_pdf(despacho, despacho_items)
    nombre_archivo = f"despacho_{despacho_id}_pedido_{pk}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response


@login_required(login_url='/login/')
def reintentar_traslado_despacho(request, pk, despacho_id):
    """
    Reintenta la inserción del traslado en a2 para un despacho cuyo registro falló.
    Solo accesible para superusuarios. Solo POST.

    Protección anti-duplicado doble:
    1. Flag traslado_a2_registrado en el modelo.
    2. Verificación de existencia en SOPERACIONINV antes de insertar.
    """
    if not request.user.is_superuser:
        messages.error(request, 'No tienes permiso para ejecutar esta acción')
        return redirect('pedidos-detalle', pk=pk)

    if request.method != 'POST':
        return redirect('pedidos-detalle', pk=pk)

    pedido = get_object_or_404(Pedido, numero_pedido=pk)
    despacho = get_object_or_404(Despacho, numero_despacho=despacho_id, pedido=pedido)

    # El botón solo debe aparecer cuando el flag es False, pero validamos en servidor también
    if despacho.traslado_a2_registrado:
        messages.info(request, f'El traslado del despacho #{despacho_id} ya fue registrado en a2')
        return redirect('pedidos-detalle', pk=pk)

    if despacho.estado in ('PENDIENTE_APROBACION', 'PREPARANDO'):
        messages.warning(request, f'El despacho #{despacho_id} aún no ha sido confirmado')
        return redirect('pedidos-detalle', pk=pk)

    # Verificación de seguridad contra a2 para evitar duplicados (despachos históricos)
    # Snapshot del pedido si existe; fallback a la config para pedidos antiguos.
    deposito_transito = (
        pedido.deposito_transito or ConfiguracionPedidos.load().deposito_transito
    )
    try:
        dbisam = PedidosDBISAM()
        if dbisam.existe_traslado_despacho(despacho.numero_despacho, deposito_transito):
            despacho.traslado_a2_registrado = True
            despacho.save(update_fields=['traslado_a2_registrado'])
            messages.warning(
                request,
                f'El traslado del despacho #{despacho_id} ya existía en a2 — se marcó como registrado sin duplicar.',
            )
            return redirect('pedidos-detalle', pk=pk)
    except Exception as e:
        logger.error(f'Error al verificar existencia del traslado #{despacho_id} en a2: {e}')
        messages.error(request, f'No se pudo verificar el estado del traslado en a2: {e}')
        return redirect('pedidos-detalle', pk=pk)

    # Reconstruir items idéntico a confirmar_despacho
    items_dbisam = [
        {'codigo': di.pedido_item.codigo, 'cantidad': di.cantidad_despachada}
        for di in despacho.items.select_related('pedido_item')
        if di.pedido_item and di.cantidad_despachada > 0
    ]

    if not items_dbisam:
        messages.error(request, f'El despacho #{despacho_id} no tiene ítems válidos para registrar en a2')
        return redirect('pedidos-detalle', pk=pk)

    try:
        dbisam.insertar_traslado_despacho(
            despacho.numero_despacho,
            deposito_transito,
            items_dbisam,
            responsable=request.user.username,
            proposito=pedido.condicion,
            numero_pedido=pedido.numero_pedido,
        )
        despacho.traslado_a2_registrado = True
        despacho.save(update_fields=['traslado_a2_registrado'])
        pedido.deposito_transito = deposito_transito
        pedido.save(update_fields=['deposito_transito'])
        messages.success(request, f'Traslado del despacho #{despacho_id} registrado correctamente en a2')
    except Exception as e:
        logger.error(f'Error al reintentar traslado del despacho #{despacho_id} en a2: {e}')
        messages.error(request, f'Error al registrar el traslado en a2: {e}')

    return redirect('pedidos-detalle', pk=pk)


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_any, login_url='dashboard')
def buscar_producto(request):
    query = request.GET.get('q', '').strip()
    tipo = request.GET.get('tipo', 'codigo')
    categoria = request.GET.get('categoria', '').strip()
    solo_existencia = request.GET.get('solo_existencia') == '1'

    if not categoria:
        return HttpResponse('<p class="text-warning">Seleccione una categoria antes de buscar</p>')

    if len(query) < 2:
        return HttpResponse('')

    try:
        dbisam = PedidosDBISAM()
        resultados_raw = dbisam.buscar_en_categoria(
            categoria, query, tipo, solo_existencia=solo_existencia)
    except Exception:
        resultados_raw = []

    # Enriquecer con ubicaciones internas (Postgres)
    from ubicaciones.models import ProductoUbicacion
    codigos = [r[0] for r in resultados_raw]
    ubicaciones_map: dict = {}
    if codigos:
        try:
            qs = (
                ProductoUbicacion.objects
                .filter(
                    codigo_producto__in=codigos,
                    ubicacion__activo=True,
                    ubicacion__nivel__activo=True,
                    ubicacion__nivel__rack__activo=True,
                )
                .select_related('ubicacion__nivel__rack')
            )
            for pu in qs:
                ubicaciones_map.setdefault(pu.codigo_producto, []).append({
                    'codigo': pu.ubicacion.codigo_completo,
                    'tipo_nivel': pu.ubicacion.nivel.tipo,
                    'tipo_nivel_display': pu.ubicacion.nivel.get_tipo_display(),
                })
        except Exception:
            logger.exception("Error al consultar ubicaciones internas en buscar_producto")

    resultados = [
        {
            'codigo': r[0],
            'descripcion': r[1],
            'referencia': r[2],
            'puesto': r[3],
            'existencia': r[4],
            'ref_proveedor': r[5],
            'ubicaciones_internas': ubicaciones_map.get(r[0], []),
        }
        for r in resultados_raw
    ]

    return render(request, 'pedidos-buscar-producto.html', {'resultados': resultados})


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def reporte_pedidos(request):
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    categoria_filtro = request.GET.get('categoria', '')
    condicion_filtro = request.GET.get('condicion', '')

    pedidos = Pedido.objects.exclude(estado='ANULADO')

    if fecha_inicio:
        pedidos = pedidos.filter(fecha_creacion__date__gte=fecha_inicio)
    if fecha_fin:
        pedidos = pedidos.filter(fecha_creacion__date__lte=fecha_fin)
    if categoria_filtro:
        pedidos = pedidos.filter(categoria=categoria_filtro)
    if condicion_filtro:
        pedidos = pedidos.filter(condicion=condicion_filtro)

    total_pedidos = pedidos.count()

    anulados_qs = Pedido.objects.filter(estado='ANULADO')
    if fecha_inicio:
        anulados_qs = anulados_qs.filter(fecha_creacion__date__gte=fecha_inicio)
    if fecha_fin:
        anulados_qs = anulados_qs.filter(fecha_creacion__date__lte=fecha_fin)
    total_anulados = anulados_qs.count()

    totales_items = PedidoItem.objects.filter(pedido__in=pedidos).aggregate(
        total_solicitado=Sum('cantidad_solicitada'),
        total_despachado=Sum('cantidad_despachada'),
        total_recibido=Sum('cantidad_recibida'),
    )

    tiempo_horas = None
    tiempo_minutos = None
    pedidos_con_despacho = pedidos.filter(fecha_despacho__isnull=False)
    if pedidos_con_despacho.exists():
        segundos_list = [
            _segundos_laborales(p.fecha_creacion, p.fecha_despacho)
            for p in pedidos_con_despacho.only('fecha_creacion', 'fecha_despacho')
        ]
        if segundos_list:
            promedio_seg = sum(segundos_list) / len(segundos_list)
            tiempo_horas = int(promedio_seg) // 3600
            tiempo_minutos = (int(promedio_seg) % 3600) // 60

    categoria_top = (
        pedidos.exclude(categoria='')
        .values('categoria', 'categoria_nombre')
        .annotate(total=Count('numero_pedido'))
        .order_by('-total')
        .first()
    )

    condicion_top = (
        pedidos.exclude(condicion='')
        .values('condicion')
        .annotate(total=Count('numero_pedido'))
        .order_by('-total')
        .first()
    )

    por_estado = (
        pedidos.values('estado')
        .annotate(total=Count('numero_pedido'))
        .order_by('-total')
    )

    por_categoria = (
        pedidos.exclude(categoria='')
        .values('categoria', 'categoria_nombre')
        .annotate(total=Count('numero_pedido'))
        .order_by('-total')[:10]
    )

    por_condicion = (
        pedidos.exclude(condicion='')
        .values('condicion')
        .annotate(total=Count('numero_pedido'))
        .order_by('-total')
    )

    items_qs = PedidoItem.objects.filter(pedido__in=pedidos)
    total_items_incidencia = items_qs.filter(estado='INCIDENCIA').count()
    pedidos_con_incidencia = pedidos.filter(items__estado='INCIDENCIA').distinct().count()
    pct_incidencias = round(pedidos_con_incidencia / total_pedidos * 100, 1) if total_pedidos else 0

    categorias_disponibles = (
        Pedido.objects.exclude(categoria='')
        .values('categoria')
        .annotate(nombre=Max('categoria_nombre'))
        .order_by('categoria')
    )

    return render(request, 'pedidos-reporte.html', {
        'total_pedidos': total_pedidos,
        'total_anulados': total_anulados,
        'total_solicitado': totales_items['total_solicitado'] or 0,
        'total_despachado': totales_items['total_despachado'] or 0,
        'total_recibido': totales_items['total_recibido'] or 0,
        'total_items_incidencia': total_items_incidencia,
        'pedidos_con_incidencia': pedidos_con_incidencia,
        'pct_incidencias': pct_incidencias,
        'tiempo_horas': tiempo_horas,
        'tiempo_minutos': tiempo_minutos,
        'categoria_top': categoria_top,
        'condicion_top': condicion_top,
        'por_estado': por_estado,
        'por_categoria': por_categoria,
        'por_condicion': por_condicion,
        'categorias_disponibles': categorias_disponibles,
        'condiciones': Pedido.CONDICION_CHOICES,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'categoria_filtro': categoria_filtro,
        'condicion_filtro': condicion_filtro,
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def exportar_reporte_pdf(request):
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    categoria_filtro = request.GET.get('categoria', '')
    condicion_filtro = request.GET.get('condicion', '')

    pedidos = Pedido.objects.exclude(estado='ANULADO')
    if fecha_inicio:
        pedidos = pedidos.filter(fecha_creacion__date__gte=fecha_inicio)
    if fecha_fin:
        pedidos = pedidos.filter(fecha_creacion__date__lte=fecha_fin)
    if categoria_filtro:
        pedidos = pedidos.filter(categoria=categoria_filtro)
    if condicion_filtro:
        pedidos = pedidos.filter(condicion=condicion_filtro)

    total_pedidos = pedidos.count()
    totales_items = PedidoItem.objects.filter(pedido__in=pedidos).aggregate(
        total_solicitado=Sum('cantidad_solicitada'),
        total_despachado=Sum('cantidad_despachada'),
        total_recibido=Sum('cantidad_recibida'),
    )

    tiempo_horas = None
    tiempo_minutos = None
    pedidos_con_despacho = pedidos.filter(fecha_despacho__isnull=False)
    if pedidos_con_despacho.exists():
        segundos_list = [
            _segundos_laborales(p.fecha_creacion, p.fecha_despacho)
            for p in pedidos_con_despacho.only('fecha_creacion', 'fecha_despacho')
        ]
        if segundos_list:
            promedio_seg = sum(segundos_list) / len(segundos_list)
            tiempo_horas = int(promedio_seg) // 3600
            tiempo_minutos = (int(promedio_seg) % 3600) // 60

    items_qs_pdf = PedidoItem.objects.filter(pedido__in=pedidos)
    total_items_incidencia = items_qs_pdf.filter(estado='INCIDENCIA').count()
    pedidos_con_incidencia = pedidos.filter(items__estado='INCIDENCIA').distinct().count()
    pct_incidencias = round(pedidos_con_incidencia / total_pedidos * 100, 1) if total_pedidos else 0

    ctx = {
        'total_pedidos': total_pedidos,
        'total_solicitado': totales_items['total_solicitado'] or 0,
        'total_despachado': totales_items['total_despachado'] or 0,
        'total_recibido': totales_items['total_recibido'] or 0,
        'total_items_incidencia': total_items_incidencia,
        'pedidos_con_incidencia': pedidos_con_incidencia,
        'pct_incidencias': pct_incidencias,
        'tiempo_horas': tiempo_horas,
        'tiempo_minutos': tiempo_minutos,
        'categoria_top': (
            pedidos.exclude(categoria='')
            .values('categoria', 'categoria_nombre').annotate(total=Count('numero_pedido'))
            .order_by('-total').first()
        ),
        'condicion_top': (
            pedidos.exclude(condicion='')
            .values('condicion').annotate(total=Count('numero_pedido'))
            .order_by('-total').first()
        ),
        'por_estado': list(
            pedidos.values('estado').annotate(total=Count('numero_pedido')).order_by('-total')
        ),
        'por_condicion': list(
            pedidos.exclude(condicion='').values('condicion')
            .annotate(total=Count('numero_pedido')).order_by('-total')
        ),
        'por_categoria': list(
            pedidos.exclude(categoria='').values('categoria', 'categoria_nombre')
            .annotate(total=Count('numero_pedido')).order_by('-total')[:10]
        ),
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'categoria_filtro': categoria_filtro,
        'condicion_filtro': condicion_filtro,
    }

    pdf_bytes = generar_reporte_pedidos_pdf(ctx)
    nombre_archivo = f"reporte_pedidos_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response


def _estadisticas_pickers(fecha_inicio: str, fecha_fin: str, picker_id: str) -> dict:
    """
    Estadísticas de picking agregadas por picker sobre Despacho/DespachoItem.

    Solo cuenta despachos cuyo picker pertenece al grupo Pedidos Picker
    (los creados sin picker asignado quedan atribuidos al despachador y
    se excluyen). Los despachos ANULADOS se reportan en columna aparte
    y quedan fuera de las métricas netas.

    Args:
        fecha_inicio: Fecha 'YYYY-MM-DD' o '' (sin filtro inferior).
        fecha_fin: Fecha 'YYYY-MM-DD' o '' (sin filtro superior).
        picker_id: PK del picker a filtrar o '' (todos).

    Returns:
        {'stats': [dict por picker], 'totales': dict global}
    """
    no_anulado = ~Q(estado='ANULADO')
    qs = Despacho.objects.filter(
        picker__isnull=False, picker__groups__name=GROUP_PICKER,
    ).annotate(
        # Despachos legacy creados por la API quedaron con fecha_despacho null
        fecha_ref=Coalesce('fecha_despacho', 'pedido__fecha_despacho', 'pedido__fecha_creacion'),
    )
    for valor, lookup in ((fecha_inicio, 'fecha_ref__date__gte'), (fecha_fin, 'fecha_ref__date__lte')):
        if valor:
            try:
                qs = qs.filter(**{lookup: datetime.strptime(valor, '%Y-%m-%d').date()})
            except ValueError:
                pass
    if picker_id:
        try:
            qs = qs.filter(picker_id=int(picker_id))
        except ValueError:
            pass

    stats = list(
        qs.values('picker_id', 'picker__username')
        .annotate(
            total_despachos=Count('numero_despacho', filter=no_anulado, distinct=True),
            total_pedidos=Count('pedido_id', filter=no_anulado, distinct=True),
            total_unidades=Coalesce(Sum('items__cantidad_despachada', filter=no_anulado), 0),
            total_lineas=Count('items__id', filter=no_anulado, distinct=True),
            total_productos=Count('items__pedido_item__codigo', filter=no_anulado, distinct=True),
            despachos_anulados=Count('numero_despacho', filter=Q(estado='ANULADO'), distinct=True),
        )
        .order_by('-total_unidades', 'picker__username')
    )
    totales = {
        'despachos': sum(s['total_despachos'] for s in stats),
        # Query aparte: un pedido tocado por varios pickers cuenta una sola vez
        'pedidos': qs.filter(no_anulado).values('pedido_id').distinct().count(),
        'unidades': sum(s['total_unidades'] for s in stats),
        'lineas': sum(s['total_lineas'] for s in stats),
        'anulados': sum(s['despachos_anulados'] for s in stats),
    }
    return {'stats': stats, 'totales': totales}


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def reporte_pickers(request):
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    picker_filtro = request.GET.get('picker', '')

    ctx = _estadisticas_pickers(fecha_inicio, fecha_fin, picker_filtro)
    ctx.update({
        'pickers_disponibles': _pickers_disponibles(),
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'picker_filtro': picker_filtro,
    })
    return render(request, 'pedidos-reporte-pickers.html', ctx)


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def exportar_reporte_pickers_pdf(request):
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    picker_filtro = request.GET.get('picker', '')

    ctx = _estadisticas_pickers(fecha_inicio, fecha_fin, picker_filtro)
    ctx.update({'fecha_inicio': fecha_inicio, 'fecha_fin': fecha_fin})
    if picker_filtro.isdigit():
        from users.models import User as UserModel
        picker = UserModel.objects.filter(pk=picker_filtro).first()
        ctx['picker_filtro_nombre'] = picker.username if picker else ''

    pdf_bytes = generar_reporte_pickers_pdf(ctx)
    nombre_archivo = f"estadisticas_pickers_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_any, login_url='dashboard')
def exportar_pedido_pdf(request, pk):
    pedido = get_object_or_404(Pedido.objects.select_related('solicitante', 'despachador'), numero_pedido=pk)

    if _solo_tienda(request.user) and pedido.solicitante != request.user:
        messages.error(request, 'No tienes permiso para descargar este pedido')
        return redirect('pedidos-lista')

    vista = request.GET.get('vista', 'todos')
    if vista not in VISTAS_PEDIDO:
        vista = 'todos'
    if not _puede_vista_pedido(request.user, vista):
        messages.error(request, 'No tienes permiso para imprimir esa variante del pedido')
        return redirect('pedidos-detalle', pk=pk)

    items = pedido.items.all()
    estado_filtro = VISTAS_PEDIDO[vista]['estado']
    if estado_filtro is not None:
        items = items.filter(estado=estado_filtro)

    mostrar_cantidades = is_pedidos_almacen(request.user) or is_pedidos_supervisor(request.user)
    pdf_bytes = None
    if vista == 'todos':
        from formatos import contratos
        from formatos.generacion import generar_pdf as generar_pdf_formato
        pdf_bytes = generar_pdf_formato(
            'pedido',
            contratos.datos_pedido(pedido, items, mostrar_cantidades=mostrar_cantidades),
        )
    if pdf_bytes is None:
        pdf_bytes = generar_pedido_pdf(pedido, items, vista=vista, mostrar_cantidades=mostrar_cantidades)

    sufijo = '' if vista == 'todos' else f'_{vista}'
    nombre_archivo = f"pedido_{pedido.numero_pedido}{sufijo}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
    return response


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def reporte_incidencias(request):
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    tipo_filtro = request.GET.get('tipo', '')

    TIPOS_INCIDENCIA = [
        ('PRODUCTO_ERRONEO', 'Cambio de SKU'),
        ('SKU_NO_CONTEMPLADO', 'SKU No Contemplado'),
        ('CANTIDAD_MENOR', 'Cantidad Menor a lo Despachado'),
        ('CANTIDAD_MAYOR', 'Cantidad Mayor a lo Despachado'),
    ]

    qs = DespachoItem.objects.filter(
        tipo_incidencia__in=['PRODUCTO_ERRONEO', 'SKU_NO_CONTEMPLADO', 'CANTIDAD_MENOR', 'CANTIDAD_MAYOR']
    ).select_related(
        'despacho__pedido__solicitante',
        'pedido_item',
        'autorizado_por',
    ).order_by('-despacho__fecha_despacho').exclude(
        despacho__estado='ANULADO'
    ).exclude(despacho__pedido__estado='ANULADO')

    if fecha_inicio:
        try:
            qs = qs.filter(despacho__fecha_despacho__date__gte=datetime.strptime(fecha_inicio, '%Y-%m-%d').date())
        except ValueError:
            pass
    if fecha_fin:
        try:
            qs = qs.filter(despacho__fecha_despacho__date__lte=datetime.strptime(fecha_fin, '%Y-%m-%d').date())
        except ValueError:
            pass
    if tipo_filtro in [t[0] for t in TIPOS_INCIDENCIA]:
        qs = qs.filter(tipo_incidencia=tipo_filtro)

    total = qs.count()
    total_erroneos = qs.filter(tipo_incidencia='PRODUCTO_ERRONEO').count()
    total_no_contemplados = qs.filter(tipo_incidencia='SKU_NO_CONTEMPLADO').count()
    total_cantidad_menor = qs.filter(tipo_incidencia='CANTIDAD_MENOR').count()
    total_cantidad_mayor = qs.filter(tipo_incidencia='CANTIDAD_MAYOR').count()

    return render(request, 'pedidos-reporte-incidencias.html', {
        'incidencias': qs,
        'total': total,
        'total_erroneos': total_erroneos,
        'total_no_contemplados': total_no_contemplados,
        'total_cantidad_menor': total_cantidad_menor,
        'total_cantidad_mayor': total_cantidad_mayor,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'tipo_filtro': tipo_filtro,
        'tipos_incidencia': TIPOS_INCIDENCIA,
    })


def _sku_incidencia(di: DespachoItem) -> str:
    """SKU que debe figurar en el traslado a2 que resuelve la incidencia.

    Para PRODUCTO_ERRONEO es el producto que realmente llegó (codigo_real);
    para el resto, el código del PedidoItem asociado.
    """
    if di.tipo_incidencia == 'PRODUCTO_ERRONEO' and di.codigo_real:
        return di.codigo_real.strip()
    if di.pedido_item:
        return di.pedido_item.codigo.strip()
    return di.codigo_real.strip()


def _incidencias_base_qs():
    """Queryset base de DespachoItems con incidencia, excluyendo anulados."""
    return (
        DespachoItem.objects.exclude(tipo_incidencia='')
        .select_related(
            'despacho__pedido__solicitante', 'pedido_item', 'autorizado_por',
            'resolucion__resuelto_por',
        )
        .exclude(despacho__estado='ANULADO')
        .exclude(despacho__pedido__estado='ANULADO')
        .order_by('-despacho__fecha_despacho')
    )


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def resolver_incidencias(request):
    """Página de resolución de incidencias: pestañas Pendientes/Resueltas."""
    vista = request.GET.get('vista', 'pendientes')
    if vista not in ('pendientes', 'resueltas'):
        vista = 'pendientes'
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    tipo_filtro = request.GET.get('tipo', '')

    qs = _incidencias_base_qs()
    if fecha_inicio:
        try:
            qs = qs.filter(despacho__fecha_despacho__date__gte=datetime.strptime(fecha_inicio, '%Y-%m-%d').date())
        except ValueError:
            pass
    if fecha_fin:
        try:
            qs = qs.filter(despacho__fecha_despacho__date__lte=datetime.strptime(fecha_fin, '%Y-%m-%d').date())
        except ValueError:
            pass
    if tipo_filtro in [t[0] for t in DespachoItem.TIPO_INCIDENCIA_CHOICES]:
        qs = qs.filter(tipo_incidencia=tipo_filtro)

    pendientes = qs.filter(resolucion__isnull=True)
    resueltas = qs.filter(resolucion__isnull=False).prefetch_related(
        'eventos_incidencia__usuario',
    )
    incidencias = pendientes if vista == 'pendientes' else resueltas

    return render(request, 'pedidos-resolver-incidencias.html', {
        'incidencias': incidencias,
        'vista': vista,
        'total_pendientes': pendientes.count(),
        'total_resueltas': resueltas.count(),
        'tipos_incidencia': DespachoItem.TIPO_INCIDENCIA_CHOICES,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
        'tipo_filtro': tipo_filtro,
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def validar_traslado_incidencias(request):
    """AJAX: valida un documento de traslado a2 contra las incidencias seleccionadas."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método no permitido'}, status=405)
    documento = request.POST.get('documento', '').strip()
    item_ids = request.POST.getlist('item_ids')
    if not documento or not item_ids:
        return JsonResponse({'ok': False, 'error': 'Documento e incidencias son requeridos'}, status=400)

    items = list(
        DespachoItem.objects.exclude(tipo_incidencia='')
        .filter(id__in=item_ids)
        .select_related('pedido_item')
    )
    if not items:
        return JsonResponse({'ok': False, 'error': 'Incidencias no encontradas'}, status=400)

    try:
        resultado = PedidosDBISAM().validar_traslado_resolucion(documento)
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Número de documento inválido'}, status=400)
    except Exception:
        logger.exception('Error validando traslado de resolución contra a2')
        return JsonResponse(
            {'ok': False, 'error': 'No se pudo consultar a2. Intenta de nuevo.'},
            status=502,
        )

    if not resultado['existe']:
        return JsonResponse({'ok': True, 'existe': False, 'skus': [], 'faltantes': [], 'valido': False})

    skus = sorted({_sku_incidencia(di) for di in items})
    faltantes = sorted(set(skus) - resultado['codigos_traslado'])
    return JsonResponse({
        'ok': True,
        'existe': True,
        'skus': skus,
        'faltantes': faltantes,
        'valido': not faltantes,
    })


def _incidencias_pendientes_despacho(despacho: Despacho) -> bool:
    """True si el despacho tiene incidencias sin resolución activa."""
    return despacho.items.exclude(tipo_incidencia='').filter(resolucion__isnull=True).exists()


def _actualizar_estados_tras_resolucion(despacho: Despacho) -> None:
    """Promueve despacho y pedido cuando ya no quedan incidencias pendientes.

    Despacho: PARCIAL → RECIBIDO. Pedido: → RECIBIDO si todos sus items quedan
    en RECIBIDO o INCIDENCIA_RESUELTA (equivalente a recibido).
    """
    if despacho.estado == 'PARCIAL' and not _incidencias_pendientes_despacho(despacho):
        despacho.estado = 'RECIBIDO'
        despacho.save(update_fields=['estado'])

    pedido = despacho.pedido
    estados = list(pedido.items.values_list('estado', flat=True))
    if (
        estados
        and pedido.estado not in ('ANULADO', 'CERRADO', 'RECIBIDO')
        and all(e in ('RECIBIDO', 'INCIDENCIA_RESUELTA') for e in estados)
    ):
        pedido.estado = 'RECIBIDO'
        if not pedido.fecha_recepcion:
            pedido.fecha_recepcion = timezone.now()
        pedido.save(update_fields=['estado', 'fecha_recepcion'])


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def confirmar_resolucion_incidencias(request):
    """Crea una resolución (traslado validado contra a2, o manual) para las incidencias elegidas."""
    if request.method != 'POST':
        return redirect('pedidos-resolver-incidencias')

    item_ids = request.POST.getlist('item_ids')
    tipo = request.POST.get('tipo', '')
    documento = request.POST.get('documento', '').strip()
    observacion = request.POST.get('observacion', '').strip()

    if not item_ids:
        messages.error(request, 'Selecciona al menos una incidencia.')
        return redirect('pedidos-resolver-incidencias')
    if tipo not in ('TRASLADO', 'MANUAL'):
        messages.error(request, 'Tipo de resolución inválido.')
        return redirect('pedidos-resolver-incidencias')
    if tipo == 'MANUAL' and not observacion:
        messages.error(request, 'La observación es obligatoria en una resolución manual.')
        return redirect('pedidos-resolver-incidencias')
    if tipo == 'TRASLADO' and not documento:
        messages.error(request, 'Indica el número de documento del traslado.')
        return redirect('pedidos-resolver-incidencias')

    items = list(
        DespachoItem.objects.exclude(tipo_incidencia='')
        .filter(id__in=item_ids)
        .select_related('pedido_item')
    )
    if len(items) != len(set(item_ids)):
        messages.error(request, 'Alguna de las incidencias seleccionadas no existe.')
        return redirect('pedidos-resolver-incidencias')

    # Revalidación en servidor contra a2 (no confía en el AJAX previo)
    if tipo == 'TRASLADO':
        try:
            resultado = PedidosDBISAM().validar_traslado_resolucion(documento)
        except ValueError:
            messages.error(request, 'Número de documento inválido.')
            return redirect('pedidos-resolver-incidencias')
        except Exception:
            logger.exception('Error validando traslado de resolución contra a2')
            messages.error(request, 'No se pudo validar contra a2. Intenta de nuevo.')
            return redirect('pedidos-resolver-incidencias')
        if not resultado['existe']:
            messages.error(request, f'El documento {documento} no existe como traslado en a2.')
            return redirect('pedidos-resolver-incidencias')
        faltantes = sorted({_sku_incidencia(di) for di in items} - resultado['codigos_traslado'])
        if faltantes:
            messages.error(
                request,
                f'El traslado {documento} no incluye los SKUs: {", ".join(faltantes)}.',
            )
            return redirect('pedidos-resolver-incidencias')

    with transaction.atomic():
        # of=('self',): bloquear solo las filas de DespachoItem; el JOIN a
        # pedido_item es nullable (LEFT OUTER) y Postgres no admite FOR UPDATE
        # sobre el lado nullable de un outer join.
        bloqueados = list(
            DespachoItem.objects.select_for_update(of=('self',))
            .filter(id__in=[di.id for di in items], resolucion__isnull=True)
            .select_related('pedido_item')
        )
        if len(bloqueados) != len(items):
            messages.error(request, 'Alguna incidencia ya fue resuelta por otro usuario. Refresca la página.')
            return redirect('pedidos-resolver-incidencias')

        resolucion = ResolucionIncidencia.objects.create(
            tipo=tipo,
            documento_traslado=documento if tipo == 'TRASLADO' else '',
            observacion=observacion,
            resuelto_por=request.user,
        )
        despachos_ids = set()
        for di in bloqueados:
            di.resolucion = resolucion
            di.save(update_fields=['resolucion'])
            IncidenciaEvento.objects.create(
                despacho_item=di, resolucion=resolucion, tipo_evento='RESOLUCION',
                usuario=request.user,
                detalle=(f'Traslado a2 {documento}' if tipo == 'TRASLADO' else f'Manual: {observacion}'),
            )
            if di.pedido_item and di.pedido_item.estado == 'INCIDENCIA':
                di.pedido_item.estado = 'INCIDENCIA_RESUELTA'
                di.pedido_item.save(update_fields=['estado'])
            despachos_ids.add(di.despacho_id)

        for despacho in Despacho.objects.select_for_update().filter(numero_despacho__in=despachos_ids):
            _actualizar_estados_tras_resolucion(despacho)

    messages.success(request, f'{len(bloqueados)} incidencia(s) resuelta(s) correctamente.')
    return redirect('pedidos-resolver-incidencias')


def _revertir_estados_tras_anulacion(despacho: Despacho) -> None:
    """Devuelve despacho y pedido a PARCIAL si reaparecen incidencias pendientes."""
    if despacho.estado == 'RECIBIDO' and _incidencias_pendientes_despacho(despacho):
        despacho.estado = 'PARCIAL'
        despacho.save(update_fields=['estado'])

    pedido = despacho.pedido
    if pedido.estado == 'RECIBIDO' and pedido.items.filter(estado='INCIDENCIA').exists():
        pedido.estado = 'PARCIAL'
        pedido.save(update_fields=['estado'])


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def anular_resolucion_incidencia(request, resolucion_id):
    """Anula una resolución activa: las incidencias vuelven a pendientes."""
    if request.method != 'POST':
        return redirect('pedidos-resolver-incidencias')
    motivo = request.POST.get('motivo', '').strip()
    if not motivo:
        messages.error(request, 'El motivo de anulación es obligatorio.')
        return redirect('pedidos-resolver-incidencias')

    with transaction.atomic():
        try:
            resolucion = (
                ResolucionIncidencia.objects.select_for_update()
                .get(pk=resolucion_id, estado='ACTIVA')
            )
        except ResolucionIncidencia.DoesNotExist:
            messages.error(request, 'La resolución no existe o ya fue anulada.')
            return redirect('pedidos-resolver-incidencias')

        resolucion.estado = 'ANULADA'
        resolucion.anulada_por = request.user
        resolucion.fecha_anulacion = timezone.now()
        resolucion.motivo_anulacion = motivo
        resolucion.save(update_fields=['estado', 'anulada_por', 'fecha_anulacion', 'motivo_anulacion'])

        items = list(resolucion.items_resueltos.select_related('pedido_item'))
        despachos_ids = set()
        for di in items:
            IncidenciaEvento.objects.create(
                despacho_item=di, resolucion=resolucion, tipo_evento='ANULACION',
                usuario=request.user, detalle=motivo,
            )
            di.resolucion = None
            di.save(update_fields=['resolucion'])
            if di.pedido_item and di.pedido_item.estado == 'INCIDENCIA_RESUELTA':
                di.pedido_item.estado = 'INCIDENCIA'
                di.pedido_item.save(update_fields=['estado'])
            despachos_ids.add(di.despacho_id)

        for despacho in Despacho.objects.select_for_update().filter(numero_despacho__in=despachos_ids):
            _revertir_estados_tras_anulacion(despacho)

    messages.success(request, f'Resolución anulada: {len(items)} incidencia(s) vuelven a pendientes.')
    return redirect('pedidos-resolver-incidencias')


@login_required(login_url='/login/')
def contar_pendientes(request):
    if is_pedidos_supervisor(request.user):
        count = (
            Pedido.objects.filter(estado='PENDIENTE').count()
            + Despacho.objects.filter(estado='PENDIENTE_APROBACION').count()
        )
    elif is_pedidos_almacen(request.user):
        count = Pedido.objects.filter(estado='PENDIENTE').count()
    elif _solo_picker(request.user) and not _es_receptor_grupo(request.user) and not is_pedidos_tienda(request.user):
        count = Pedido.objects.filter(picker=request.user, estado__in=['ASIGNADO', 'PICKING']).count()
    elif is_pedidos_tienda(request.user) or _es_receptor_grupo(request.user):
        condiciones = Q()
        if is_pedidos_tienda(request.user):
            condiciones |= Q(pedido__solicitante=request.user)
        if _es_receptor_grupo(request.user):
            condiciones |= Q(pedido__deposito_codigo__in=_codigos_depositos_receptor(request.user))
        count = Despacho.objects.filter(condiciones, estado='ENVIADO').count()
        if _solo_picker(request.user):
            count += Pedido.objects.filter(picker=request.user, estado__in=['ASIGNADO', 'PICKING']).count()
    else:
        count = 0
    return HttpResponse(f'<span class="badge bg-danger rounded-pill">{count}</span>' if count > 0 else '')
