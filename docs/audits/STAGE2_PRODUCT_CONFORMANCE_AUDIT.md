# Auditoría de conformidad de producto — Etapa 2

Fecha: 2026-08-07; evidencia externa observada hasta 2026-08-08 UTC. Esta
auditoría evalúa el entorno experimental usable, no un SaaS institucional ni
validez semántica de un modelo real.

## Flujo docente

El candidato permite crear una actividad, aprobar su blueprint, registrar
múltiples `subject_ref` seudónimos, subir TXT/Markdown/PDF/DOCX, ejecutar jobs
independientes y filtrar el lote. Una submission insuficiente falla cerrada sin
Assessment parcial y no bloquea otra suficiente.

En review, la evidencia debe verificarse antes de aprobar. ACCEPT, REJECT, EDIT
y REGENERATE se autorizan server-side, quedan append-only y conservan
versiones/lineage. La regeneración cambia solo la pregunta objetivo desde su
reserva y mantiene exactamente N o falla cerrada. La guide continúa separada.

Coverage, métricas y feedback describen el sistema y el proceso de revisión;
no se convierten en inferencias sobre capacidad, autoría o fraude. La
aprobación masiva exige confirmación, versiones exactas y permiso expreso, y
devuelve una partición completa de aprobados/excluidos.

## Export y recuperación

Assessment PDF/HTML, Guide PDF/HTML, coverage CSV/JSON y JSON canónico derivan
de snapshots. Crear o reemitir una capability no repite llamadas de modelo ni
persiste URLs firmadas. La UI recupera estado durable desde la raíz después de
cerrar el navegador. El recorrido cloud sintético verificó exports, replay,
model-call delta 0 y recuperación, y terminó con capabilities persistidas 0.

## Accesibilidad

Los flujos críticos incluyen labels, foco visible, estados de error, tabs
roving, Home/End/flechas, navegación por teclado y semántica de listas/tablas.
Vitest y Playwright cubren axe y 390 px; una revisión renderizada en el browser
integrado verificó ausencia de overflow y consola limpia. En el runtime cloud
real se repitió el recorrido a 1440 px y 390 px, incluido cierre/reapertura: no
hubo errores de consola ni overflow global.

## Roles y límites del producto

ASSISTANT puede cargar/ejecutar submissions y proponer acciones; aprobar exige
`can_approve_assessments`. El aviso fijo declara que el sistema no detecta IA,
no prueba autoría/fraude ni reconstruye historia, y que la decisión académica
es humana.

El candidato usa `MOCK_MODEL`; por ello valida integración, contratos,
seguridad y control de estado, no calidad pedagógica de un proveedor real. No
usa datos reales. ClamAV está ausente y la salida a datos reales permanece
bloqueada por [PARSER_SECURITY_E2.md](../PARSER_SECURITY_E2.md).

## Conformidad cloud controlada

Sobre `STAGE2_RUNTIME_SHA`
`44b94830bf3346a8fcbc0a8ce11247a42ae5daf5`, el manifest sintético completó
38/38 pasos contra Service/Job Ready con el mismo digest, modelo mock, P10
false y libmagic true. Los pasos 12 y 33–36 requirieron
`CONTROLLED_ADMIN_SEED`: comprobaron los estados y las acciones en el runtime
real, pero no representan fallos naturales del proveedor. Retry/resume conserva
lineage cloud; la semántica de éxito se demuestra en local/CI.

La ejecución terminó sin usuarios Auth efímeros, jobs activos ni capabilities
persistidas, y con errores/fugas en logs 0/0. DB/R2 retienen únicamente la
evidencia sintética. La supply chain observada incluye SLSA 3 v1 y scan
`FINISHED_SUCCESS`; no se observó ni se reclama SBOM.

## Dictamen

| Frontera | Dictamen |
|---|---|
| Conformidad funcional local E2-01…E2-15 | PASS |
| Regresión E0/E1 | PASS |
| Accesibilidad crítica local | PASS |
| CI del runtime | PASS_CI_REAL |
| Conformidad cloud sintética 1–38 | PASS_CLOUD_REAL; 38/38 |
| Accesibilidad cloud 1440/390 y recuperación | PASS_CLOUD_REAL_BROWSER |
| Proveedor/modelo real | BLOCKED / fuera de E2 |
| Datos estudiantiles reales | BLOCKED / fuera de E2 |
| Conformidad cloud del runtime probado | PASS_CLOUD_REAL + MOCK_MODEL |

P0 abiertos: 0. P1 abiertos: 0. El producto queda conforme para un piloto
controlado exclusivamente sintético con modelo mock. P2/P3 abiertos: 3/1.
Datos/modelo reales, P10 y Etapa 3 continúan bloqueados.
