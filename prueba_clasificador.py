"""script de prueba del clasificador"""
from src.clasificador import clasificar

casos = [
    "el reporte de riesgo sale con cifras raras desde temprano",
    "ingesta_transacciones FAILED - task extract - TimeoutError",
    "buenos días equipo, cómo va todo?",
    "cómo pido acceso al dataset de cierre contable?",
]

for texto in casos:
    print(f"\ntexto: {texto[:60]}")
    r = clasificar(texto)
    print(f"  categoria: {r.categoria}")
    print(f"  sistema: {r.sistema_afectado}")
    print(f"  impacto/urgencia: {r.impacto}/{r.urgencia}")
    print(f"  confianza: {r.confianza:.2f}")
    print(f"  resumen: {r.resumen}")