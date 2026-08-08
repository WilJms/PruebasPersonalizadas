# Auditoría de conformidad de producto — Etapa 2

Fecha: 2026-08-07. Esta auditoría evalúa el entorno experimental usable, no un
SaaS institucional ni validez semántica de un modelo real.

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
cerrar el navegador.

## Accesibilidad

Los flujos críticos incluyen labels, foco visible, estados de error, tabs
roving, Home/End/flechas, navegación por teclado y semántica de listas/tablas.
Vitest y Playwright cubren axe y 390 px; una revisión renderizada en el browser
integrado verificó ausencia de overflow y consola limpia.

## Roles y límites del producto

ASSISTANT puede cargar/ejecutar submissions y proponer acciones; aprobar exige
`can_approve_assessments`. El aviso fijo declara que el sistema no detecta IA,
no prueba autoría/fraude ni reconstruye historia, y que la decisión académica
es humana.

El candidato usa `MOCK_MODEL`; por ello valida integración, contratos,
seguridad y control de estado, no calidad pedagógica de un proveedor real. No
usa datos reales. ClamAV está ausente y la salida a datos reales permanece
bloqueada por [PARSER_SECURITY_E2.md](../PARSER_SECURITY_E2.md).

## Dictamen

| Frontera | Dictamen |
|---|---|
| Conformidad funcional local E2-01…E2-15 | PASS |
| Regresión E0/E1 | PASS |
| Accesibilidad crítica local | PASS |
| Proveedor/modelo real | BLOCKED / fuera de E2 |
| Datos estudiantiles reales | BLOCKED / fuera de E2 |
| Conformidad cloud del SHA final | NOT_VERIFIED |

P0 locales abiertos: 0. P1 locales abiertos: 0. El dictamen final de piloto
controlado depende todavía de CI y cloud real con fixtures sintéticos.
