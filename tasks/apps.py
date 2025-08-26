from django.apps import AppConfig
from django.conf import settings
import threading
import sys, os
import atexit

class TasksConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tasks'
    _scheduler_lock = threading.Lock()
    _scheduler_started = False
    _scheduler_timer = None  # ¡Añade esta línea!

    #TRACKING ESTADOS APP ERROR - PROCESADO - POR PROCESAR
    #IMPRIMIR ETIQUETAS SOLO CUANDO ESTE PROCESADO LA TAREA

    def ready(self):
        
        exclude_commands = [
        'migrate',
        'makemigrations',
        'flush',
        'test',  # Opcional: excluir durante tests
        'shell',
        'createsuperuser'
        ]
        if settings.DEBUG and os.environ.get("RUN_MAIN") != "true":
            return
        if any(cmd in sys.argv for cmd in exclude_commands):
            return
        
    # Resto de tu lógica normal de inicio
        self._start_scheduler_safe()

    def _start_scheduler_safe(self):
            with self._scheduler_lock:
                if not self._scheduler_started:
                    from .scheduler import get_scheduler
                    scheduler = get_scheduler()

                    def start_scheduler():
                        if not scheduler.running:
                            try:
                                from .scheduler import iniciar_scheduler
                                iniciar_scheduler()
                                atexit.register(self._shutdown_scheduler)
                            except Exception as e:
                                print(f"Error al iniciar scheduler: {e}")

                    # Cancelar timer anterior si existe
                    if self._scheduler_timer:
                        self._scheduler_timer.cancel()

                    # Iniciar con delay de 5 segundos
                    self._scheduler_timer = threading.Timer(5.0, start_scheduler)
                    self._scheduler_timer.start()
                    self._scheduler_started = True

    def _shutdown_scheduler(self):
        from .scheduler import get_scheduler
        scheduler = get_scheduler()
        if scheduler.running:
            scheduler.shutdown(wait=False)
            print("Scheduler detenido correctamente")
