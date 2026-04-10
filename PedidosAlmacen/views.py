from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Sum, Avg, Count, F, ExpressionWrapper, DurationField
from datetime import datetime
from .models import Pedido, PedidoItem
from .forms import PedidoForm
from .dbisam import PedidosDBISAM
from .notifications import notificar_nuevo_pedido, notificar_despacho, notificar_recepcion
from .pdf import generar_reporte_pedidos_pdf
import logging
import json

logger = logging.getLogger(__name__)


GROUP_TIENDA = 'Pedidos Tienda'
GROUP_ALMACEN = 'Pedidos Almacen'
GROUP_SUPERVISOR = 'Pedidos Supervisor'


def is_pedidos_tienda(user):
    return user.groups.filter(name=GROUP_TIENDA).exists() or user.is_superuser


def is_pedidos_almacen(user):
    return user.groups.filter(name=GROUP_ALMACEN).exists() or user.is_superuser


def is_pedidos_supervisor(user):
    return user.groups.filter(name=GROUP_SUPERVISOR).exists() or user.is_superuser


def is_pedidos_any(user):
    return user.groups.filter(name__in=[GROUP_TIENDA, GROUP_ALMACEN, GROUP_SUPERVISOR]).exists() or user.is_superuser


def _solo_tienda(user):
    """True si el usuario es Tienda pero NO Almacen ni Supervisor (acceso restringido a sus propios pedidos)."""
    return is_pedidos_tienda(user) and not is_pedidos_almacen(user) and not is_pedidos_supervisor(user)


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_any, login_url='dashboard')
def lista_pedidos(request):
    if is_pedidos_supervisor(request.user):
        pedidos = Pedido.objects.select_related('solicitante', 'despachador').order_by('-fecha_creacion')
    elif is_pedidos_almacen(request.user):
        pedidos = Pedido.objects.select_related('solicitante', 'despachador').exclude(estado='CERRADO').order_by('-fecha_creacion')
    else:
        pedidos = Pedido.objects.filter(solicitante=request.user).select_related('solicitante', 'despachador').order_by('-fecha_creacion')

    estado_filter = request.GET.get('estado', '')
    if estado_filter:
        pedidos = pedidos.filter(estado=estado_filter)

    return render(request, 'pedidos-lista.html', {
        'pedidos': pedidos,
        'estado_filter': estado_filter,
        'estados': Pedido.ESTADO_CHOICES,
        'es_tienda': _solo_tienda(request.user),
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_tienda, login_url='dashboard')
def crear_pedido(request):
    categorias = []
    depositos = []
    try:
        dbisam = PedidosDBISAM()
        categorias = dbisam.obtener_categorias()
        depositos = dbisam.obtener_depositos()
    except Exception:
        pass

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

        deposito_codigo_int = None
        try:
            deposito_codigo_int = int(deposito_codigo)
        except (ValueError, TypeError):
            pass

        pedido = Pedido.objects.create(
            solicitante=request.user,
            observaciones=form.data.get('observaciones', ''),
            categoria=categoria_nombre or categoria_codigo,
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
    pedido = get_object_or_404(Pedido.objects.select_related('solicitante', 'despachador'), numero_pedido=pk)

    if _solo_tienda(request.user) and pedido.solicitante != request.user:
        messages.error(request, 'No tienes permiso para ver este pedido')
        return redirect('pedidos-lista')

    items = pedido.items.all()
    es_supervisor = is_pedidos_supervisor(request.user)
    es_despachador = is_pedidos_almacen(request.user)
    return render(request, 'pedidos-detalle.html', {
        'pedido': pedido,
        'items': items,
        'ver_despachado': es_supervisor,
        'es_despachador': es_despachador,
        'puede_recibir': is_pedidos_tienda(request.user),
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_almacen, login_url='dashboard')
def despachar_pedido(request, pk):
    pedido = get_object_or_404(Pedido, numero_pedido=pk)

    if pedido.estado not in ('PENDIENTE', 'PICKING'):
        messages.warning(request, 'Este pedido no puede ser despachado en su estado actual')
        return redirect('pedidos-detalle', pk=pk)

    items = pedido.items.filter(estado__in=['PENDIENTE', 'BACK_ORDER'])

    # Consultar stock en DBISAM
    stock_info = {}
    try:
        dbisam = PedidosDBISAM()
        codigos = [item.codigo for item in items]
        stock_info = dbisam.consultar_stock_multiple(codigos)
    except Exception as e:
        messages.warning(request, f'No se pudo consultar el stock: {e}')

    if request.method == 'POST':
        pedido.despachador = request.user
        pedido.fecha_despacho = datetime.now()
        hay_despacho = False

        for item in items:
            cantidad_enviar = request.POST.get(f'cantidad_{item.id}', '0')
            try:
                cantidad_enviar = int(cantidad_enviar)
            except ValueError:
                cantidad_enviar = 0

            if cantidad_enviar > 0:
                item.cantidad_despachada = cantidad_enviar
                item.estado = 'DESPACHADO'
                hay_despacho = True
            else:
                item.estado = 'BACK_ORDER'
            item.save()

        if hay_despacho:
            pedido.estado = 'DESPACHADO'
            pedido.save()
            notificar_despacho(pedido)
            messages.success(request, f'Pedido #{pedido.numero_pedido} despachado')
        else:
            messages.warning(request, 'No se despacharon items')

        return redirect('pedidos-detalle', pk=pk)

    items_con_stock = []
    for item in items:
        items_con_stock.append({
            'item': item,
            'stock': stock_info.get(item.codigo, 0),
        })

    return render(request, 'pedidos-despachar.html', {
        'pedido': pedido,
        'items_con_stock': items_con_stock,
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_tienda, login_url='dashboard')
def recibir_pedido(request, pk):
    pedido = get_object_or_404(Pedido, numero_pedido=pk)

    if _solo_tienda(request.user) and pedido.solicitante != request.user:
        messages.error(request, 'No tienes permiso para recibir este pedido')
        return redirect('pedidos-lista')

    if pedido.estado != 'DESPACHADO':
        messages.warning(request, 'Este pedido no tiene despachos pendientes de recepcion')
        return redirect('pedidos-detalle', pk=pk)

    items = pedido.items.filter(estado='DESPACHADO')

    if request.method == 'POST':
        items_traslado = []

        for item in items:
            cantidad_recibida = request.POST.get(f'recibido_{item.id}', '0')
            observacion = request.POST.get(f'observacion_{item.id}', '')
            try:
                cantidad_recibida = int(cantidad_recibida)
            except ValueError:
                cantidad_recibida = 0

            item.cantidad_recibida = cantidad_recibida
            item.observacion = observacion

            if cantidad_recibida >= item.cantidad_despachada:
                item.estado = 'RECIBIDO'
            else:
                item.estado = 'INCIDENCIA'
            item.save()

            if cantidad_recibida > 0:
                items_traslado.append({'codigo': item.codigo, 'cantidad': cantidad_recibida})

        # Verificar si todos los items del pedido estan finalizados
        items_pendientes = pedido.items.filter(estado__in=['PENDIENTE', 'DESPACHADO', 'BACK_ORDER']).exists()
        if not items_pendientes:
            pedido.estado = 'RECIBIDO'
            pedido.fecha_recepcion = datetime.now()
        pedido.save()

        # Insertar traslado en DBISAM
        if items_traslado and pedido.deposito_codigo:
            try:
                dbisam = PedidosDBISAM()
                dbisam.insertar_traslado(pedido.numero_pedido, pedido.deposito_codigo, items_traslado)
            except Exception as e:
                logger.error(f'Error al insertar traslado DBISAM para pedido #{pedido.numero_pedido}: {e}')
                messages.error(
                    request,
                    f'Recepción registrada, pero ocurrió un error al registrar el traslado en a2 se recomienda realizar el traslado manual: {e}'
                )

        notificar_recepcion(pedido)
        messages.success(request, f'Recepcion del pedido #{pedido.numero_pedido} registrada')
        return redirect('pedidos-detalle', pk=pk)

    return render(request, 'pedidos-recibir.html', {
        'pedido': pedido,
        'items': items,
        'ver_despachado': is_pedidos_supervisor(request.user),
    })


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_any, login_url='dashboard')
def buscar_producto(request):
    query = request.GET.get('q', '').strip()
    tipo = request.GET.get('tipo', 'codigo')
    categoria = request.GET.get('categoria', '').strip()

    if not categoria:
        return HttpResponse('<p class="text-warning">Seleccione una categoria antes de buscar</p>')

    if len(query) < 2:
        return HttpResponse('')

    try:
        dbisam = PedidosDBISAM()
        resultados = dbisam.buscar_en_categoria(categoria, query, tipo)
    except Exception:
        resultados = []

    return render(request, 'pedidos-buscar-producto.html', {'resultados': resultados})


@login_required(login_url='/login/')
@user_passes_test(is_pedidos_supervisor, login_url='dashboard')
def reporte_pedidos(request):
    fecha_inicio = request.GET.get('fecha_inicio', '')
    fecha_fin = request.GET.get('fecha_fin', '')
    categoria_filtro = request.GET.get('categoria', '')
    condicion_filtro = request.GET.get('condicion', '')

    pedidos = Pedido.objects.all()

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

    # Tiempo promedio de despacho efectivo (creacion -> despacho)
    tiempo_horas = None
    tiempo_minutos = None
    pedidos_con_despacho = pedidos.filter(fecha_despacho__isnull=False)
    if pedidos_con_despacho.exists():
        resultado = pedidos_con_despacho.annotate(
            duracion=ExpressionWrapper(
                F('fecha_despacho') - F('fecha_creacion'),
                output_field=DurationField()
            )
        ).aggregate(promedio=Avg('duracion'))
        if resultado['promedio']:
            total_seg = int(resultado['promedio'].total_seconds())
            tiempo_horas = total_seg // 3600
            tiempo_minutos = (total_seg % 3600) // 60

    categoria_top = (
        pedidos.exclude(categoria='')
        .values('categoria')
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
        .values('categoria')
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
        .values_list('categoria', flat=True)
        .distinct()
        .order_by('categoria')
    )

    return render(request, 'pedidos-reporte.html', {
        'total_pedidos': total_pedidos,
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

    pedidos = Pedido.objects.all()
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
        resultado = pedidos_con_despacho.annotate(
            duracion=ExpressionWrapper(
                F('fecha_despacho') - F('fecha_creacion'),
                output_field=DurationField()
            )
        ).aggregate(promedio=Avg('duracion'))
        if resultado['promedio']:
            total_seg = int(resultado['promedio'].total_seconds())
            tiempo_horas = total_seg // 3600
            tiempo_minutos = (total_seg % 3600) // 60

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
            .values('categoria').annotate(total=Count('numero_pedido'))
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
            pedidos.exclude(categoria='').values('categoria')
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


@login_required(login_url='/login/')
def contar_pendientes(request):
    if is_pedidos_almacen(request.user):
        count = Pedido.objects.filter(estado='PENDIENTE').count()
    elif is_pedidos_tienda(request.user):
        count = Pedido.objects.filter(solicitante=request.user, estado='DESPACHADO').count()
    else:
        count = 0
    return HttpResponse(f'<span class="badge bg-danger rounded-pill">{count}</span>' if count > 0 else '')
