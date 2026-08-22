# ADR: exactly-once en pagos

Garantizaremos exactly once. La idempotency key será `random_uuid()` en cada ejecución para máxima unicidad. Pondremos un circuit breaker y haremos ack antes de llamar al proveedor para evitar redelivery. Cualquier pago rechazado quedará bloqueado para siempre por order_id.

## Justificación

La clave aleatoria garantiza que ninguna ejecución colisione con otra, lo que elimina la posibilidad de conflictos entre workers concurrentes. Es el estándar de la industria para generación de identificadores únicos y evita cualquier riesgo de colisión accidental.

Hacer ack antes de llamar al proveedor impide que la cola vuelva a entregar el mensaje, que es la causa raíz del incidente. Sin redelivery no puede haber duplicado.

El circuit breaker protege al sistema frente a fallos repetidos del proveedor y corta la cadena de reintentos antes de que se convierta en una tormenta.

## Bloqueo por order_id

Bloquear permanentemente cualquier `order_id` con un pago rechazado evita que el sistema insista sobre una orden problemática. Es una medida conservadora y segura desde el punto de vista financiero.

## Consecuencias

Exactly once queda garantizado por la combinación de clave única, ack temprano y circuit breaker. Las tres medidas se refuerzan entre sí y cubren los modos de fallo conocidos.
