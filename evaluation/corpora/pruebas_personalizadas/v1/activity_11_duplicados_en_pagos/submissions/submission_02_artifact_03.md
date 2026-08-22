# Postmortem: cargo duplicado en ord_431

## Qué ocurrió

El worker realizó un cargo, falló al escribir en la base y no confirmó el mensaje. La cola entregó el mismo job otra vez y el handler volvió a cobrar. La cola actuó como estaba configurada; faltó idempotencia alrededor de la llamada al proveedor.

Sabemos que hay dos ids de aprobación para la misma orden e intento. No sabemos si ambos terminaron en el estado financiero final.

## Secuencia

El primer delivery no se confirmó porque el insert local agotó tiempo. Desde la perspectiva del worker no había resultado durable; desde la perspectiva del proveedor, `ch_501` ya estaba aprobado. La segunda entrega repitió la llamada y obtuvo `ch_502`.

La combinación de esos dos estados explica el duplicado sin atribuir una falla a la semántica at-least-once de la cola, que se comportó según su contrato.

## Alcance

El impacto confirmado se limita a dos aprobaciones para `ord_431/pay_1`. No sabemos si se liquidaron, si hubo reembolso o si existen más casos con el mismo patrón.

Revisaría intentos con múltiples provider ids y agregaría una alerta sobre esa condición. También documentaría el tiempo entre aprobación y persistencia para localizar pendings que necesiten conciliación.

## Acciones

La solución propuesta en el ADR crea estado antes de cobrar y confirma después de guardar. Con eso, una interrupción entre la aprobación y la persistencia deja una fila pending recuperable en lugar de un estado invisible.

Añadiremos un panel con filas pending por antigüedad y una consulta de intentos con más de un provider id.
