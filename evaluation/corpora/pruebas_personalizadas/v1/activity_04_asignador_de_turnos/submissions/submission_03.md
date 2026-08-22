```python
def asignar_turnos(solicitudes, cupos_por_grupo):
    solicitudes = sorted(solicitudes, key=lambda x: x.get("prioridad", 99))
    limite = sum(cupos_por_grupo.values())
    ids = [x.get("id") for x in solicitudes]
    return {"asignadas": ids[:limite], "espera": ids[limite:]}
```

No adjunto nota técnica.

## Ejemplo visto en clase

```python
datos = [
    {"id": "u3", "grupo": "A", "prioridad": 2},
    {"id": "u1", "grupo": "B", "prioridad": 1},
]
cupos = {"A": 1, "B": 1}
```

Con este ejemplo salen primero `u1` y luego `u3`, que es lo correcto porque `u1` tiene mejor prioridad. Usé `99` cuando falta prioridad para que el registro quede al final en vez de producir un error. El límite es la suma de los cupos.

La función es corta y devuelve las dos listas que pide el contrato.
