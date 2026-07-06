from django.urls import path

from . import views

urlpatterns = [
    path('formatos/', views.lista_formatos, name='formatos-lista'),
    path('formatos/<str:tipo>/disenar/', views.disenar, name='formatos-disenar'),
    path('formatos/<str:tipo>/report/run', views.report_run, name='formatos-report-run'),
    path('formatos/<str:tipo>/guardar/', views.guardar, name='formatos-guardar'),
    path('formatos/<str:tipo>/activar/', views.activar, name='formatos-activar'),
    path('formatos/<str:tipo>/desactivar/', views.desactivar, name='formatos-desactivar'),
    path('formatos/<str:tipo>/restaurar/', views.restaurar, name='formatos-restaurar'),
]
