from django.core.management.base import BaseCommand
from tasks.scheduler import iniciar_scheduler 
import time
import sys

class Command(BaseCommand):
    help = "Corre el APScheduler como proceso independiente"

    def add_arguments(self, parser):
        parser.add_argument(
            '--test',
            action='store_true',
            help='Iniciar scheduler'
        )

    def handle(self, *args, **options):
        print("Iniciando servicio de Scheduler...")
        
        # Iniciamos tu lógica de scheduler
        
        
        print("Scheduler corriendo. Presiona Ctrl+C para salir.")
        
        try:
            # Bucle infinito para mantener el script vivo
            self.iniciar_tareas()
            while True:
                time.sleep(20)
                
        except KeyboardInterrupt:
            print("Deteniendo scheduler...")
            sys.exit(0)

    def iniciar_tareas(self):
        iniciar_scheduler()