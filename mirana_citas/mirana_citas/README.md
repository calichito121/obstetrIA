# Plataforma web con asistente virtual para citas obstétricas (MVP)

Prototipo para **Mirana Consultores S.A.C.** (semana 8). Python + Streamlit + SQLite, sin costo.
**Todos los datos son sintéticos.** El asistente funciona con reglas (no diagnostica).

## Qué incluye
- **Reservar cita** por tipo: control prenatal, ecografía, psicoprofilaxis, planificación familiar, Papanicolaou, puerperio y consulta ginecológica. Cada tipo solo se asigna a las profesionales habilitadas y no permite dobles reservas.
- **Asistente virtual** (chat): reserva citas conversando, responde horarios, servicios y contacto, y detecta signos de alarma.
- **Mis citas**: consultar, cancelar y reprogramar con el celular.
- **Panel del personal** (con clave): agenda, estado de citas, **nombre y teléfono editables de las 4 trabajadoras** y consultas anónimas.

## Ejecutar
```bash
pip install -r requirements.txt
streamlit run app.py
python test_logica.py        # pruebas de la lógica
```
Clave del panel: variable `PANEL_CLAVE` o `.streamlit/secrets.toml` (`PANEL_CLAVE = "tu-clave"`). Por defecto, en demostración: `demo1234`.

## Archivos
- `app.py`: interfaz Streamlit. `logica.py`: reglas, agenda y base de datos. `test_logica.py`: pruebas.

## Limitaciones
- En Streamlit Community Cloud el archivo SQLite se reinicia al reiniciar la app; sirve para la demo, no como almacenamiento definitivo.
- Los horarios, servicios y profesionales están definidos en `logica.py` (supuestos editables).
