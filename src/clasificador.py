"""clasifica mensajes de soporte usando gemini"""
import json
from dataclasses import dataclass
from google import genai
from google.genai import types
from src import config

# catálogo cerrado de sistemas, gemini no puede inventar
SISTEMAS = [
    "ingesta_transacciones",
    "reporte_riesgo",
    "cierre_contable",
    "plataforma_analitica",
    "autenticacion",
    "desconocido",
]

# schema que fuerza a gemini a devolver json con estos campos exactos
SCHEMA = {
    "type": "object",
    "properties": {
        "categoria": {"type": "string", "enum": ["incidente", "consulta", "solicitud", "ruido"]},
        "sistema_afectado": {"type": "string", "enum": SISTEMAS},
        "impacto": {"type": "string", "enum": ["bajo", "medio", "alto"]},
        "urgencia": {"type": "string", "enum": ["baja", "media", "alta"]},
        "resumen": {"type": "string"},
        "confianza": {"type": "number"},
    },
    "required": ["categoria", "sistema_afectado", "impacto", "urgencia", "resumen", "confianza"],
}

INSTRUCCIONES = """Eres un clasificador de tickets de soporte para una fintech.
Recibes texto libre y devuelves JSON con categoría, sistema afectado, impacto,
urgencia, resumen corto y nivel de confianza.

Usa 'desconocido' si el sistema no está claro, no inventes nombres.
Si el mensaje es saludo u off-topic, categoría='ruido'.
No repitas datos sensibles (cédulas, cuentas) en el resumen."""


@dataclass
class Resultado:
    categoria: str
    sistema_afectado: str
    impacto: str
    urgencia: str
    resumen: str
    confianza: float


def clasificar(texto: str) -> Resultado:
    cliente = genai.Client(vertexai=True, project=config.PROYECTO, location=config.UBICACION)
    respuesta = cliente.models.generate_content(
        model=config.MODELO,
        contents=texto,
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCCIONES,
            response_mime_type="application/json",
            response_schema=SCHEMA,
            temperature=0.1,
        ),
    )
    data = json.loads(respuesta.text)
    return Resultado(**data)