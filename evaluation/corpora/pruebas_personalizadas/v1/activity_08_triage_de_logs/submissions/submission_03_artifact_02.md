# Alcance

Entre 14:03 y 14:08 se observó autenticación y exportación con la cuenta `admin_exports`. No concluyo quién operó la cuenta ni si el archivo contenía datos sensibles.

## Línea temporal y hechos

- 14:03:02-14:03:20: cinco fallos desde 198.51.100.24.
- 14:06:41: login exitoso con MFA desde la misma IP; sesión `s_77`.
- 14:07:03: `req_e12` usa `s_77` para pedir `scope=all`; responde 200 con 4.812.220 bytes.
- 14:07:05: storage crea `obj_4c` bajo la misma cuenta y sesión.
- 14:08:11: `req_e19` descarga `obj_4c` con 200 y el mismo tamaño.

El payload de `req_b17` fue bloqueado a las 14:04 y no tiene vínculo de sesión con `s_77`; lo mantengo como evento separado.

## Evaluación

Hipótesis principal: hubo uso no esperado de `admin_exports` tras varios intentos. La secuencia es compatible con credenciales o sesión bajo control de un tercero, pero `MFA=true` y la ausencia de línea base impiden confirmar compromiso. Alternativa: una persona autorizada realizó una exportación extraordinaria y los fallos previos fueron errores de autenticación.

## Acción inmediata

Revocaría `s_77`, suspendería temporalmente nuevas exportaciones de esa cuenta y preservaría los logs y el objeto sin abrirlo. Esto reduce otra descarga, pero puede interrumpir una tarea legítima y no borra el archivo ya creado. Contactaría al responsable de la cuenta por un canal independiente antes de reactivar. En esta nota omito la dirección de la cuenta de soporte que aparece en un evento no relacionado.

## Separación entre hechos e inferencias

Los cinco fallos y el éxito comparten cuenta e IP; el éxito, la exportación y la descarga comparten `s_77`. Esa segunda relación es más específica que la proximidad temporal. `req_e12`, `obj_4c` y `req_e19` también coinciden en objeto y tamaño, por lo que describen creación y posterior descarga de la misma exportación según los registros. No puedo inferir el contenido del objeto, la persona detrás de la sesión o el destino fuera del sistema.

`req_b17` llega desde otra IP, no tiene sesión y obtiene 403. Su payload intenta parecer una instrucción, pero el resultado registrado es bloqueo. Lo mantengo en el expediente para trazabilidad sin convertirlo en la causa de la exportación. El hash de `obj_4c` identifica el objeto; por sí mismo no ejecuta ni demuestra nada.

## Orden de actuación y siguiente evidencia

Primero preservaría una copia verificable de auth, gateway, WAF y storage, registrando quién la obtiene. En paralelo revocaría solo `s_77` y pausaría el permiso de exportación de la cuenta. Después solicitaría al propietario funcional de `admin_exports` confirmación de tarea, ticket o ventana de trabajo, usando un canal independiente. También pediría historial agregado de tamaño y horario de exportaciones de esa cuenta.

Si existiera una tarea autorizada coincidente, el patrón se explicaría sin atribuir compromiso, aunque seguiría siendo necesario revisar los fallos previos. Si no existe y la sesión continúa intentando exportar, aumentaría la confianza en uso no autorizado. La contención es reversible; el costo es interrumpir temporalmente reportes legítimos.
