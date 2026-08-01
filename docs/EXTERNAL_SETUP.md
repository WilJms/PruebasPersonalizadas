# Configuración externa

La Etapa 0 no requiere cuentas cloud, dominios, buckets, bases de datos ni
credenciales de modelos. El modo predeterminado y de CI es `mock`.

## Smoke test futuro de proveedor real

Pendiente y excluido del CI. Solo podrá ejecutarse manualmente cuando exista un
adapter aprobado, autenticación introducida fuera del chat y un presupuesto
positivo explícito. El comando reservado es:

```bash
CVA_MODEL_MODE=real CVA_REAL_SMOKE_BUDGET_USD=... make real-smoke
```

Un presupuesto cero debe bloquear la ejecución antes de cualquier llamada. La
ausencia de adapter/credencial debe reportarse como ruta `BLOCKED`, nunca como
prueba exitosa.

