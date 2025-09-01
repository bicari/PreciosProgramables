from django.urls import path
from .views import ListFormView, ListTaskView, ListLabelView, download_duplicados, download_excel
urlpatterns = [
    path('list-form/', ListFormView, name='list-form'),
    path('list-tasks/',  ListTaskView, name='list-tasks'),
    path('print-label/', ListLabelView, name='print-label'),
    path('download_duplicados/', download_duplicados, name='download_duplicados'),
    path('download_excel/<int:task_id>', download_excel, name='download_excel')

    
]
