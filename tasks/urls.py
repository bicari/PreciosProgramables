from django.urls import path
from .views import ListFormView, ListFormResultView, ListTaskView, ListLabelView, LabelListInfoView, download_duplicados, download_excel, PreviewListView, TaskDetailView
urlpatterns = [
    path('list-form/', ListFormView, name='list-form'),
    path('list-form/resultado/', ListFormResultView, name='list-form-result'),
    path('validar-lista/', PreviewListView, name='validar-lista'),
    path('list-tasks/', ListTaskView, name='list-tasks'),
    path('list-tasks/<int:task_id>/detalle/', TaskDetailView, name='task-detail'),
    path('print-label/', ListLabelView, name='print-label'),
    path('print-label/count/<int:list_id>/', LabelListInfoView, name='print-label-count'),
    path('download_duplicados/', download_duplicados, name='download_duplicados'),
    path('download_excel/<int:task_id>', download_excel, name='download_excel'),
]
