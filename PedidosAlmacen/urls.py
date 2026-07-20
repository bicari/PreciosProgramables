from django.urls import path
from . import views

urlpatterns = [
    path('pedidos/', views.lista_pedidos, name='pedidos-lista'),
    path('pedidos/crear/', views.crear_pedido, name='pedidos-crear'),
    path('pedidos/<int:pk>/', views.detalle_pedido, name='pedidos-detalle'),
    path('pedidos/<int:pk>/anular/', views.anular_pedido, name='pedidos-anular'),
    path('pedidos/<int:pk>/despachar/', views.despachar_pedido, name='pedidos-despachar'),
    path('pedidos/<int:pk>/despachos/<int:despacho_id>/recibir/', views.recibir_despacho, name='pedidos-recibir-despacho'),
    path('pedidos/verificar-autorizacion/', views.verificar_autorizacion_despacho, name='pedidos-verificar-autorizacion'),
    path('pedidos/<int:pk>/despachos/<int:despacho_id>/pdf/', views.exportar_despacho_pdf, name='pedidos-despacho-pdf'),
    path('pedidos/<int:pk>/pdf/', views.exportar_pedido_pdf, name='pedidos-pdf'),
    path('pedidos/buscar-producto/', views.buscar_producto, name='pedidos-buscar-producto'),
    path('pedidos/pendientes-count/', views.contar_pendientes, name='pedidos-pendientes-count'),
    path('pedidos/reporte/', views.reporte_pedidos, name='pedidos-reporte'),
    path('pedidos/reporte/pdf/', views.exportar_reporte_pdf, name='pedidos-reporte-pdf'),
    path('pedidos/reporte/incidencias/', views.reporte_incidencias, name='pedidos-reporte-incidencias'),
    path('pedidos/incidencias/resolver/', views.resolver_incidencias, name='pedidos-resolver-incidencias'),
    path('pedidos/incidencias/resolver/validar/', views.validar_traslado_incidencias, name='pedidos-validar-traslado-incidencias'),
    path('pedidos/incidencias/resolver/confirmar/', views.confirmar_resolucion_incidencias, name='pedidos-confirmar-resolucion'),
    path('pedidos/<int:pk>/asignar-picker/', views.asignar_picker, name='pedidos-asignar-picker'),
    path('pedidos/<int:pk>/desasignar-picker/', views.desasignar_picker, name='pedidos-desasignar-picker'),
    path('pedidos/<int:pk>/preparar/', views.preparar_pedido, name='pedidos-preparar'),
    path('pedidos/<int:pk>/despachos/<int:despacho_id>/confirmar/', views.confirmar_despacho, name='pedidos-confirmar-despacho'),
    path('pedidos/<int:pk>/despachos/<int:despacho_id>/reintentar-traslado/', views.reintentar_traslado_despacho, name='pedidos-reintentar-traslado-despacho'),
    path('despachos/', views.lista_despachos, name='despachos-lista'),
    path('despachos/<int:despacho_id>/anular/', views.anular_despacho, name='despachos-anular'),
]
