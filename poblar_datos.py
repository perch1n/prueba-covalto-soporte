"""genera tickets sinteticos para llenar el dashboard

crea ~60 tickets distribuidos en los ultimos 15 dias
con distintos estados, prioridades y sistemas para que
looker studio tenga datos ricos que mostrar
"""
import random
import time
from datetime import datetime, timezone, timedelta
from src.clasificador import clasificar
from src import ticket_store as store
from src.ticket_store import _cliente, TABLA_TICKETS, TABLA_EVENTOS, SLA_MINUTOS
from google.cloud import bigquery
import json
import uuid


# mensajes realistas por categoria, mezclados humanos y sistemas
MENSAJES = [
    # incidentes de sistemas (bots)
    ("sistema", "airflow-alerts@covalto.iam.gserviceaccount.com",
     "DAG ingesta_transacciones FAILED - task extract - TimeoutError después de 3 reintentos"),
    ("sistema", "airflow-alerts@covalto.iam.gserviceaccount.com",
     "DAG cierre_contable_diario FAILED - operator SqlSensor timeout waiting for source"),
    ("sistema", "dataflow-alerts@covalto.iam.gserviceaccount.com",
     "pipeline batch_scoring_riesgo failed - OOM error en worker node-3"),
    ("sistema", "monitoring@covalto.iam.gserviceaccount.com",
     "reporte_riesgo lag detectado, latencia 45min vs SLA de 15min"),
    ("sistema", "airflow-alerts@covalto.iam.gserviceaccount.com",
     "ingesta_transacciones lentitud detectada, ejecucion 2h vs promedio 40min"),
    ("sistema", "monitoring@covalto.iam.gserviceaccount.com",
     "plataforma_analitica CPU al 95% por más de 10 minutos"),
    ("sistema", "dataflow-alerts@covalto.iam.gserviceaccount.com",
     "job procesamiento_batch_diario finalizó con warnings, revisar logs"),
    ("sistema", "monitoring@covalto.iam.gserviceaccount.com",
     "autenticacion timeouts detectados en las últimas 2 horas"),

    # incidentes reportados por humanos
    ("humano", "diana.torres@covalto.com",
     "el reporte de riesgo sale con cifras raras desde temprano, faltan transacciones de ayer"),
    ("humano", "carlos.mendez@covalto.com",
     "no puedo cerrar el cierre contable, el dashboard muestra datos inconsistentes"),
    ("humano", "andrea.lopez@covalto.com",
     "la ingesta de ayer no cargó todos los registros, faltan como 300 transacciones"),
    ("humano", "pedro.ramirez@covalto.com",
     "el sistema de scoring está devolviendo scores extraños para clientes nuevos"),
    ("humano", "maria.gomez@covalto.com",
     "ingesta_transacciones lleva 3 horas sin procesar, urgente revisar"),
    ("humano", "julio.perez@covalto.com",
     "los datos de riesgo del reporte diario no cuadran con el core bancario"),
    ("humano", "ana.rojas@covalto.com",
     "la plataforma analitica está muy lenta, no puedo generar mis reportes"),

    # consultas de usuarios
    ("humano", "luis.pardo@covalto.com",
     "cómo pido acceso al dataset de cierre contable?"),
    ("humano", "sofia.diaz@covalto.com",
     "existe algún tutorial de cómo usar la plataforma analitica?"),
    ("humano", "diego.castro@covalto.com",
     "quién es el owner del dataset de scoring de riesgo?"),
    ("humano", "camila.silva@covalto.com",
     "cuál es el sla de procesamiento del cierre contable?"),

    # solicitudes de mejora
    ("humano", "roberto.vega@covalto.com",
     "podrian agregar una columna con el timestamp de última actualización?"),
    ("humano", "valentina.morales@covalto.com",
     "sería útil tener una alerta cuando el DAG tarde más de 1h"),
    ("humano", "sebastian.jimenez@covalto.com",
     "propuesta: mejorar el dashboard de riesgo con filtros por región"),

    # ruido / off-topic
    ("humano", "manuel.aguilar@covalto.com",
     "buenos días equipo, cómo va todo?"),
    ("humano", "patricia.reyes@covalto.com",
     "gracias por el update de la doc, quedó muy bien"),
    ("humano", "fernando.torres@covalto.com",
     "recordatorio: hoy es la reunión mensual a las 4pm"),
]


def crear_ticket_con_fecha(origen, remitente, texto, clasificacion, fecha_creacion):
    """crea un ticket con fecha custom en lugar de now"""
    ticket_id = store.generar_id_ticket()
    # forzamos que sea unico agregando aleatorio si hay colision
    ticket_id = f"{ticket_id}-{random.randint(100,999)}"

    prioridad = store.calcular_prioridad(clasificacion.impacto, clasificacion.urgencia)
    sla_vence = fecha_creacion + timedelta(minutes=SLA_MINUTOS[prioridad])

    fila = {
        "id": ticket_id,
        "creado_en": fecha_creacion.isoformat(),
        "origen": origen,
        "remitente": remitente,
        "texto_original": texto,
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
        "sugerencia_ia": store._serializar_sugerencia(clasificacion),
        "motivo_descarte": None,
        "comentario_resolucion": None,
        "ultima_actividad": fecha_creacion.isoformat(),
    }
    store._insertar_ticket_via_sql(fila)
    _insertar_evento_con_fecha(ticket_id, "creado", None, "sugerido", "sistema",
                                fecha_creacion, f"clasificado con confianza {clasificacion.confianza:.2f}")
    return ticket_id, prioridad


def _insertar_evento_con_fecha(ticket_id, evento, estado_anterior, estado_nuevo, actor, fecha, nota):
    """version del registrar_evento que permite fecha custom"""
    fila = {
        "id": str(uuid.uuid4()),
        "ticket_id": ticket_id,
        "evento": evento,
        "estado_anterior": estado_anterior,
        "estado_nuevo": estado_nuevo,
        "actor": actor,
        "fecha": fecha.isoformat(),
        "nota": nota,
    }
    store._insertar_evento_via_sql(fila)


def actualizar_ticket_con_fecha(ticket_id, updates, fecha):
    """update de campos con fecha custom en ultima_actividad"""
    set_clauses = []
    parametros = []
    for campo, (tipo, valor) in updates.items():
        set_clauses.append(f"{campo} = @{campo}")
        parametros.append(bigquery.ScalarQueryParameter(campo, tipo, valor))

    set_clauses.append("ultima_actividad = @ultima_actividad")
    parametros.append(bigquery.ScalarQueryParameter("ultima_actividad", "TIMESTAMP", fecha.isoformat()))
    parametros.append(bigquery.ScalarQueryParameter("ticket_id", "STRING", ticket_id))

    query = f"UPDATE `{TABLA_TICKETS}` SET {', '.join(set_clauses)} WHERE id = @ticket_id"
    job_config = bigquery.QueryJobConfig(query_parameters=parametros)
    _cliente.query(query, job_config=job_config).result()


AGENTES = [
    "soporte@covalto.com",
    "carolina@covalto.com",
    "andres@covalto.com",
    "senior1@covalto.com",
]


def simular_ciclo_vida(ticket_id, prioridad, fecha_creacion, distribucion_estado):
    """simula un ciclo de vida realista: aprobar, tomar, resolver, escalar, descartar"""
    if distribucion_estado == "sugerido":
        return  # se queda pendiente

    if distribucion_estado == "descartado":
        fecha_descarte = fecha_creacion + timedelta(minutes=random.randint(5, 60))
        actualizar_ticket_con_fecha(ticket_id, {
            "estado": ("STRING", "descartado"),
            "motivo_descarte": ("STRING", "no es un incidente, es una consulta general"),
        }, fecha_descarte)
        _insertar_evento_con_fecha(ticket_id, "descartado", "sugerido", "descartado",
                                    random.choice(AGENTES), fecha_descarte, "no aplica como incidente")
        return

    # aprobar
    fecha_aprobado = fecha_creacion + timedelta(minutes=random.randint(3, 30))
    actualizar_ticket_con_fecha(ticket_id, {
        "estado": ("STRING", "abierto"),
        "asignado_a": ("STRING", random.choice(AGENTES)),
    }, fecha_aprobado)
    _insertar_evento_con_fecha(ticket_id, "aprobado", "sugerido", "abierto",
                                random.choice(AGENTES), fecha_aprobado, "aprobado")

    if distribucion_estado == "abierto":
        return

    # tomar
    fecha_tomado = fecha_aprobado + timedelta(minutes=random.randint(5, 120))
    actualizar_ticket_con_fecha(ticket_id, {
        "estado": ("STRING", "en_progreso"),
    }, fecha_tomado)
    _insertar_evento_con_fecha(ticket_id, "tomado", "abierto", "en_progreso",
                                random.choice(AGENTES), fecha_tomado, None)

    if distribucion_estado == "en_progreso":
        return

    # posible escalamiento (30% de probabilidad)
    if random.random() < 0.3:
        fecha_escalado = fecha_tomado + timedelta(minutes=random.randint(30, 180))
        actualizar_ticket_con_fecha(ticket_id, {
            "estado": ("STRING", "escalado"),
        }, fecha_escalado)
        _insertar_evento_con_fecha(ticket_id, "escalado", "en_progreso", "escalado",
                                    random.choice(AGENTES), fecha_escalado, "requiere expertise senior")

        if distribucion_estado == "escalado":
            return
        fecha_tomado = fecha_escalado + timedelta(minutes=random.randint(10, 60))
        actualizar_ticket_con_fecha(ticket_id, {
            "estado": ("STRING", "en_progreso"),
            "asignado_a": ("STRING", "senior1@covalto.com"),
        }, fecha_tomado)
        _insertar_evento_con_fecha(ticket_id, "tomado", "escalado", "en_progreso",
                                    "senior1@covalto.com", fecha_tomado, "tomado por senior")

    # resolver
    tiempo_resolucion_min = {"P0": (30, 120), "P1": (60, 480), "P2": (120, 1440), "P3": (240, 3000)}
    minutos = random.randint(*tiempo_resolucion_min.get(prioridad, (60, 480)))
    fecha_resuelto = fecha_tomado + timedelta(minutes=minutos)

    comentarios = [
        "reprocesado el batch fallido, datos correctos",
        "reindexado tabla origen, ingesta restaurada",
        "ajuste de configuracion en el DAG, ejecutando ok",
        "escalado a plataforma, fix aplicado",
        "resuelto con retry manual, monitoreando",
    ]
    actualizar_ticket_con_fecha(ticket_id, {
        "estado": ("STRING", "resuelto"),
        "comentario_resolucion": ("STRING", random.choice(comentarios)),
    }, fecha_resuelto)
    _insertar_evento_con_fecha(ticket_id, "resuelto", "en_progreso", "resuelto",
                                random.choice(AGENTES), fecha_resuelto, "cerrado con solución")


def main():
    total = 60
    print(f"generando {total} tickets sinteticos...")
    print("esto tarda ~3-5 minutos porque cada uno llama a gemini\n")

    # distribucion de estados finales para que el dashboard se vea real
    distribucion = (
        ["resuelto"] * 40 +
        ["en_progreso"] * 7 +
        ["abierto"] * 5 +
        ["escalado"] * 3 +
        ["descartado"] * 3 +
        ["sugerido"] * 2
    )
    random.shuffle(distribucion)

    exitosos = 0
    for i in range(total):
        origen, remitente, texto = random.choice(MENSAJES)
        # fecha aleatoria en los ultimos 15 dias
        dias_atras = random.randint(0, 14)
        horas_atras = random.randint(0, 23)
        fecha = datetime.now(timezone.utc) - timedelta(days=dias_atras, hours=horas_atras)

        try:
            clasificacion = clasificar(texto)
            ticket_id, prioridad = crear_ticket_con_fecha(origen, remitente, texto, clasificacion, fecha)
            simular_ciclo_vida(ticket_id, prioridad, fecha, distribucion[i])
            exitosos += 1
            print(f"  [{i+1}/{total}] {ticket_id} - {prioridad} - {distribucion[i]}")
            time.sleep(0.3)  # evitar rate limits de gemini
        except Exception as e:
            print(f"  [{i+1}/{total}] ERROR: {e}")

    print(f"\ncompletados: {exitosos}/{total} tickets")


if __name__ == "__main__":
    main()