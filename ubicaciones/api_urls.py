from django.urls import path

from . import api_views

urlpatterns = [
    path('galpones/', api_views.api_galpones_list, name='api-galpones-list'),
    path('galpones/<int:pk>/', api_views.api_galpon_detail, name='api-galpon-detail'),
    path('racks/<int:pk>/', api_views.api_rack_detail, name='api-rack-detail'),
    path('cuerpos/<int:pk>/', api_views.api_cuerpo_detail, name='api-cuerpo-detail'),
    path('niveles/<int:pk>/asignar/', api_views.api_asignar_producto, name='api-nivel-asignar'),
    path('niveles/<int:pk>/desfusionar/', api_views.api_desfusionar, name='api-nivel-desfusionar'),
    path('niveles/trasladar/', api_views.api_trasladar, name='api-niveles-trasladar'),
    path('niveles/fusionar/', api_views.api_fusionar, name='api-niveles-fusionar'),
    path('producto-ubicaciones/<int:pk>/editar-cantidad/', api_views.api_editar_cantidad, name='api-pu-editar-cantidad'),
    path('producto-ubicaciones/<int:pk>/quitar/', api_views.api_quitar_producto, name='api-pu-quitar'),
    path('ubicaciones/movimientos/', api_views.api_movimientos, name='api-ubicaciones-movimientos'),
    path('productos/<str:codigo>/ubicaciones/', api_views.api_producto_ubicaciones, name='api-producto-ubicaciones'),
    path('ubicaciones/incidencias/', api_views.api_incidencias_list, name='api-ubicaciones-incidencias'),
    path('ubicaciones/movimientos/<int:pk>/resolver/', api_views.api_resolver_incidencia, name='api-movimiento-resolver'),
    path('producto-ubicaciones/<int:pk>/marcar-principal/', api_views.api_marcar_principal, name='api-pu-marcar-principal'),
]
