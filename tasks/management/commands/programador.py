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
        try:
            self.iniciar_tareas()
            print("Scheduler corriendo. Presiona Ctrl+C para salir.")
            while True:
                time.sleep(2)
        except KeyboardInterrupt:
            print("Deteniendo scheduler...")
            sys.exit(0)

    def iniciar_tareas(self):
        iniciar_scheduler()