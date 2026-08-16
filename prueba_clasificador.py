"""prueba end to end: clasificar y guardar en bigquery"""
from src.clasificador import clasificar
from src.ticket_store import crear_ticket

casos = [
    {
        "origen": "humano",
        "remitente": "diana.torres@covalto.com",
        "texto": "el reporte de riesgo sale con cifras raras desde temprano",
    },
    {
        "origen": "sistema",
        "remitente": "airflow-alerts@covalto.iam.gserviceaccount.com",
        "texto": "ingesta_transacciones FAILED - task extract - TimeoutError",
    },
    {
        "origen": "humano",
        "remitente": "luis.pardo@covalto.com",
        "texto": "buenos días equipo, cómo va todo?",
    },
]

for caso in casos:
    print(f"\ntexto: {caso['texto'][:60]}")
    clasificacion = clasificar(caso["texto"])
    print(f"  clasificado: {clasificacion.categoria} | {clasificacion.sistema_afectado} | confianza {clasificacion.confianza:.2f}")

    ticket_id = crear_ticket(
        origen=caso["origen"],
        remitente=caso["remitente"],
        texto_original=caso["texto"],
        clasificacion=clasificacion,
    )
    print(f"  guardado: {ticket_id}")