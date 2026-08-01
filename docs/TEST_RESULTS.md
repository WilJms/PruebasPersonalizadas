# Resultados de pruebas

Este archivo solo registra comandos realmente ejecutados. Se completará durante
la Etapa 0 con fecha, código de salida y limitaciones. No se registrarán como
éxito pruebas escritas pero no ejecutadas.

## Auditoría previa - 2026-07-31

| Comando/acción | Resultado real |
|---|---|
| `python ... -m py_compile specification/models_v1.1(1).py` | PASS con Python 3.12.13 y Pydantic 2.13.4 |
| regeneración temporal + `cmp` del schema | PASS, bytes idénticos |
| crawler estándar de `$ref` | PASS, 231/231 referencias resolubles |
| extractor de fixtures documentales | PASS, 8/8 objetos Pydantic válidos |
| inspección de workbook mediante runtime de artefactos | PASS, 8 hojas y fórmulas leídas; sin edición |

La validación independiente Draft 2020-12 mediante `jsonschema`, la suite, los
pipelines y el render todavía no se han ejecutado en este punto.

