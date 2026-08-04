# Manifiesto de evidencia de Etapa 1

Fecha de auditoría: `2026-08-04` (`America/Santiago`). Este documento inventaría
evidencia aportada; no la convierte en autoridad canónica ni incorpora el
paquete al repositorio.

## Cadena de custodia

| Adjunto identificado | Bytes | Fecha del archivo | SHA-256 | Resultado |
|---|---:|---|---|---|
| `/Users/wiljms/cva-stage1-evidence/20260803-112142.tar.gz` | 43.678 | `2026-08-03T23:33:04-0400` | `d68bd852fd97a120b4c5c8afc72396083071ebac3f4dafae2f1511d7d3952ab0` | El checksum declarado coincide. |
| `/Users/wiljms/cva-stage1-evidence/20260803-112142.tar.gz.sha256` | 123 | `2026-08-03T23:33:09-0400` | `5e6dee5a48c8ff0b3203b3017135235a78b2ebc10efaf1a67116222a6b0cdcab` | Archivo de checksum conservado intacto. |
| `/Users/wiljms/cva-stage1-evidence/20260803-112142.tar.gz.contents.txt` | 4.042 | `2026-08-03T23:33:16-0400` | `e81facfec8a13945ec930a0a538f1cbe1fe7597654d47da63301956c1cd5f2f4` | Coincide byte a byte con `tar -tzf`: 93 entradas, de ellas 92 archivos. |
| `/Users/wiljms/.codex/attachments/3c7f3ac2-0f8c-4b27-b971-ea71c12d3179/pasted-text.txt` | 18.548 | `2026-08-04T12:50:00-0400` | `837a80cf69be70a5349afc251ff71e04a511a95fa8fd25e0be5fae49345d05c4` | Prompt de auditoría, no evidencia de ejecución. |

El tar se inspeccionó antes de extraer: 0 paths absolutos o con traversal, 0
paths duplicados y 0 entradas especiales. Solo después se extrajo en
`/tmp/cva-stage1-audit.sJQmUS/20260803-112142`, fuera del repositorio. Los
originales no se escribieron y el hash del tar se volvió a comprobar al final.
El escaneo previo por private keys, bearer/JWT, tokens cloud, credential URLs y
asignaciones sensibles produjo 0 coincidencias de alta confianza. Esto no
garantiza ausencia semántica de todo secreto; por ello los informes no copian
logs ni identificadores personales.

## Cómo leer la correlación

Cada fila del inventario hereda todos los campos de un perfil y una relación.
Así quedan explícitos para cada archivo: criterio, operación, commit,
build/digest, proyecto, región, Service/Job, resultado esperado, observado y
limitación. `ND` significa que el propio archivo no lo demuestra; no se rellena
por inferencia.

### Perfiles de despliegue

| Perfil | Commit | Build | Imagen/digest | Proyecto / región / recursos |
|---|---|---|---|---|
| `B` | `ND` salvo que la relación indique `a817546a07460c8dd87f6d6c82403ec6dddf38cb` | pre-runtime | `ND` | `cva-experimento-wiljms` / `us-east1`; bootstrap de `cva-web` y `cva-worker`. |
| `I` | `a817546a07460c8dd87f6d6c82403ec6dddf38cb` | `0ef1cd09-8d05-4667-bd3a-6691005ab256` | `sha256:a09ff04b5a2c5084f60dc4742ed5dcedf4761eedf2f261de2b4bd23849aa3ba1` | Mismo proyecto/región; Service/Job generación inicial. |
| `A` | `eec2a7455b5425422a8c7b9cd4ae38fa083b8a41` | `f10cef87-4626-44de-b2cd-cac959f45fcd` | `sha256:6a30c0745721cd3473c564bf4d95a868ac0e625e5ed3df51c5abca88305ca7c5` | Mismo proyecto/región; fix de auth intermedio. |
| `F` | `0167f14cbfe4a1192b26688a8443c5835da60bb4` | `85514589-a513-46af-ae74-1656a8433aa7` | `sha256:4dc9be449d1c7401dd70beaeeb38b6989b128a1892b59343b59717d2ca0a6f0b` | Mismo proyecto/región; `cva-web` / `cva-worker` finales. |
| `N` | `ND` | `ND` | `ND` | Contexto no demostrado por el archivo; no usar para atribución de despliegue. |

### Tipos

| Código | Significado |
|---|---|
| `D` | Evidencia directa/primaria: salida de API, CLI, DB, build o recurso. |
| `I` | Evidencia indirecta: resultado reportado sin el artefacto primario completo. |
| `R` | Resumen generado por el agente/operador que creó el paquete. |
| `U` | Afirmación o intento no demostrado/invalidado. |
| `M` | Archivo intermedio u obsoleto respecto del snapshot final. |
| `S` | Snapshot final aplicable al perfil `F`. |

### Relaciones de criterio y operación

| Rel. | Criterio | Operación | Esperado | Observado y limitación |
|---|---|---|---|---|
| `R01` | E1-11 / todos E1 | Resumen de cierre | Resumen consistente con primarios y gates. | Resume stack/happy path, pero acepta drift que la guía canónica bloquea; no sustituye primarios. |
| `R02` | E1-01 | Auth, usuario y membership | Magic link válido, actor autorizado y sesión durable. | Secuencia reportada/consultas; sin acceso Auth admin independiente y algunos archivos son parciales. |
| `R03` | E1-07, E1-11 | Cierre/reapertura del navegador | Job continúa y estado se recupera. | Recuperación por deep link reportada; no demuestra navegación desde el shell sin URL. |
| `R04` | E1-11 | IAM de build/runtime | Least privilege y separación de identidades. | Políticas/roles observados; archivos de política vacía web/worker son duplicados y solo prueban ausencia de bindings directos. |
| `R05` | E1-11 | Cloud Build e imagen inmutable | Build success, digest y commit trazables. | Tres builds sucesivos; perfiles I/A son intermedios y F es final. Status de 22 bytes está triplicado; submit manual, sin trigger. |
| `R06` | E1-11 | Describe Cloud Run e imagen | Service/Job Ready con mismo digest. | Descripciones de generación 1 son intermedias; imágenes I coinciden; la consulta viva posterior fue necesaria para F. |
| `R07` | E1-06, E1-07, E1-11 | Fallo controlado del Job | Un intento, 0 retries y estado durable failed. | Recursos/DB confirman fallo; cálculo de exit con `PIPESTATUS` bajo zsh no prueba el exit CLI. |
| `R08` | E1-01–E1-11 | Happy path E2E | Flujo de una actividad/submission, aprobaciones y exports. | Resultado reportado como exitoso; no incluye grabación ni transcript HTTP integral. |
| `R09` | E1-11 | Inventario del paquete | Lista completa con hashes/correlación. | El índice aportado solo lista nombres; este manifiesto lo reemplaza. |
| `R10` | E1-11 | Proyecto/billing | Proyecto correcto y billing habilitado. | Salida directa de bootstrap; no prueba por sí sola el runtime. |
| `R11` | E1-11 | GitHub Actions y PR | CI verde y SHA preciso. | Snapshot final del paquete apunta a `0167f14…`; HEAD luego avanzó solo con auditorías. |
| `R12` | E1-01, E1-11 | Health/readiness/ruta privada | 200/200/401 en imagen final. | Health de F está vacío; health previo y readiness F más comprobación viva cubren la operación, no ese archivo vacío. |
| `R13` | E1-09, E1-10 | Ledger antes/después de export | Conteo idéntico y P10=0. | Recheck 8→8 y distribución observada; intento original inválido no cuenta. DB viva posterior contó 18 en dos actividades. |
| `R14` | E1-04–E1-09 | Estado durable, aprobación y reanudación | Versiones/estados terminales coherentes. | Respuestas/consultas directas con datos redactados; snapshots previos a F son intermedios. |
| `R15` | E1-06–E1-11 | Resultados de fases 28–32 | Resultado final verificable. | Resúmenes breves de otro agente; deben leerse contra archivos primarios. |
| `R16` | E1-10, E1-11 | Migración, RLS, grants y triggers | Migración completa, RLS y append-only. | Salidas directas, muy concisas; consultas vivas posteriores corroboraron 24/24 y dos triggers. |
| `R17` | E1-06–E1-10 | Estados PostgreSQL | Job/submission/assessment terminales. | Salidas directas con contenido sensible ya redactado; no se copian filas. |
| `R18` | E1-03, E1-11 | Control plane R2 | Privado, CORS/lifecycle correctos, r2.dev off. | Salidas directas aportadas; sin sesión Wrangler independiente. |
| `R19` | E1-03, E1-09 | Capacidad firmada | 200 inmediato y 403 tras TTL 300 s. | Status/result aportados; URL no se conserva ni cita. |
| `R20` | E1-11 | Secret Manager/runtime refs | Secretos por referencia/version, no inline. | Solo nombres/metadata; no valores. |
| `R21` | E1-01 | JWKS Supabase | JWKS público usable. | JSON directo ES256; no prueba invitation/membership por sí solo. |
| `R22` | E1-11 | Terraform bootstrap/runtime | Plan/apply planificado y outputs coherentes. | Planes/outputs intermedios; tfvars solo se identifica por hash, no se incorpora. |
| `R23` | E1-11 | Terraform drift | Plan posterior debe terminar 0. | Todos los planes aplicables terminan 2 por `service.scaling`; assessment que lo acepta contradice el gate. |
| `R24` | E1-11 | Service-account policy | Sin bindings inesperados. | Dos archivos idénticos; evidencia estrecha, no inventario IAM completo. |
| `R25` | E1-06, E1-11 | Logs/fallos redactados | Fallos diagnósticos sin secretos. | Extractos derivados/redactados; útiles, pero no logs primarios completos. |

## Inventario completo de los 92 archivos

| Archivo | Bytes | Timestamp | SHA-256 | Tipo | Perfil/relación |
|---|---:|---|---|---|---|
| `SUMMARY.txt` | 2285 | `2026-08-03T23:29:23-0400` | `4d66c37d6d78cf0baf49202e3e19117b865850b89f79a017ca406b25095efa18` | `R+S` | `F/R01` |
| `auth-verification-partial.txt` | 172 | `2026-08-03T12:06:48-0400` | `2df1e3d39119efd41a07bccda5daa6d4eb22bab0906076b26e18fbd871af3a56` | `I+M` | `B/R02` |
| `auth-verification.txt` | 470 | `2026-08-03T17:16:58-0400` | `3dba311d47f93a339ad4adbc87887cdf81fa030aa158284deee12c7a0c6b2e47` | `I+M` | `A/R02` |
| `browser-close-recovery.txt` | 288 | `2026-08-03T18:35:20-0400` | `f54c34e9f0ead2f5e2f2d68aac8934779eb55b644472fa91a4ebaabaa78df487` | `I+S` | `F/R03` |
| `cloud-build-iam.txt` | 151 | `2026-08-03T11:54:07-0400` | `9b04ff3b13a79e7b36144acd127113864f19087316a2e28972e03205115307be` | `D+M` | `B/R04` |
| `cloud-build-id-auth-fix.txt` | 37 | `2026-08-03T16:29:32-0400` | `5c608f66d895d6ff6de04910c7bcfe8d7ea153a8806c7dc6bbd053f12c0bd929` | `D+M` | `A/R05` |
| `cloud-build-id-principal-fix.txt` | 37 | `2026-08-03T18:20:02-0400` | `4d9152ed46d05bb1323ee314961223c2205037db9f5891f1cb38a8b8572eb24f` | `D+S` | `F/R05` |
| `cloud-build-id.txt` | 37 | `2026-08-03T12:36:50-0400` | `7e544d7976012255305c4362e01904867b0151d7baf24435f87f91ed29b3cb30` | `D+M` | `I/R05` |
| `cloud-build-log-auth-fix.txt` | 78100 | `2026-08-03T16:32:28-0400` | `17a3bdef847af7d949185b18d253166d615884076a9296c33c3bdfcf5320dcc9` | `D+M` | `A/R05` |
| `cloud-build-log-principal-fix.txt` | 39983 | `2026-08-03T18:22:55-0400` | `a7a876465da1f3e0098047a924d3c466a0d2cb39d32765ac57dc9e1b27bf45f9` | `D+S` | `F/R05` |
| `cloud-build-log.txt` | 200 | `2026-08-03T12:36:59-0400` | `180425326b624e0581090a78a64d499725bc92ddc94d7bbb5ecefd6be2295033` | `D+M` | `I/R05` |
| `cloud-build-status-auth-fix.txt` | 22 | `2026-08-03T16:34:21-0400` | `083661280a8864a39c845f55f4a8ad415ba7036c18e3566a03fde7b675dd2135` | `D+M` | `A/R05` |
| `cloud-build-status-principal-fix.txt` | 22 | `2026-08-03T18:23:06-0400` | `083661280a8864a39c845f55f4a8ad415ba7036c18e3566a03fde7b675dd2135` | `D+S` | `F/R05` |
| `cloud-build-status.txt` | 22 | `2026-08-03T12:40:46-0400` | `083661280a8864a39c845f55f4a8ad415ba7036c18e3566a03fde7b675dd2135` | `D+M` | `I/R05` |
| `cloud-errors-redacted.txt` | 2021 | `2026-08-03T23:22:30-0400` | `85ee68e78364303104e2df83db955c8d9932ea8e12f0fdf0a15cdb805ac9d542` | `I+S` | `F/R25` |
| `cloud-run-job-description.json` | 5907 | `2026-08-03T12:46:50-0400` | `3563a9a6632e0055d7724766f8009524910143c216b016d00c45a9d5cf37c832` | `D+M` | `I/R06` |
| `cloud-run-job-image.txt` | 158 | `2026-08-03T13:06:34-0400` | `035da1419dab67674f5cfc70e14deadb4f8969827140d297dcc41862cb633a44` | `D+M` | `I/R06` |
| `cloud-run-service-description.json` | 7245 | `2026-08-03T12:46:49-0400` | `c92dafeaf4925b04e3e59e1907c10da640b1905df2372695f59c1493faea95b1` | `D+M` | `I/R06` |
| `cloud-run-service-image.txt` | 158 | `2026-08-03T12:46:18-0400` | `035da1419dab67674f5cfc70e14deadb4f8969827140d297dcc41862cb633a44` | `D+M` | `I/R06` |
| `controlled-failure-cloud-run-execution.txt` | 71 | `2026-08-03T23:08:33-0400` | `f827c6bad1c974732e7cd0016693245bf03efb858944fd7a7d07865d1899a43e` | `D+S` | `F/R07` |
| `controlled-failure-execution-description.json` | 6736 | `2026-08-03T23:11:57-0400` | `aa51f44f5c50bd4e7d263f68660ab74c61c182544b9c48bbd41888969d6eda24` | `D+S` | `F/R07` |
| `controlled-failure-execution.txt` | 1295 | `2026-08-03T23:11:37-0400` | `dec1fd7f2db121479033fed5cac74f5d6ea1e03bf82ab93286caf91e58b81b47` | `D+S` | `F/R07` |
| `controlled-failure-max-retries.txt` | 22 | `2026-08-03T23:13:01-0400` | `0de616de52ff71d6450e1089ea13954a0097b3fec0309652d7e5a4468a3f905c` | `D+S` | `F/R07` |
| `controlled-failure-task-count.txt` | 24 | `2026-08-03T23:12:34-0400` | `fdd1e167dad5c5c6f854845403b3a1463d8c9dfc642eb97497f5c13517d5fe48` | `D+S` | `F/R07` |
| `controlled-failure-tasks.json` | 1373 | `2026-08-03T23:12:25-0400` | `1cfe39f3b513460e63136b694ba8eb40e9bf32c66e652f3e06bf65d8b6538964` | `D+S` | `F/R07` |
| `controlled-failure-test.txt` | 944 | `2026-08-03T23:08:20-0400` | `3ab08a337a5926445a64d01e97d4ca5348557d2c8266688f5b7831583dc4aeee` | `U+S` | `F/R07` |
| `controlled-failure-worker-policy.json` | 6107 | `2026-08-03T23:12:44-0400` | `efc7add9237b6a6535b437470c8a2f15df22c8186954982716a80850fb1a0981` | `D+S` | `F/R07` |
| `e2e-happy-path.txt` | 393 | `2026-08-03T18:32:09-0400` | `9f4c96f893974d95b58bade49c2998311178ccb440e4a8a2034dbf01685e13db` | `R+S` | `F/R08` |
| `evidence-manifest.txt` | 2553 | `2026-08-03T23:32:46-0400` | `e6f403696ff84762aef7ba92511cc80b8ef93205e66427d19c29688df91aa8c4` | `R+S` | `F/R09` |
| `gcp-billing-status.txt` | 55 | `2026-08-03T11:47:18-0400` | `37f28ca0aa71271cd7eb0869d4e77d75d75fb0d565d48b0a392e22085fe9659a` | `D+M` | `B/R10` |
| `gcp-project.txt` | 23 | `2026-08-03T11:47:17-0400` | `d068b17393880a6e21456652a29e2d0a5319f96aea6d597f4e59ce23ae83ee24` | `D+M` | `B/R10` |
| `github-actions-final.txt` | 1377 | `2026-08-03T23:24:55-0400` | `c9707cd431f7360d8ac464819574aae6d7e00cd2e29a213a4960cbe3063896eb` | `D+S` | `F/R11` |
| `github-pr-final.txt` | 182 | `2026-08-03T23:25:04-0400` | `57b653bb115ed2079107eee0aaf3e9510007140417050adb6efcc63749a26410` | `D+S` | `F/R11` |
| `health-principal-fix.txt` | 0 | `2026-08-03T18:26:35-0400` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `U+S` | `F/R12` |
| `health.json` | 47 | `2026-08-03T17:20:20-0400` | `7d071a136bfafd08cf1d034daf5f142085833e55df4dabc15cad4bcc06cc535e` | `D+M` | `A/R12` |
| `immutable-image-auth-fix.txt` | 158 | `2026-08-03T16:34:38-0400` | `9dc73e103c8e62a3f608a2c034c8b7129f54afa4007896ad3a0c93df87a6c8a6` | `D+M` | `A/R05` |
| `immutable-image-principal-fix.txt` | 158 | `2026-08-03T18:23:35-0400` | `2850fc546a6c8492dd97706348fd434d45f86550fa37432e6c9cb4b3e1bff8a9` | `D+S` | `F/R05` |
| `immutable-image.txt` | 158 | `2026-08-03T12:41:49-0400` | `035da1419dab67674f5cfc70e14deadb4f8969827140d297dcc41862cb633a44` | `D+M` | `I/R05` |
| `model-call-count-recheck-after.txt` | 2 | `2026-08-03T18:52:49-0400` | `aa67a169b0bba217aa0aa88a65346920c84c42447c36ba5f7ea65f422c1fe5d8` | `D+S` | `F/R13` |
| `model-call-count-recheck-before.txt` | 2 | `2026-08-03T18:51:14-0400` | `aa67a169b0bba217aa0aa88a65346920c84c42447c36ba5f7ea65f422c1fe5d8` | `D+S` | `F/R13` |
| `model-call-original-attempt-invalid.txt` | 354 | `2026-08-03T18:51:07-0400` | `ea1a6f9ced87749c0b93b0e0209ebe8b6d061cf72c4a1a313205b09c76ebddb0` | `U+S` | `F/R13` |
| `model-prompts-recheck.txt` | 234 | `2026-08-03T18:51:24-0400` | `f9b370e30362d23502ca0efec5d187b9f21ce6a0cf67e62f560a77cfc2595dd2` | `D+S` | `F/R13` |
| `phase-20-final-state.txt` | 767 | `2026-08-03T13:12:18-0400` | `d83f7adf3f450c0360409fa563dbad320b531e90911d3490c906ebae1a003de3` | `R+M` | `I/R14` |
| `phase25-blueprint-approval-state.txt` | 910 | `2026-08-03T17:57:31-0400` | `56885fdf106b53d3ba7bce2ec1bf516482165dd5276e93dc3768bf89ca495e12` | `D+M` | `A/R14` |
| `phase25-failure-redacted.txt` | 1082 | `2026-08-03T23:32:15-0400` | `16fabcc810f7b3aa202d26f87ea31c7c9efe69348b355c85853b659507cb6059` | `I+S` | `F/R25` |
| `phase25-failure-state.txt` | 1999 | `2026-08-03T17:52:03-0400` | `b14d11fd833b94d31b27042ea0bd339a75b12577038ae5708b3cced7b817b5a6` | `D+M` | `A/R14` |
| `phase25-resumed-state.txt` | 1005 | `2026-08-03T18:28:52-0400` | `fe4dbda3b63f9ff8af42b436f1639f45896a302e506cd9c08bbaa4484e5d8a72` | `D+S` | `F/R14` |
| `phase28-result.txt` | 40 | `2026-08-03T23:05:51-0400` | `111935e462c9941266f25c3d5b700fd13de6b3a46d16f3f834a62e4b0300b88d` | `R+S` | `F/R15` |
| `phase29-result.txt` | 247 | `2026-08-03T23:14:49-0400` | `644716096b372f2c70f5561d2ac7a54eb1040a1c1a57d68904b84ffcf10f95cd` | `R+S` | `F/R15` |
| `phase30-result.txt` | 239 | `2026-08-03T23:23:57-0400` | `314b143d1b774f9e433c79f5ce0846872a7f1ab10c901bb2f2a5a232b21cc17a` | `R+S` | `F/R15` |
| `phase31-result.txt` | 267 | `2026-08-03T23:27:04-0400` | `a2b7ce9ca799b83babbf4e40ed5fef8842a60853efdddf8788d126e3e975dc5b` | `R+S` | `F/R15` |
| `phase32-result.txt` | 455 | `2026-08-03T23:32:39-0400` | `dcf266f1b0787f7d930bc44251b6848d842a685de93e56326403b7df37cce8ef` | `R+S` | `F/R15` |
| `postgres-assessment-terminal.txt` | 782 | `2026-08-03T23:05:32-0400` | `48fd9dcd5ac8fa150c82828f9d7ba8865449fdf9fd34c1d50f556a8470d8e637` | `D+S` | `F/R17` |
| `postgres-grants-result.txt` | 2 | `2026-08-03T11:58:17-0400` | `9a271f2a916b0b6ee6cecb2426f0b3206ef074578be55d9bc94f6f3fe3ab86aa` | `D+M` | `B/R16` |
| `postgres-job-terminal.txt` | 616 | `2026-08-03T23:04:16-0400` | `d1986086fb79098b2a735a09960459d614c66de98f27b7aaa4709f6c27c3f15c` | `D+S` | `F/R17` |
| `postgres-migration-result.txt` | 1354 | `2026-08-03T11:57:54-0400` | `dc8b2af066f45ee2a9fe50db9f3a2df059531bbde412d2619f226a062f0049c8` | `D+M` | `B/R16` |
| `postgres-rls-result.txt` | 6 | `2026-08-03T11:58:04-0400` | `fe1baf2e5499c856c2dabc55457cd74a288f38510d3c4d7d957c2ef5bfda6d5a` | `D+M` | `B/R16` |
| `postgres-submission-terminal.txt` | 775 | `2026-08-03T23:05:00-0400` | `b7eaf61384ff77fc38d02918ee71688cda8dc4ab2db6b20feecd5218bfe0e0bb` | `D+S` | `F/R17` |
| `postgres-triggers-result.txt` | 2 | `2026-08-03T11:58:30-0400` | `53c234e5e8472b6ac51c1ae1cab3fe06fad053beb8ebfd8977b010655bfdd3c3` | `D+M` | `B/R16` |
| `private-route-http-status.txt` | 4 | `2026-08-03T17:20:56-0400` | `5d94ef1d04a57469912deb42e29ecee5168b983c775efa906cb9268596ba9f84` | `D+M` | `A/R12` |
| `private-route-response.json` | 78 | `2026-08-03T17:20:56-0400` | `614dae3e7c34670b667c01cb7dcda15627f6a1daeca4ca8509b85da2f316a199` | `D+M` | `A/R12` |
| `r2-cors-verification.txt` | 317 | `2026-08-03T17:19:01-0400` | `249f2827de12ee28c554a7511b02ce6e8b6c61793888ca7335ffbcbc69a33eeb` | `D+M` | `A/R18` |
| `r2-dev-url-status.txt` | 133 | `2026-08-03T12:29:26-0400` | `8be7a37f36e0d7d78f44d846f42f0fd1a3a7dfed4ed758a307b0ea245dca1bae` | `D+M` | `B/R18` |
| `r2-domain-list.txt` | 216 | `2026-08-03T12:29:28-0400` | `4201139a21f8fc9a6b47a632e6d69ef0810fadf830b9b8a62fc8b5ca249a98cd` | `D+M` | `B/R18` |
| `r2-lifecycle-verification.txt` | 539 | `2026-08-03T12:28:46-0400` | `a19412de5f5f4067e82efa793fa83aab19e1a90746938591bc932675f5f518a4` | `D+M` | `B/R18` |
| `r2-privacy-verification.txt` | 349 | `2026-08-03T12:29:28-0400` | `99c110a653eaecebdc0b694223f55d7ee76b37a9b4386c3b8c1e81856017dc3d` | `D+M` | `B/R18` |
| `readiness-principal-fix.txt` | 542 | `2026-08-03T18:26:35-0400` | `29a415fe1c9e6c9e139bfe2f6aaba7c963a258b9aeb784dc7140a2db64ad4402` | `D+S` | `F/R12` |
| `readiness.json` | 18 | `2026-08-03T17:20:37-0400` | `31bf75f4c0a97cc1f7b60df824fa390b3be9ba014f29b63c87c698ba63d9a9fd` | `D+M` | `A/R12` |
| `runtime-secret-names.json` | 166 | `2026-08-03T12:30:22-0400` | `5c30d6a7f7537f61fd4ce22d3f0cc67440a8bf86747209e3970a0b413d22221e` | `D+M` | `B/R20` |
| `secret-version-metadata.txt` | 280 | `2026-08-03T12:34:17-0400` | `1db811c42b027ab9955462d54bd19da3313457ae8953a5c5f68b9fb8919425be` | `D+M` | `B/R20` |
| `signed-download-expired-status.txt` | 4 | `2026-08-03T19:10:01-0400` | `97a58cc66d1cd6b51466af8ed52d6a38053b5572fee09a0ae8859c26b82bdf67` | `D+S` | `F/R19` |
| `signed-download-expiry-result.txt` | 411 | `2026-08-03T19:14:19-0400` | `d6a7aca354a277f7f3d30073d11159ec7225deda3a5138cd0b223cd68a0aa899` | `R+S` | `F/R19` |
| `signed-download-immediate-status.txt` | 4 | `2026-08-03T19:02:43-0400` | `c11e3f4837efde2441e23a7b9da02131f53bf59fddeb7147c4ab81afe400460f` | `D+S` | `F/R19` |
| `supabase-jwks.json` | 240 | `2026-08-03T12:06:06-0400` | `caf7cd7614e3448401798d64d395edab28a2c58fa7479404dad10b8469c1eb1e` | `D+M` | `B/R21` |
| `teacher-membership.txt` | 151 | `2026-08-03T13:23:56-0400` | `9a128c773b969ac7f10e86c4adf88a32a332d1e3c4581ff44175a3a690438c71` | `D+M` | `I/R02` |
| `teacher-user.txt` | 203 | `2026-08-03T13:24:18-0400` | `b9850c48b70ce71c51e0e0d432346c7dee93a4f7858c29f5ce209977ff121f01` | `D+M` | `I/R02` |
| `terraform-auth-fix-plan.txt` | 2827 | `2026-08-03T16:35:20-0400` | `6e8043d1ab6b2e15605bed35e35cc504d599f4a9300125dac8fd5ba27a80329e` | `D+M` | `A/R23` |
| `terraform-bootstrap-outputs.json` | 1119 | `2026-08-03T11:52:33-0400` | `2533a6babdfc63adefd39376d8bac3aed63896206756a2fae3a84ec3e46c9664` | `D+M` | `B/R22` |
| `terraform-bootstrap-plan.txt` | 18070 | `2026-08-03T11:48:54-0400` | `214eb835c6a942f87683cd6d793ebdd215d09c9704cbc1b2b040fc63ec82becd` | `D+M` | `B/R22` |
| `terraform-drift-assessment.txt` | 773 | `2026-08-03T13:10:45-0400` | `4b33bda54a33035e0b3aed5705fc346f1c9fe25903ea11ae188d678cd0fe473f` | `R+M` | `I/R23` |
| `terraform-drift-fix-plan.txt` | 769 | `2026-08-03T13:07:48-0400` | `b377814129b943018be6551813363b4dcaffd89b62f576bfbe89efed170b0f24` | `D+M` | `I/R23` |
| `terraform-drift-plan-final.txt` | 7794 | `2026-08-03T13:09:02-0400` | `ab7c3093a1860a08c13008a1294199af446f603e772565815e708898049a6538` | `D+M` | `I/R23` |
| `terraform-drift-plan.txt` | 7794 | `2026-08-03T12:47:29-0400` | `4a2a7b36515165ea6240b52e0cfb4da3107d264c1fcfe2f0307bc02ecc7dca5e` | `D+M` | `I/R23` |
| `terraform-drift-post-e2e-result.txt` | 38 | `2026-08-03T23:28:01-0400` | `9504fe19b31fc75c7a51acb184e2c5a18dce504405ef0c79857c376526579bb7` | `D+S` | `F/R23` |
| `terraform-drift-post-e2e.txt` | 7794 | `2026-08-03T23:28:01-0400` | `57864dcc69ded7ef4a413f5f06419bb0c10caf8b20606f22e07c764b5b9c5932` | `D+S` | `F/R23` |
| `terraform-drift-result.txt` | 29 | `2026-08-03T13:09:02-0400` | `5cb699a0f254305ebfeaecf6a9fdc5ae272f2bf59a48941be0741a34390634a0` | `D+M` | `I/R23` |
| `terraform-principal-fix-plan.txt` | 2827 | `2026-08-03T18:24:36-0400` | `c8a8c9db7bbb139c7d901cdeb7cf523d765e20c3b98f42f63a06c17dc83e7ecb` | `D+S` | `F/R23` |
| `terraform-runtime-outputs.json` | 1592 | `2026-08-03T12:45:25-0400` | `fdf0bddc5986a880d62b36cbe54f31d0b42d294792fc719da3623333191d30de` | `D+M` | `I/R22` |
| `terraform-runtime-plan.txt` | 17251 | `2026-08-03T12:44:01-0400` | `19524f20a93ab7f0c9326b91152d40e25a34836a4cd7c84c17362408a9541102` | `D+M` | `I/R22` |
| `terraform-tfvars-bootstrap.sha256` | 89 | `2026-08-03T11:30:04-0400` | `f2139fa119ac9083013fd5e8c13ba521682949466e69095961e183f6e2c88be3` | `I+M` | `B/R22` |
| `web-service-account-policy.json` | 21 | `2026-08-03T11:54:36-0400` | `c6bc1f4315e66396fab83c1908f342f5dec34847e44f43e272d5a12be30295b0` | `D+M` | `B/R24` |
| `worker-service-account-policy.json` | 21 | `2026-08-03T11:54:53-0400` | `c6bc1f4315e66396fab83c1908f342f5dec34847e44f43e272d5a12be30295b0` | `D+M` | `B/R24` |

## Calidad, duplicados y contradicciones

- Vacío: `health-principal-fix.txt`; se clasifica `U`, no como health exitoso.
- Duplicados por contenido: los tres `cloud-build-status*`; las imágenes
  `immutable-image.txt`, `cloud-run-service-image.txt` y
  `cloud-run-job-image.txt`; ambos conteos model-call; y las políticas web/worker.
  Son duplicados explicables por operación, no evidencia independiente.
- Intermedios/obsoletos: perfiles `I` y `A`, especialmente descripciones de
  generación 1 y `phase-20-final-state.txt`; no deben citarse como estado final.
- Contradicción: `SUMMARY.txt`/`terraform-drift-assessment.txt` tratan el drift
  como aceptable, mientras `docs/EXTERNAL_SETUP.md` exige plan exit `0`.
- Intento inválido: `model-call-original-attempt-invalid.txt`; el propio archivo
  reconoce interpolación incorrecta. Solo el recheck 8→8 es aplicable.
- La medición `PIPESTATUS` de `controlled-failure-test.txt` no es fiable bajo
  zsh. El estado failed sí queda probado por describe, task y PostgreSQL.
- El paquete aportado no contiene hashes por archivo, no vincula un trigger
  GitHub–Cloud Build y no contiene una prueba browser reproducible completa.
- Ningún archivo del paquete se copió al repositorio; solo se registraron
  metadatos, correlaciones y conclusiones redactadas.

`READY_FOR_STAGE1_REMEDIATION`
