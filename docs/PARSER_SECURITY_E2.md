# Seguridad del parser aislado — Etapa 2

Fecha de corte: 2026-08-08 (America/Santiago).

## Decisión temporal sobre antivirus

El runtime de Etapa 2 **no incluye ClamAV ni otro antivirus**. La omisión solo
es válida en el alcance vigente: fixtures sintéticos controlados, modo de
modelo mock y ausencia de datos estudiantiles reales. No existe una afirmación
de que los controles estructurales detecten malware general.

| Registro de excepción | Estado |
|---|---|
| Aprobación para datos reales | Ninguna; explícitamente bloqueada. |
| Responsable de cierre | Función de seguridad/privacidad del piloto, aún no designada. |
| Vigencia | Solo mientras el entorno acepte exclusivamente fixtures sintéticos controlados; vence automáticamente ante cualquier propuesta de piloto o archivo real. |
| Riesgo residual | Malware sin indicador estructural puede no ser detectado. |

Esta aplicación concreta de ADR-005 y ADR-032 sigue la condición de la sección
19 del MVP: ClamAV puede omitirse cuando no sea viable para fixtures locales,
pero un piloto con archivos reales exige AV o un control compensatorio
aprobado expresamente. Incorporar únicamente el binario, sin procedencia y
actualización de firmas, cuarentena, health check y comportamiento fail-closed,
no satisface ese gate.

## Controles compensatorios implementados

| Frontera | Control actual | Fallo seguro |
|---|---|---|
| Tipo de archivo | Allowlist de PDF digital, DOCX, TXT y Markdown; MIME por `libmagic` obligatorio en cloud. El fallback de firma es solo local/test y queda observable como `signature-fallback`. | Mismatch, detector ausente en cloud o formato fuera de allowlist se rechazan. |
| PDF/DOCX | Rechazo de cifrado, contenido activo PDF, macros, OLE, campos activos y relaciones externas OOXML. `python-docx` se usa solo después del preflight manual. | Estructura ambigua, corrupta o activa se rechaza antes de producir evidencia. |
| ZIP/XML OOXML | Validación de directorio central, nombres/path traversal, duplicados, symlinks, métodos, entries, tamaño comprimido/descomprimido, ratio, profundidad, XML y elementos. No se extrae el paquete al filesystem. | Cualquier límite o metadata inconsistente bloquea el artefacto completo. |
| Proceso hijo cloud | Intérprete nuevo con `-I`, entorno mínimo, stdin cerrado, file descriptors no heredados, `stderr` descartado, stdout en archivo efímero acotado, timeout y errores genéricos. El padre Linux deshabilita dumps. | Timeout mata el grupo de procesos; envelope inválido o código no allowlisted se convierte en un reason code estable sin `stderr` ni contenido. |
| Recursos | `RLIMIT_CORE=0`, CPU, tamaño de archivo, file descriptors, memoria Linux y procesos; imagen no-root. | No poder aplicar un límite termina el hijo antes del parsing. |
| Red | Seccomp Linux devuelve `EPERM` para creación/uso de sockets. Inmediatamente después de cargar el filtro, el propio hijo intenta crear un socket IP; continuar solo es posible si recibe exactamente `EPERM`. | Plataforma no Linux, librería ausente, filtro no cargado o self-test inesperado producen `INGEST_PARSER_SANDBOX_FAILURE`; no se invoca el parser. |
| Contratos/procedencia | El padre vuelve a validar `ArtifactRef` y cada `EvidenceUnit` con los contratos canónicos y los liga al request: hash/tamaño/ID/nombre/MIME/rol, tenant, submission y referencias al artefacto. También valida compatibilidad de la atestación MIME. | Output incompleto, cruzado entre contextos o inválido no atraviesa el boundary. |

El sandbox de proceso reduce el blast radius, pero no reemplaza un scanner de
malware ni una VM dedicada. Tampoco constituye por sí solo una frontera de
lectura de filesystem: el hijo recibe una ruta resuelta a un objeto ya sellado
por el workflow. La ejecución local sin aislamiento y el fallback de firma son
facilidades de desarrollo, no evidencia válida para un piloto.

## Exit gate antes de archivos reales

El bloqueo de datos estudiantiles reales solo puede levantarse cuando exista
evidencia revisable de **una** de estas dos rutas:

1. AV operativo antes del parser: motor y firmas con procedencia/versiones,
   actualización gobernada, objeto en cuarentena, scan offline, health y
   antigüedad máxima de firmas fail-closed, límites de recursos, corpus
   benigno/malicioso y telemetría sin contenido; o
2. una aceptación explícita de control compensatorio por seguridad y
   privacidad, con threat model, riesgo residual, owner, alcance, expiración y
   criterio de revocación documentados.

Además, ambas rutas requieren sobre el digest exacto candidato a despliegue:

- `CVA_ENVIRONMENT=cloud` y `CVA_REQUIRE_LIBMAGIC=true`, sin fallback;
- usuario no-root, `libmagic` y `libseccomp.so.2` presentes;
- roundtrip del parser con aislamiento requerido, lo cual demuestra que el
  self-test de no-red pasó;
- suite de parsers normales/adversariales, timeout, límites, corrupción,
  cifrado, contenido activo y sanitización completamente verde;
- filesystem de runtime de solo lectura salvo un `/tmp` efímero acotado, red
  deshabilitada para el trabajo de parsing y ninguna capability adicional;
- revisión del SBOM/scan de imagen y registro de la evidencia del gate.

La prueba Docker descrita abajo sigue siendo evidencia de desarrollo. El cierre
cloud posterior sí ligó imagen, Service/Job, `libmagic` y el recorrido sintético
al digest indicado en la tabla. Eso no sustituye la ruta AV/compensatoria, que
continúa inexistente; por tanto el resultado del exit gate sigue siendo **NO
APROBADO PARA DATOS REALES**.

## Verificación reproducible

| Ejecución | Clasificación | Resultado |
|---|---|---|
| `pytest tests/test_parser_sandbox.py tests/test_parsers.py` | LOCAL_REAL | 57 passed |
| Docker runtime local | LOCAL_REAL | `sha256:5644dfadccfb1e43f0ce3155912fba44ba069d138199df3ca9d77e51aadf764c`, Linux arm64, UID 65532 |
| Health/readiness con rootfs read-only | LOCAL_REAL | PASS; `/app` no escribible y sin archivos world-writable |
| Roundtrip libmagic + isolation | LOCAL_REAL | PASS; socket `EPERM`, tenant/submission/rol ligados |
| Digest de despliegue E2 | CLOUD_REAL | `sha256:0c6be928c698cd052763c9daf683ae19d4f5b8a99cba06b54fc32e244d70044e`; Cloud Build `aad1bf58-966e-44f9-ad10-5d7b81144854` SUCCESS/VERIFIED; Service y Job Ready sobre el mismo digest |
| Exit gate de datos reales | BLOCKED | ClamAV/compensación formal aún inexistente |

```bash
.venv/bin/python -m py_compile \
  src/comprehension_verification/parsers/sandbox.py \
  src/comprehension_verification/parsers/sandbox_worker.py
.venv/bin/python -m pytest \
  tests/test_parser_sandbox.py \
  tests/test_parsers.py
docker build --target runtime -t cva-parser-sandbox:e2-smoke .
```

El smoke Linux debe ejecutar la imagen como su usuario por defecto, con rootfs
read-only, `/tmp` acotado, sin capabilities y con `no-new-privileges`; debe
crear un fixture sintético dentro de `/tmp`, exigir `libmagic` y llamar
`parse_in_subprocess(..., require_isolation=True)`. Un resultado exitoso prueba
en conjunto carga de libmagic, carga de seccomp y self-test de socket bloqueado;
si cualquiera falla, el worker no retorna evidencia.
