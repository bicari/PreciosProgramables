from django.urls import path

from . import api_views

urlpatterns = [
    path('racks/', api_views.api_racks_list, name='api-racks-list'),
    path('racks/<int:pk>/', api_views.api_rack_detail, name='api-rack-detail'),
    path('niveles/<int:pk>/ubicaciones/', api_views.api_nivel_ubicaciones, name='api-nivel-ubicaciones'),
    path('ubicaciones/<int:pk>/', api_views.api_ubicacion_detail, name='api-ubicacion-detail'),
    path('ubicaciones/<int:pk>/asignar/', api_views.api_asignar_producto, name='api-ubicacion-asignar'),
    path('ubicaciones/<int:pk>/quitar/', api_views.api_quitar_producto, name='api-ubicacion-quitar'),
    path('ubicaciones/trasladar/', api_views.api_trasladar, name='api-ubicaciones-trasladar'),
    path('ubicaciones/fusionar/', api_views.api_fusionar, name='api-ubicaciones-fusionar'),
    path('ubicaciones/movimientos/', api_views.api_movimientos, name='api-ubicaciones-movimientos'),
    path('productos/<str:codigo>/ubicaciones/', api_views.api_producto_ubicaciones, name='api-producto-ubicaciones'),
]
