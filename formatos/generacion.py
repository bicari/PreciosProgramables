"""Generación de PDFs desde plantillas ReportBro con tolerancia total a fallos."""
import logging

from reportbro import Report

from .models import PlantillaImpresion

logger = logging.getLogger(__name__)


def validar_plantilla(definicion: dict, datos: dict) -> str:
    """Valida que la definición genere un PDF con los datos dados.

    Returns:
        '' si genera bien; mensaje de error legible si no.
    """
    try:
        report = Report(definicion, datos)
        if report.errors:
            return str(report.errors)
        report.generate_pdf()
        return ''
    except Exception as exc:  # noqa: BLE001 — cualquier fallo invalida
        return str(exc)


def generar_pdf(tipo: str, datos: dict) -> bytes | None:
    """Genera el PDF del tipo con su plantilla activa.

    Returns:
        Bytes del PDF, o None si no hay plantilla activa o la generación
        falla (el caller debe caer a su generador de respaldo).
    """
    plantilla = PlantillaImpresion.objects.filter(tipo=tipo, activa=True).first()
    if plantilla is None:
        return None
    try:
        report = Report(plantilla.definicion, datos)
        if report.errors:
            logger.error('Plantilla %s con errores: %s', tipo, report.errors)
            return None
        return bytes(report.generate_pdf())
    except Exception:  # noqa: BLE001 — nunca romper la operación del almacén
        logger.exception('Fallo generando PDF ReportBro para %s', tipo)
        return None
