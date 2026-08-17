# Conclusión

No hubo exportación exitosa: todas las solicitudes devolvieron 403. La sesión s_77 solo aparece en intentos fallidos y el archivo nunca fue descargado.

Evidencia: `req_e12` devolvió 200 con 4.812.220 bytes; `obj_4c` fue creado a las 14:07:05; `req_e19` devolvió 200 con el mismo tamaño. Estos tres eventos muestran una creación y descarga exitosa.

El payload bloqueado y la sesión s_77 son el mismo evento porque ocurrieron el mismo día. Recomiendo no hacer nada, pero también revocar todas las cuentas de la empresa.

## Línea temporal

A las 14:03:02 comienzan los fallos de autenticación de `admin_exports`. A las 14:04:08 el WAF bloquea `req_b17`. A las 14:06:41 se completa el login con MFA y se abre `s_77`. Entre las 14:07:03 y las 14:08:11 ocurren la exportación, la creación del objeto y la descarga.

Los relojes están sincronizados para este ejercicio, así que las horas son comparables entre sistemas.

## Incertidumbres

No conocemos el contenido del archivo, ni la línea base de tamaños de `admin_exports`, ni si existía un ticket de exportación asociado. Tampoco hay geolocalización ni historial de la cuenta.

## Acción inmediata

Como no ocurrió ninguna exportación, no es necesario interrumpir el servicio. Al mismo tiempo, conviene revocar todas las cuentas de la empresa para cerrar cualquier vía de acceso.

El siguiente dato que pediría es el ticket de exportación, si existe, y la línea base de tamaños de archivo de la cuenta.
