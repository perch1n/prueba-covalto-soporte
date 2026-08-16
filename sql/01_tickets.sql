CREATE TABLE `prueba-covalto-data.covalto_soporte.tickets` (
  id STRING NOT NULL,
  creado_en TIMESTAMP NOT NULL,
  origen STRING NOT NULL,
  remitente STRING NOT NULL,
  texto_original STRING NOT NULL,
  tipo STRING,
  estado STRING NOT NULL,
  categoria STRING,
  sistema_afectado STRING,
  impacto STRING,
  urgencia STRING,
  prioridad STRING,
  resumen STRING,
  asignado_a STRING,
  sla_vence_en TIMESTAMP,
  sugerencia_ia JSON,
  motivo_descarte STRING,
  comentario_resolucion STRING,
  ultima_actividad TIMESTAMP NOT NULL
)
PARTITION BY DATE(creado_en)
CLUSTER BY estado, prioridad;