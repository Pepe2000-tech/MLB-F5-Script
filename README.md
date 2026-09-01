# MLB Betting Hub V4.1.1 — Hotfix

Esta versión usa un solo `app.py`.

## ¿Por qué?
La V4.1 podía fallar en Streamlit si `app.py`, `model.py` y `data_mlb.py`
quedaban desincronizados o Streamlit tomaba una versión anterior.

En V4.1.1:
- no existe import desde `model.py`
- no existe import desde `data_mlb.py`
- toda la lógica está dentro de `app.py`

## Para subir
En GitHub reemplaza:
- `app.py`
- `requirements.txt`

Puedes borrar `model.py` y `data_mlb.py`, aunque no es obligatorio porque V4.1.1 ya no los usa.
