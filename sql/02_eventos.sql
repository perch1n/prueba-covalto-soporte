CREATE TABLE `prueba-covalto-data.covalto_soporte.eventos_ticket` (
  id STRING NOT NULL,
  ticket_id STRING NOT NULL,
  evento STRING NOT NULL,
  estado_anterior STRING,
  estado_nuevo STRING,
  actor STRING NOT NULL,
  fecha TIMESTAMP NOT NULL,
  nota STRING
)
PARTITION BY DATE(fecha)
CLUSTER BY ticket_id;