from django.contrib import admin
from .models import Tasks
from django.utils.html import format_html
from django.conf import settings
import os
@admin.register(Tasks)
class TasksAdmin(admin.ModelAdmin):
    list_display = ('task_number', 'user_id', 'check_process', 'file_download_link','created_at', 'date_to_execute')
    list_filter = ('check_process', 'created_at')
    search_fields = ('task_number',)
    list_per_page = 10
    ordering = ('-created_at',)


    def file_download_link(self, obj):
        if obj.file and os.path.exists(os.path.join(settings.MEDIA_ROOT, obj.file.name)):
            return format_html(
                '<a href="{}" download>📥 Descargar</a>',
                f"{settings.MEDIA_URL}{obj.file.name}"
            )
        return "—"  # si no hay archivo o no existe
    file_download_link.short_description = "Archivo"
    
    file_download_link.short_description = "Archivo"  # Nombre de la columna
    file_download_link.allow_tags = True