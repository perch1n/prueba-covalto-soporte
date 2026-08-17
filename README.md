# Sistema de Soporte por Eventos - Covalto

Sistema que reemplaza el desorden de reportes en canales de chat con un flujo estructurado: mensajes clasificados con IA, revisión humana antes de crear tickets, y visibilidad operativa en un tablero.

Prueba técnica · Fabián Gómez · Agosto 2026

Repo: https://github.com/perch1n/prueba-covalto-soporte
Dashboard: https://datastudio.google.com/reporting/31eaddcd-4d8a-487f-a38f-fa39c753d09e

---

## Contexto

En Covalto los reportes de usuarios (analistas de riesgo, comercial, finanzas) llegan mezclados con alertas de sistemas (Airflow, Dataflow) en el mismo canal de chat. Nada queda registrado, no hay métricas de respuesta y los problemas se resuelven de memoria.

Este sistema atiende ese vacío: ingiere todo, clasifica con Gemini, pide validación humana y guarda el ciclo completo en BigQuery.

---

## Arquitectura

```
Usuarios y bots
      ↓
Canal de mensajería (CLI en el MVP, Google Chat en producción)
      ↓
Ingestor           ← distingue humano vs bot por el remitente
      ↓
Clasificador       ← Gemini 2.5 Flash con schema estructurado
      ↓
BigQuery           ← tabla tickets + tabla eventos_ticket
      ↓
Looker Studio      ← tablero operativo
```

Piezas concretas del MVP:

- Ingestor y CLI en Python
- Clasificador contra Vertex AI (Gemini 2.5 Flash)
- Persistencia en BigQuery con DML (particionada y clustered)
- Tablero en Looker Studio conectado directamente a BigQuery

---

## Modelo de datos

Dos tablas en el dataset `covalto_soporte`:

**`tickets`** — todo lo que entra al sistema. Los descartados también son tickets pero con estado `descartado`. Esto permite medir la calidad del clasificador sin duplicar tablas.

Campos clave: `id`, `estado`, `origen`, `impacto`, `urgencia`, `prioridad`, `sistema_afectado`, `sla_vence_en`, `sugerencia_ia` (JSON con lo que sugirió la IA).

**`eventos_ticket`** — log append-only de cada cambio de estado. Permite reconstruir el ciclo de vida completo, calcular tiempos entre transiciones y cumplir auditoría.

Campos clave: `ticket_id`, `evento`, `estado_anterior`, `estado_nuevo`, `actor`, `fecha`.

Ambas particionadas por fecha y clustered por columnas de acceso frecuente.

---

## Priorización

Se usa la matriz ITIL: **prioridad = f(impacto, urgencia)**.

|  | Urgencia baja | Urgencia media | Urgencia alta |
|---|---|---|---|
| **Impacto alto** | P2 | P1 | P0 |
| **Impacto medio** | P3 | P2 | P1 |
| **Impacto bajo** | P3 | P3 | P2 |

Gemini estima impacto y urgencia (dos ejes objetivos), y el sistema calcula la prioridad de forma determinista. Esto es más auditable que dejar que la IA decida directamente.

SLA por prioridad: P0 = 2h · P1 = 8h · P2 = 24h · P3 = 5 días.

---

## Flujo end-to-end

1. Un usuario reporta con `/reportar <mensaje>`.
2. El sistema clasifica con Gemini (esquema JSON estructurado con enums cerrados).
3. Calcula prioridad con la matriz ITIL.
4. Crea el ticket en estado `sugerido`.
5. El soporte revisa y decide: `/crear <id> [prioridad=P0]` o `/descartar <id> <motivo>`.
6. Ciclo del ticket: `abierto` → `en_progreso` → `resuelto` (con `escalado` posible en el medio).
7. Cada transición registra un evento en `eventos_ticket`.

---

## Comandos del CLI

| Comando | Efecto |
|---|---|
| `/reportar <mensaje>` | Ingresa reporte, dispara clasificación |
| `/crear <id> [prioridad=P0]` | Convierte sugerencia en ticket, opcional corrección |
| `/descartar <id> <motivo>` | Cierra sin crear ticket |
| `/tomar <id>` | Se autoasigna, pasa a `en_progreso` |
| `/escalar <id> <motivo>` | Pasa a N2 |
| `/resolver <id> <comentario>` | Cierra con solución |
| `/salir` | Sale del CLI |

---

## Estructura del repo

```
prueba-covalto-soporte/
├── sql/
│   ├── 01_tickets.sql
│   └── 02_eventos.sql
├── src/
│   ├── __init__.py
│   ├── config.py           # lee .env
│   ├── clasificador.py     # gemini con schema estructurado
│   ├── ticket_store.py     # crud contra bigquery
│   └── cli.py              # cli interactivo
├── prueba_clasificador.py  # prueba aislada del clasificador
├── poblar_datos.py         # datos sinteticos para el dashboard
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Cómo correrlo

Requisitos: Python 3.11+, `gcloud` instalado, cuenta GCP con billing activo, Vertex AI y BigQuery habilitados.

```bash
# clonar
git clone https://github.com/perch1n/prueba-covalto-soporte.git
cd prueba-covalto-soporte

# entorno virtual
python -m venv venv
.\venv\Scripts\Activate.ps1   # Windows
# source venv/bin/activate    # Linux/Mac

pip install -r requirements.txt

# configurar variables
cp .env.example .env
# editar .env con tu project id

# autenticacion GCP
gcloud auth application-default login
gcloud config set project prueba-covalto-data
gcloud auth application-default set-quota-project prueba-covalto-data

# habilitar apis
gcloud services enable bigquery.googleapis.com aiplatform.googleapis.com

# crear dataset y tablas
bq --location=us-central1 mk --dataset prueba-covalto-data:covalto_soporte
Get-Content sql\01_tickets.sql | bq query --use_legacy_sql=false --project_id=prueba-covalto-data
Get-Content sql\02_eventos.sql | bq query --use_legacy_sql=false --project_id=prueba-covalto-data

# ejecutar el cli
python -m src.cli

# poblar datos sinteticos para el dashboard
python poblar_datos.py
```

---

## Dashboard

Publicado en Looker Studio, conectado directamente a BigQuery:

https://datastudio.google.com/reporting/31eaddcd-4d8a-487f-a38f-fa39c753d09e

Incluye:
- KPIs generales (total, abiertos, P0 críticos, resueltos)
- Distribución por estado y prioridad
- Tickets por sistema afectado
- Evolución en el tiempo

---

## Decisiones de diseño (las que vale la pena defender)

**Una sola tabla `tickets` con estado `descartado`, no dos tablas separadas.** Es como lo hacen Jira Service Management y Zendesk. Un descarte es información valiosa para medir la calidad del clasificador, no un caso aparte que se guarda en otro lado.

**La prioridad se calcula, no se le pide a la IA.** Gemini estima impacto y urgencia; el sistema aplica la matriz ITIL. En banca esta trazabilidad es obligatoria y así puedo explicar exactamente por qué un ticket es P0.

**Human-in-the-loop.** Nada se activa automáticamente, la IA sugiere y el humano decide. Esto evita errores automatizados en producción, genera datos etiquetados para mejorar el clasificador, y da control sobre casos ambiguos.

**DML en vez de streaming inserts en BigQuery.** El streaming buffer bloquea UPDATE por hasta 90 minutos. Como el ciclo de vida del ticket requiere actualizar seguido, `INSERT ... VALUES` con parámetros nombrados es la opción correcta.

**Structured output con enums cerrados.** Gemini no puede inventar sistemas que no existen. Si el mensaje habla de algo desconocido, devuelve `desconocido`. Es una defensa contra alucinaciones.

**Particionamiento y clustering desde el inicio.** Con el volumen actual el impacto es mínimo, pero es la práctica correcta y escala sin cambios.

**BigQuery como capa única en el MVP.** Es un trade-off consciente: en producción separaría transaccional (Cloud SQL) y analítico (BigQuery) con CDC via Datastream. Para 2 días de MVP, la separación es sobreingeniería.

---

## Qué queda para v2

- **Chat App real en Apps Script** conectada a Google Chat. El backend queda igual, solo cambia el adapter de entrada.
- **Runbooks ejecutables en 4 niveles** (documentado → sugerido → aprobado → auto). Cloud Functions dedicadas con service accounts de permisos mínimos.
- **SLA watcher automático** con Cloud Scheduler ejecutando cada 5 min.
- **Correlación humano ↔ sistema** cuando hay reportes duplicados sobre el mismo componente.
- **Redacción de PII explícita** con regex antes de cada llamada a Gemini (para tarjetas, cédulas, cuentas). Actualmente el prompt le pide a Gemini que no las repita, pero un módulo separado es más robusto.
- **Cloud SQL Postgres como transaccional** con Datastream sincronizando a BigQuery. Es el diseño de producción real.

---

## Stack

Python 3.11, Google Cloud (BigQuery + Vertex AI Gemini 2.5 Flash), Looker Studio, Git.

Librerías: `google-genai`, `google-cloud-bigquery`, `python-dotenv`.