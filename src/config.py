"""configuración leída desde .env"""
import os
from dotenv import load_dotenv

load_dotenv()

PROYECTO = os.getenv("GCP_PROJECT_ID")
UBICACION = os.getenv("GCP_LOCATION")
MODELO = os.getenv("GEMINI_MODEL")
DATASET = os.getenv("BQ_DATASET")