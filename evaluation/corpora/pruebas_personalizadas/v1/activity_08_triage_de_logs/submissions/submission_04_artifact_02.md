# Resumen

La cuenta `admin_exports` tuvo cinco fallos, luego completó MFA y exportó un archivo grande. La sesión `s_77` aparece en el login, la creación y la descarga, así que esos eventos forman una secuencia. El 403 de búsqueda parece aparte porque fue bloqueado y no comparte sesión.

Es probable que la cuenta haya sido usada de forma no habitual, aunque MFA hace posible que fuera una acción autorizada. No hay historial para saber si 4,8 MB es anormal ni contenido del zip.

Recomiendo revocar la sesión y pedir confirmación al dueño de la cuenta. El costo es frenar una exportación legítima. También guardaría los logs. No propongo borrar el objeto porque podría ser evidencia.

## Cronología resumida

Los fallos terminan a las 14:03:20 y el éxito ocurre a las 14:06:41 desde la misma IP. Veintidós segundos después, `req_e12` solicita `scope=all`; a los dos segundos storage registra `obj_4c`; luego `req_e19` lo descarga. El encadenamiento por `s_77` hace más defendible tratarlos como una actividad continua que unirlos solo porque pasaron en cinco minutos.

Mi hipótesis de uso no habitual se apoya en los fallos seguidos de una exportación amplia, pero carezco de una línea base y de confirmación del responsable. La alternativa legítima sería un operador que cometió errores, completó MFA y ejecutó una tarea excepcional. No afirmo exfiltración: un 200 demuestra transferencia desde el servicio, no quién terminó con el archivo ni qué contenía.

Revocar la sesión y preservar logs tiene un alcance limitado y reversible. Antes de suspender la cuenta completa pediría confirmación por canal independiente y buscaría el ticket asociado. Si aparecen nuevas descargas con otra sesión, escalaría la contención. El evento WAF seguirá separado salvo que se encuentre un vínculo técnico adicional.
