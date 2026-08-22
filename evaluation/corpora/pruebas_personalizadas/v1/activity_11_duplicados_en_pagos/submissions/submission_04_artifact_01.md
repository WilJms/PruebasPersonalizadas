# Invariant

Para cada `(order_id, attempt_id)` puede existir como máximo un cargo lógico. Un intento nuevo tras rechazo recibe otro `attempt_id` y puede originar un cargo nuevo.

# Decisión

Crear de forma durable un registro `payment_attempt` único antes de la llamada, con estado `pending`. Derivar `idempotency_key = "charge:" + order_id + ":" + attempt_id`. La clave es igual en redeliveries de `job_88` y distinta para otro intento legítimo. Enviar la clave al proveedor, persistir resultado y solo entonces hacer ack.

# Fallos y trade-offs

Si se cae antes de llamar, la redelivery encuentra `pending` y puede continuar. Si se cae después de la aprobación, repite con la misma clave y obtiene el mismo resultado. Un `pending` antiguo requiere reconciliación con el proveedor; no debe convertirse automáticamente en otro cargo. Dependemos de la ventana de 24 horas, por lo que alertaremos antes de que expire y detendremos reintentos automáticos después. Esto agrega estado y operación de reconciliación, pero conserva reintentos legítimos por `attempt_id` nuevo.

## Opciones consideradas

**Solo constraint local.** Evita dos filas finales, pero no evita dos llamadas al proveedor si la primera aprobación no se registra. Es necesaria como defensa, no suficiente como frontera de idempotencia.

**Clave por `job_id`.** Funciona mientras toda redelivery y republicación legítima conserven `job_88`. El dossier solo garantiza la redelivery observada; no define que un mismo intento nunca se republique con otro job. Por eso la identidad del negocio es más estable.

**Clave por orden.** Impediría cobrar de nuevo después de un rechazo cuando se crea un intento legítimo distinto. Viola el requisito de permitir un nuevo `attempt_id`.

Elegimos la combinación `(order_id, attempt_id)` tanto para el constraint como para la clave del proveedor. La ventana de 24 horas obliga a no reintentar ciegamente cuando un pending se acerca a expirar. El reconciliador consulta el estado existente; si no puede resolverlo, escala y mantiene bloqueado ese intento sin bloquear intentos nuevos explícitos.
