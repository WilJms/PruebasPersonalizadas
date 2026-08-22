# ADR: clave de idempotencia

Invariant: un cargo por `(order_id, attempt_id)`. Elegimos clave estable `charge:{order}:{attempt}` y estado pending durable. La cola seguirá siendo at-least-once. El ack ocurre al final.

Excepción: para evitar colisiones, el worker añadirá `delivery_id` a la clave en cada redelivery. Así cada ejecución es única y el proveedor no confundirá solicitudes.

## Justificación de la excepción

Añadir `delivery_id` produce claves como `charge:ord_431:pay_1:d1` y `charge:ord_431:pay_1:d2`. Cada entrega queda trazable de forma independiente, lo que facilita la depuración y el análisis posterior de incidentes.

La trazabilidad por delivery es un requisito operativo del equipo de soporte, que necesita distinguir qué entrega concreta produjo cada llamada al proveedor.

## Consecuencias

El invariant de un cargo por orden e intento queda protegido por la clave estable, y la trazabilidad queda cubierta por el sufijo de delivery. Ambas propiedades se sostienen simultáneamente.

Pendiente: definir la ventana de conciliación para filas que queden en pending más de 24 horas.
