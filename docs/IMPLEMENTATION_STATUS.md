# Estado de implementación y cierre de Etapa 1

Fecha de corte documental: 2026-08-07 (America/Santiago).

## Estado del gate

La implementación de Etapas 0 y 1 está en estado
**CORRECTIVE_CANDIDATE_STAGE1_VERIFIED**. Los once hallazgos P1 quedaron
cerrados sobre el candidato funcional
6374e60ce74ebb2a1ee0ec80531eab218d1b9548. El snapshot f982ef89 y el primer
intento de cierre 5b13428ace03ef2852ef3f6f1b942e54151a5204 fueron rechazados
por auditoría independiente y se conservan solo como historia. El candidato
correctivo 4bab5b400199b94f2fd003c7f959b4d341363b26 elimina el residuo
histórico de capabilities en PostgreSQL, impone el invariante también en la
base y corrige la exigencia de procedencia CI. La decisión definitiva
READY_FOR_STAGE_2 se emite únicamente después de:

1. crear el último commit documental, denominado FINAL_STAGE1_SHA;
2. construir y desplegar ese SHA exacto;
3. generar el paquete de evidencia externo;
4. completar la auditoría independiente de solo lectura.

Un commit no puede contener de forma verificable su propio hash ni los
identificadores del build que se ejecuta después de publicarlo. Por eso esos
valores finales viven en el manifest externo y no se sustituyen posteriormente
en este archivo. No se harán commits después de FINAL_STAGE1_SHA.

## Identidad de los candidatos verificados

| Elemento | Valor |
|---|---|
| Repositorio | WilJms/PruebasPersonalizadas |
| Rama | fix/stage1-external-readiness |
| PR | #1, abierto y draft |
| Candidato funcional completo | 6374e60ce74ebb2a1ee0ec80531eab218d1b9548 |
| Candidato correctivo | 4bab5b400199b94f2fd003c7f959b4d341363b26 |
| CI correctivo push | 31209547327, SUCCESS, 7/7 jobs |
| CI correctivo pull request | 31209552197, SUCCESS, 7/7 jobs |
| Merge CI correctivo | 1e695278b5ea25d5e94756e67eb9f47c11ecdde0 = merge(dadaaa7, 4bab5b4) |
| Cloud Build correctivo | 745eb275-eea4-4493-8b64-293570472265, SUCCESS |
| Digest correctivo | sha256:7d73b1cb7a438f6f8adb8de10f31752efdbca860e1aa08c9314097d4e5daed7a |
| Runtime correctivo | cva-web generación 11 y cva-worker generación 11, Ready, mismo digest |
| Terraform correctivo | imagen 0/2/0; dos planes vivos consecutivos exit 0 |

El build correctivo fue disparado por la conexión regional al repositorio
autorizado, registró source exacto del candidato, produjo dos occurrences de
provenance verificada, SLSA nivel 3 y análisis terminado sin vulnerabilidades.
El SBOM y la cadena del SHA definitivo se vuelven a capturar en el artifact
externo posterior a FINAL_STAGE1_SHA.
Terraform continúa siendo el único escritor del deployment.

## Gates implementados

| Boundary | Estado | Evidencia resumida |
|---|---|---|
| Contratos canónicos | PASS | Schema 1.1.0, 46 roots, 112 definiciones, 231 referencias y 8 fixtures. |
| PrincipalId | PASS | Principales externos aceptan UUID Supabase sin ampliar Id globalmente. |
| OpenAPI | PASS | DTOs tipados, responses validadas, snapshot determinista y consumer/provider tests. |
| Backend y Stage 0 | PASS | 163 pruebas locales verdes; 7 PostgreSQL-only ejecutadas aparte; 10 pruebas de artifacts de deploy. |
| Review UX | PASS | Blueprint, SelectedQuestion, CHOICE y Guide proyectan la trazabilidad requerida. |
| Evidence-first | PASS | Receipt durable por fragmento; replay sin URL persistida y ligado a autorización vigente; aprobación server-side. |
| Frontend | PASS | Typecheck, 19 tests, build, audit sin vulnerabilidades y Playwright crítico. |
| PostgreSQL | PASS | PG16 y PG17: dos migraciones, 24 tablas/RLS, 2 triggers, constraint de idempotencia y matriz repetida dos veces sin limpieza. |
| Logging | PASS | Access log deshabilitado; 650 eventos JSON por plantilla; scan de 2.881 entradas sin capability, credencial ni payload sintético. |
| GitHub a Cloud Build | PASS | Connection, repository y trigger regionales limitados al repo; build SA sin Run Admin. |
| Supply chain | PASS E1 | Bases por digest, locks con hashes, Actions por SHA, provenance, scan y SBOM ligados al digest. |
| Terraform | PASS | Scaling superior declarado; apply revisado; dos planes vivos consecutivos exit 0. |
| Cloud runtime | PASS candidato correctivo | Health/readiness 200, privado 401, mismo digest, secretos version 2, Service/Job Ready, 1/1/0 y mock/P10 off. |
| Supabase | PASS candidato correctivo | Proyecto correcto, PostgreSQL 17, Auth sintético, constraint validado y cero descriptores inseguros/JSON null. |
| Cloudflare R2 | PASS candidato | Bucket privado correcto, CORS/lifecycle exactos, r2.dev off y cero dominios. |
| Browser cloud | PASS candidato + correctivo | Recorrido completo nuevo en 6374e60; cierre/reapertura desde raíz y recuperación de Assessment/Guide sobre el digest 4bab5b4. |

## Correcciones principales

- lista autenticada de actividades y acciones de continuación derivadas desde
  estado durable del servidor;
- edición de actividad draft con ETag/If-Match y preflight de costo;
- blueprint y assessment review completos, dificultad derivada de solo lectura
  y separación explícita entre contenido estudiantil y datos del evaluador;
- alternativas CHOICE visibles, exactamente una mejor respuesta y
  misconceptions/rationales reservados al evaluador;
- receipt evidence-first durable por fragmento antes de aprobar;
- replay idempotente ligado a principal, rol y permiso actuales; los
  descriptores de upload, export y evidence verify no contienen capabilities;
- migración de higiene que elimina reservas legacy JSON null/capabilities y
  constraint PostgreSQL validado que impide volver a persistirlas;
- EvaluationGuide visible con observables, evidencia, fuentes, niveles,
  alternativas, misconceptions y cannot_infer;
- frontera OpenAPI tipada desde DTOs que componen contratos canónicos; las
  rutas con response_model retornan DTOs y no objetos Response que omitan la
  validación runtime;
- PrincipalId aplicado solo a actores/principales externos;
- logs HTTP estructurados por plantilla de ruta, sin URL, query, payload ni
  capability;
- worker separado de settings web y sin secreto de sesión;
- CI PostgreSQL 16/17, navegador E2E, dependencias fijadas y build verificable;
- Terraform convergente y trigger GitHub a Cloud Build de mínimo privilegio;
- documentos SPA no-store, assets hashados inmutables y epoch de shell que
  purga solo la caché HTTP de clientes anteriores sin borrar su sesión.

Durante la verificación del candidato, una invocación fallida de un cliente
PostgreSQL incluyó una credencial en su diagnóstico. Esa salida se invalidó y
se excluye de evidencia: la contraseña Supabase fue rotada mediante la API
oficial, la credencial anterior quedó denegada, Secret Manager recibió la
versión 2 y Terraform actualizó únicamente las referencias de secretos de
Service/Job. No se conserva ni reproduce el valor.

## Estado de Etapa 0 y Etapa 1

- E0-01 a E0-08: PASS.
- E1-01 a E1-11: PASS en implementación y candidato cloud.
- P0: 0.
- P1: 0 abiertos.
- P2/P3 residuales: solo deuda no bloqueante descrita en
  [STAGE1_FINAL_REMEDIATION_BACKLOG.md](audits/STAGE1_FINAL_REMEDIATION_BACKLOG.md).

La matriz detallada está en
[STAGE1_FINAL_ACCEPTANCE_MATRIX.md](audits/STAGE1_FINAL_ACCEPTANCE_MATRIX.md).

## Frontera preservada

La revisión humana académica del producto se conserva para blueprint y
Assessment. La verificación de ingeniería se realiza mediante pruebas,
evidencia y agentes de IA; no existe un gate humano de revisión de código.

No se implementó batch, retry/cancel general, acciones o regeneración por
pregunta, aprobación masiva, feedback/métricas E2, DOCX completo, OCR, LMS,
calificación, detección de IA, múltiples submissions ni proveedor IA real.
El modo cloud permanece mock y P10 permanece deshabilitado.

No se hizo merge ni tag. El PR debe permanecer draft hasta que el propietario
dé una instrucción posterior.
