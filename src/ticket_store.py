"""guarda tickets y eventos en bigquery usando dml"""
import json
import uuid
from datetime import datetime, timezone, timedelta
from google.cloud import bigquery
from src import config

# cliente reutilizable
_cliente = bigquery.Client(project=config.PROYECTO)

# tablas completas con proyecto.dataset.tabla
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

    _insertar_ticket_via_sql(fila_ticket)

    _registrar_evento(
        ticket_id=ticket_id,
        evento="creado",
        estado_nuevo="sugerido",
        actor="sistema",
        nota=f"clasificado por gemini con confianza {clasificacion.confianza:.2f}",
    )

    return ticket_id


def obtener_ticket(ticket_id: str) -> dict:
    """trae un ticket por id, devuelve dict o None si no existe"""
    query = f"SELECT * FROM `{TABLA_TICKETS}` WHERE id = @ticket_id LIMIT 1"
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("ticket_id", "STRING", ticket_id)]
    )
    filas = list(_cliente.query(query, job_config=job_config).result())
    if not filas:
        return None
    return dict(filas[0])


def aprobar_ticket(ticket_id: str, actor: str, prioridad_override: str = None) -> dict:
    """convierte ticket de sugerido a abierto, opcionalmente corrige prioridad"""
    ticket = obtener_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"ticket {ticket_id} no existe")
    if ticket["estado"] != "sugerido":
        raise ValueError(f"ticket {ticket_id} no está en estado sugerido (está: {ticket['estado']})")

    ahora = datetime.now(timezone.utc)
    prioridad_final = prioridad_override or ticket["prioridad"]
    sla_vence = ahora + timedelta(minutes=SLA_MINUTOS[prioridad_final])

    query = f"""
        UPDATE `{TABLA_TICKETS}`
        SET estado = 'abierto',
            prioridad = @prioridad,
            asignado_a = @asignado,
            sla_vence_en = @sla_vence,
            ultima_actividad = @ahora
        WHERE id = @ticket_id
    """
    _ejecutar_update(query, {
        "prioridad": ("STRING", prioridad_final),
        "asignado": ("STRING", actor),
        "sla_vence": ("TIMESTAMP", sla_vence.isoformat()),
        "ahora": ("TIMESTAMP", ahora.isoformat()),
        "ticket_id": ("STRING", ticket_id),
    })

    nota = f"aprobado por {actor}"
    if prioridad_override and prioridad_override != ticket["prioridad"]:
        nota += f", prioridad corregida de {ticket['prioridad']} a {prioridad_override}"

    _registrar_evento(
        ticket_id=ticket_id,
        evento="aprobado",
        estado_anterior="sugerido",
        estado_nuevo="abierto",
        actor=actor,
        nota=nota,
    )
    return {"prioridad_final": prioridad_final, "sla_vence": sla_vence}


def descartar_ticket(ticket_id: str, actor: str, motivo: str):
    """cierra el ticket sin crear trabajo real"""
    ticket = obtener_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"ticket {ticket_id} no existe")

    ahora = datetime.now(timezone.utc)
    query = f"""
        UPDATE `{TABLA_TICKETS}`
        SET estado = 'descartado',
            motivo_descarte = @motivo,
            ultima_actividad = @ahora
        WHERE id = @ticket_id
    """
    _ejecutar_update(query, {
        "motivo": ("STRING", motivo),
        "ahora": ("TIMESTAMP", ahora.isoformat()),
        "ticket_id": ("STRING", ticket_id),
    })

    _registrar_evento(
        ticket_id=ticket_id,
        evento="descartado",
        estado_anterior=ticket["estado"],
        estado_nuevo="descartado",
        actor=actor,
        nota=motivo,
    )


def tomar_ticket(ticket_id: str, actor: str):
    """soporte se autoasigna, pasa a en_progreso"""
    ticket = obtener_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"ticket {ticket_id} no existe")
    if ticket["estado"] not in ("abierto", "escalado"):
        raise ValueError(f"ticket {ticket_id} no se puede tomar en estado {ticket['estado']}")

    ahora = datetime.now(timezone.utc)
    query = f"""
        UPDATE `{TABLA_TICKETS}`
        SET estado = 'en_progreso',
            asignado_a = @asignado,
            ultima_actividad = @ahora
        WHERE id = @ticket_id
    """
    _ejecutar_update(query, {
        "asignado": ("STRING", actor),
        "ahora": ("TIMESTAMP", ahora.isoformat()),
        "ticket_id": ("STRING", ticket_id),
    })

    _registrar_evento(
        ticket_id=ticket_id,
        evento="tomado",
        estado_anterior=ticket["estado"],
        estado_nuevo="en_progreso",
        actor=actor,
    )


def escalar_ticket(ticket_id: str, actor: str, motivo: str):
    """pasa el ticket a N2"""
    ticket = obtener_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"ticket {ticket_id} no existe")

    ahora = datetime.now(timezone.utc)
    query = f"""
        UPDATE `{TABLA_TICKETS}`
        SET estado = 'escalado',
            ultima_actividad = @ahora
        WHERE id = @ticket_id
    """
    _ejecutar_update(query, {
        "ahora": ("TIMESTAMP", ahora.isoformat()),
        "ticket_id": ("STRING", ticket_id),
    })

    _registrar_evento(
        ticket_id=ticket_id,
        evento="escalado",
        estado_anterior=ticket["estado"],
        estado_nuevo="escalado",
        actor=actor,
        nota=motivo,
    )


def resolver_ticket(ticket_id: str, actor: str, comentario: str):
    """cierra el ticket con solución"""
    ticket = obtener_ticket(ticket_id)
    if not ticket:
        raise ValueError(f"ticket {ticket_id} no existe")

    ahora = datetime.now(timezone.utc)
    query = f"""
        UPDATE `{TABLA_TICKETS}`
        SET estado = 'resuelto',
            comentario_resolucion = @comentario,
            ultima_actividad = @ahora
        WHERE id = @ticket_id
    """
    _ejecutar_update(query, {
        "comentario": ("STRING", comentario),
        "ahora": ("TIMESTAMP", ahora.isoformat()),
        "ticket_id": ("STRING", ticket_id),
    })

    _registrar_evento(
        ticket_id=ticket_id,
        evento="resuelto",
        estado_anterior=ticket["estado"],
        estado_nuevo="resuelto",
        actor=actor,
        nota=comentario,
    )


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
    _insertar_evento_via_sql(fila)


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


def _ejecutar_update(query: str, parametros: dict):
    """helper para ejecutar updates con parametros nombrados"""
    query_params = [
        bigquery.ScalarQueryParameter(nombre, tipo, valor)
        for nombre, (tipo, valor) in parametros.items()
    ]
    job_config = bigquery.QueryJobConfig(query_parameters=query_params)
    _cliente.query(query, job_config=job_config).result()


def _insertar_ticket_via_sql(fila: dict):
    """inserta ticket usando dml, compatible con updates inmediatos"""
    query = f"""
        INSERT INTO `{TABLA_TICKETS}` (
            id, creado_en, origen, remitente, texto_original,
            tipo, estado, categoria, sistema_afectado,
            impacto, urgencia, prioridad, resumen,
            asignado_a, sla_vence_en, sugerencia_ia,
            motivo_descarte, comentario_resolucion, ultima_actividad
        ) VALUES (
            @id, @creado_en, @origen, @remitente, @texto_original,
            @tipo, @estado, @categoria, @sistema_afectado,
            @impacto, @urgencia, @prioridad, @resumen,
            @asignado_a, @sla_vence_en, PARSE_JSON(@sugerencia_ia),
            @motivo_descarte, @comentario_resolucion, @ultima_actividad
        )
    """
    parametros = [
        bigquery.ScalarQueryParameter("id", "STRING", fila["id"]),
        bigquery.ScalarQueryParameter("creado_en", "TIMESTAMP", fila["creado_en"]),
        bigquery.ScalarQueryParameter("origen", "STRING", fila["origen"]),
        bigquery.ScalarQueryParameter("remitente", "STRING", fila["remitente"]),
        bigquery.ScalarQueryParameter("texto_original", "STRING", fila["texto_original"]),
        bigquery.ScalarQueryParameter("tipo", "STRING", fila["tipo"]),
        bigquery.ScalarQueryParameter("estado", "STRING", fila["estado"]),
        bigquery.ScalarQueryParameter("categoria", "STRING", fila["categoria"]),
        bigquery.ScalarQueryParameter("sistema_afectado", "STRING", fila["sistema_afectado"]),
        bigquery.ScalarQueryParameter("impacto", "STRING", fila["impacto"]),
        bigquery.ScalarQueryParameter("urgencia", "STRING", fila["urgencia"]),
        bigquery.ScalarQueryParameter("prioridad", "STRING", fila["prioridad"]),
        bigquery.ScalarQueryParameter("resumen", "STRING", fila["resumen"]),
        bigquery.ScalarQueryParameter("asignado_a", "STRING", fila["asignado_a"]),
        bigquery.ScalarQueryParameter("sla_vence_en", "TIMESTAMP", fila["sla_vence_en"]),
        bigquery.ScalarQueryParameter("sugerencia_ia", "STRING", fila["sugerencia_ia"]),
        bigquery.ScalarQueryParameter("motivo_descarte", "STRING", fila["motivo_descarte"]),
        bigquery.ScalarQueryParameter("comentario_resolucion", "STRING", fila["comentario_resolucion"]),
        bigquery.ScalarQueryParameter("ultima_actividad", "TIMESTAMP", fila["ultima_actividad"]),
    ]
    job_config = bigquery.QueryJobConfig(query_parameters=parametros)
    _cliente.query(query, job_config=job_config).result()


def _insertar_evento_via_sql(fila: dict):
    """inserta evento usando dml, compatible con updates inmediatos"""
    query = f"""
        INSERT INTO `{TABLA_EVENTOS}` (
            id, ticket_id, evento, estado_anterior, estado_nuevo, actor, fecha, nota
        ) VALUES (
            @id, @ticket_id, @evento, @estado_anterior, @estado_nuevo, @actor, @fecha, @nota
        )
    """
    parametros = [
        bigquery.ScalarQueryParameter("id", "STRING", fila["id"]),
        bigquery.ScalarQueryParameter("ticket_id", "STRING", fila["ticket_id"]),
        bigquery.ScalarQueryParameter("evento", "STRING", fila["evento"]),
        bigquery.ScalarQueryParameter("estado_anterior", "STRING", fila["estado_anterior"]),
        bigquery.ScalarQueryParameter("estado_nuevo", "STRING", fila["estado_nuevo"]),
        bigquery.ScalarQueryParameter("actor", "STRING", fila["actor"]),
        bigquery.ScalarQueryParameter("fecha", "TIMESTAMP", fila["fecha"]),
        bigquery.ScalarQueryParameter("nota", "STRING", fila["nota"]),
    ]
    job_config = bigquery.QueryJobConfig(query_parameters=parametros)
    _cliente.query(query, job_config=job_config).result()