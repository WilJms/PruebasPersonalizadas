```python
def asignar_turnos(solicitudes, cupos_por_grupo):
    solicitudes.sort(key=lambda s: (s["prioridad"], s["marca"], s["id"]))
    unicas = {s["id"]: s for s in solicitudes if s["grupo"] in cupos_por_grupo}
    asignadas, espera = [], []
    for grupo in cupos_por_grupo:
        del_grupo = [s for s in unicas.values() if s["grupo"] == grupo]
        corte = cupos_por_grupo[grupo]
        asignadas += [s["id"] for s in del_grupo[:corte]]
        espera += [s["id"] for s in del_grupo[corte:]]
    return {"asignadas": asignadas, "espera": espera}
```

## Caso de demostración

```python
demo = [
    {"id": "q2", "grupo": "B", "prioridad": 1, "marca": "08:00"},
    {"id": "q1", "grupo": "A", "prioridad": 1, "marca": "08:00"},
    {"id": "q2", "grupo": "B", "prioridad": 2, "marca": "08:10"},
]
antes = list(demo)
resultado = asignar_turnos(demo, {"A": 1, "B": 1})
```

Después de llamar, `demo` queda ordenada, aunque `antes` conserva el orden de referencias previo. El diccionario elige para `q2` la aparición insertada al final. La salida agrupa primero todo A y luego todo B porque el bucle exterior recorre el mapa de cupos.
