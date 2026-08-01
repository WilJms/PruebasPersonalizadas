# Diseno propuesto

La lectura consulta primero la cache local. Si la entrada existe y su version coincide con la version publicada por la fuente, se devuelve el valor almacenado. Una entrada vencida no se renueva de forma silenciosa: se marca como no vigente antes de consultar la fuente.

## Invalidacion

Cada actualizacion aceptada incrementa una version monotona. El consumidor compara esa version con la de la entrada local, por lo que una invalidacion tardia no puede restaurar un valor anterior.

## Degradacion y limite

Si la fuente no responde, el servicio puede mostrar el ultimo valor con una marca explicita de antiguedad durante treinta segundos. Esta decision reduce interrupciones, pero no es apropiada cuando un valor desactualizado puede causar una accion irreversible.
