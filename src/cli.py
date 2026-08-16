"""cli interactivo que simula un canal de google chat"""
import shlex
from src.clasificador import clasificar
from src import ticket_store as store

# usuario actual del cli (soporte que ejecuta comandos)
SOPORTE = "soporte@covalto.com"

BANNER = """
╔══════════════════════════════════════════════════════════════╗
║      canal #incidents - sistema de soporte covalto           ║
║      soporte: soporte@covalto.com                             ║
╚══════════════════════════════════════════════════════════════╝

comandos disponibles:
  /reportar <mensaje>           - reportar un incidente (usuario)
  /crear <id> [prioridad=P0]    - aprobar sugerencia como ticket
  /descartar <id> <motivo>      - descartar sugerencia
  /tomar <id>                   - tomar ticket como soporte
  /escalar <id> <motivo>        - pasar a N2
  /resolver <id> <comentario>   - cerrar ticket
  /salir                        - salir del cli
"""


def procesar_reportar(argumentos: str):
    """crea reporte a partir del texto libre del usuario"""
    if not argumentos:
        print("uso: /reportar <mensaje>")
        return
    texto = argumentos
    clasificacion = clasificar(texto)
    ticket_id = store.crear_ticket(
        origen="humano",
        remitente="usuario@covalto.com",
        texto_original=texto,
        clasificacion=clasificacion,
    )
    print(f"\n📥 reporte {ticket_id} recibido")
    print(f"   sugerencia ia: {clasificacion.categoria} | {clasificacion.sistema_afectado}")
    print(f"   impacto/urgencia: {clasificacion.impacto}/{clasificacion.urgencia}")
    print(f"   confianza: {clasificacion.confianza:.2f}")
    print(f"   resumen: {clasificacion.resumen}")
    print(f"\n   soporte decide:")
    print(f"   /crear {ticket_id}                    - aceptar")
    print(f"   /crear {ticket_id} prioridad=P0       - corregir y aceptar")
    print(f"   /descartar {ticket_id} <motivo>       - no crear ticket")


def procesar_crear(argumentos: str):
    """aprueba una sugerencia, opcionalmente corrige prioridad"""
    partes = shlex.split(argumentos)
    if not partes:
        print("uso: /crear <id> [prioridad=P0]")
        return
    ticket_id = partes[0]
    prioridad_override = None
    for p in partes[1:]:
        if p.startswith("prioridad="):
            prioridad_override = p.split("=")[1].upper()
    try:
        resultado = store.aprobar_ticket(ticket_id, SOPORTE, prioridad_override)
        print(f"\n✅ ticket {ticket_id} creado")
        print(f"   prioridad final: {resultado['prioridad_final']}")
        print(f"   asignado a: {SOPORTE}")
        print(f"   sla vence: {resultado['sla_vence'].strftime('%Y-%m-%d %H:%M UTC')}")
    except ValueError as e:
        print(f"❌ {e}")


def procesar_descartar(argumentos: str):
    """descarta una sugerencia con motivo"""
    partes = shlex.split(argumentos)
    if len(partes) < 2:
        print("uso: /descartar <id> <motivo>")
        return
    ticket_id = partes[0]
    motivo = " ".join(partes[1:])
    try:
        store.descartar_ticket(ticket_id, SOPORTE, motivo)
        print(f"\n🗑️  ticket {ticket_id} descartado")
        print(f"   motivo: {motivo}")
    except ValueError as e:
        print(f"❌ {e}")


def procesar_tomar(argumentos: str):
    """soporte se autoasigna el ticket"""
    ticket_id = argumentos.strip()
    if not ticket_id:
        print("uso: /tomar <id>")
        return
    try:
        store.tomar_ticket(ticket_id, SOPORTE)
        print(f"\n🔧 ticket {ticket_id} en_progreso, asignado a {SOPORTE}")
    except ValueError as e:
        print(f"❌ {e}")


def procesar_escalar(argumentos: str):
    """escala el ticket a N2"""
    partes = shlex.split(argumentos)
    if len(partes) < 2:
        print("uso: /escalar <id> <motivo>")
        return
    ticket_id = partes[0]
    motivo = " ".join(partes[1:])
    try:
        store.escalar_ticket(ticket_id, SOPORTE, motivo)
        print(f"\n⚠️  ticket {ticket_id} escalado a N2")
        print(f"   motivo: {motivo}")
    except ValueError as e:
        print(f"❌ {e}")


def procesar_resolver(argumentos: str):
    """cierra el ticket con comentario"""
    partes = shlex.split(argumentos)
    if len(partes) < 2:
        print("uso: /resolver <id> <comentario>")
        return
    ticket_id = partes[0]
    comentario = " ".join(partes[1:])
    try:
        store.resolver_ticket(ticket_id, SOPORTE, comentario)
        print(f"\n✔️  ticket {ticket_id} resuelto")
        print(f"   comentario: {comentario}")
    except ValueError as e:
        print(f"❌ {e}")


COMANDOS = {
    "/reportar": procesar_reportar,
    "/crear": procesar_crear,
    "/descartar": procesar_descartar,
    "/tomar": procesar_tomar,
    "/escalar": procesar_escalar,
    "/resolver": procesar_resolver,
}


def main():
    print(BANNER)
    while True:
        try:
            linea = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nchao")
            break

        if not linea:
            continue
        if linea == "/salir":
            print("chao")
            break

        # separar comando y argumentos
        partes = linea.split(maxsplit=1)
        comando = partes[0]
        argumentos = partes[1] if len(partes) > 1 else ""

        handler = COMANDOS.get(comando)
        if not handler:
            print(f"comando no reconocido: {comando}")
            continue

        try:
            handler(argumentos)
        except Exception as e:
            print(f"❌ error inesperado: {e}")


if __name__ == "__main__":
    main()