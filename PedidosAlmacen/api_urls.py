from django.urls import path
from . import api_views

urlpatterns = [
    path('pedidos/', api_views.api_pedidos_list, name='api-pedidos-list'),
    path('pedidos/<int:pk>/', api_views.api_pedido_detail, name='api-pedido-detail'),
    path('pedidos/<int:pk>/estado/', api_views.api_update_pedido, name='api-pedido-update'),
    path('pedidos/<int:pk>/preparar/', api_views.api_preparar_pedido, name='api-pedido-preparar'),
    path('pedidos/<int:pedido_pk>/items/<int:item_pk>/', api_views.api_update_item, name='api-item-update'),
    path('despachos/', api_views.api_despachos_list, name='api-despachos-list'),
    path('despachos/crear/', api_views.api_crear_despacho, name='api-despachos-crear'),
    path('alerts/', api_views.api_alerts_list, name='api-alerts-list'),
    path('productos/<str:codigo>/', api_views.api_buscar_producto, name='api-buscar-producto'),
]
