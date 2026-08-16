"""guarda tickets y eventos en bigquery"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery
from src import config

# cliente reutilizable
_cliente = bigquery.Client(project=config.PROYECTO)

# tabla completa con proyecto.dataset.tabla
TABLA_TICKETS = f"{config.PROYECTO}.{config.DATASET}.tickets"
TABLA_EVENTOS = f"{config.PROYECTO}.{config.DATASET}.eventos_ticket"

# minutos de sla por prioridad
SLA_MINUTOS = {
    "P0": 120,
    "P1": 480,
    "P2": 1440,
    "P3": 7200,
}

# matriz itil: impacto x urgencia da prioridad
MATRIZ_PRIORIDAD = {
    ("alto", "alta"): "P0",
    ("alto", "media"): "P1",
    ("alto", "baja"): "P2",
    ("medio", "alta"): "P1",
    ("medio", "media"): "P2",
    ("medio", "baja"): "P3",
    ("bajo", "alta"): "P2",
    ("bajo", "media"): "P3",
    ("bajo", "baja"): "P3",
}


def calcular_prioridad(impacto: str, urgencia: str) -> str:
    """devuelve la prioridad segun matriz itil"""
    return MATRIZ_PRIORIDAD.get((impacto, urgencia), "P3")


def generar_id_ticket() -> str:
    """genera id tipo TCK-YYYYMMDD-NNN consultando la tabla"""
    hoy = datetime.now(timezone.utc).strftime("%Y%m%d")
    query = f"""
        SELECT COUNT(*) as total
        FROM `{TABLA_TICKETS}`
        WHERE DATE(creado_en) = CURRENT_DATE()
    """
    resultado = _cliente.query(query).result()
    total = next(resultado).total
    siguiente = total + 1
    return f"TCK-{hoy}-{siguiente:03d}"


def crear_ticket(
    origen: str,
    remitente: str,
    texto_original: str,
    clasificacion,
) -> str:
    """crea un ticket en estado sugerido y su evento inicial"""
    ahora = datetime.now(timezone.utc)
    ticket_id = generar_id_ticket()
    prioridad = calcular_prioridad(clasificacion.impacto, clasificacion.urgencia)
    sla_vence = ahora + timedelta(minutes=SLA_MINUTOS[prioridad])

    fila_ticket = {
        "id": ticket_id,
        "creado_en": ahora.isoformat(),
        "origen": origen,
        "remitente": remitente,
        "texto_original": texto_original,
        "tipo": clasificacion.categoria,
        "estado": "sugerido",
        "categoria": clasificacion.categoria,
        "sistema_afectado": clasificacion.sistema_afectado,
        "impacto": clasificacion.impacto,
        "urgencia": clasificacion.urgencia,
        "prioridad": prioridad,
        "resumen": clasificacion.resumen,
        "asignado_a": None,
        "sla_vence_en": sla_vence.isoformat(),
        "sugerencia_ia": _serializar_sugerencia(clasificacion),
        "motivo_descarte": None,
        "comentario_resolucion": None,
        "ultima_actividad": ahora.isoformat(),
    }

    errores = _cliente.insert_rows_json(TABLA_TICKETS, [fila_ticket])
    if errores:
        raise RuntimeError(f"error insertando ticket: {errores}")

    # registrar evento de creacion
    _registrar_evento(
        ticket_id=ticket_id,
        evento="creado",
        estado_nuevo="sugerido",
        actor="sistema",
        nota=f"clasificado por gemini con confianza {clasificacion.confianza:.2f}",
    )

    return ticket_id


def _registrar_evento(
    ticket_id: str,
    evento: str,
    actor: str,
    estado_anterior: str = None,
    estado_nuevo: str = None,
    nota: str = None,
):
    """registra un evento en la tabla eventos_ticket"""
    fila = {
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "evento": evento,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "actor": actor,
        "fecha": datetime.now(timezone.utc).isoformat(),
        "nota": nota,
    }
    errores = _cliente.insert_rows_json(TABLA_EVENTOS, [fila])
    if errores:
        raise RuntimeError(f"error insertando evento: {errores}")


def _serializar_sugerencia(clasificacion) -> str:
    """convierte el dataclass Resultado en string json para bigquery"""
    return json.dumps({
        "categoria": clasificacion.categoria,
        "sistema_afectado": clasificacion.sistema_afectado,
        "impacto": clasificacion.impacto,
        "urgencia": clasificacion.urgencia,
        "resumen": clasificacion.resumen,
        "confianza": clasificacion.confianza,
    })