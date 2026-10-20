# -*- coding: utf-8 -*-
"""Pruebas de la lógica (python test_logica.py). Usan una base temporal."""
import os, tempfile
os.environ["MIRANA_DB"] = os.path.join(tempfile.mkdtemp(), "prueba.db")
from datetime import date, timedelta
import logica as L

L.iniciar_bd()
assert len(L.listar_trabajadores()) == 4

# Teléfonos editables
L.actualizar_trabajador(1, "Obstetra 1", "+51 987 654 321")
assert L.listar_trabajadores()[0]["telefono"] == "987654321"
for malo in ("123", "812345678", "abc"):
    try: L.actualizar_trabajador(1, "Obstetra 1", malo); raise SystemExit("debió fallar")
    except L.ErrorCita: pass

def prox_dia_habil():
    d = date.today() + timedelta(days=1)
    while d.weekday() == 6: d += timedelta(days=1)
    return d
d = prox_dia_habil()

# Reserva y choque de horario
libres = L.horarios_libres("ecografia", d)
assert libres, "debe haber horarios"
h = libres[0]
c = L.crear_cita("ecografia", d, h["hora"], h["trabajador_id"], "Ana Perez", "911111111", consentimiento=True)
assert c["id"] == 1
try: L.crear_cita("ecografia", d, h["hora"], h["trabajador_id"], "Rosa Diaz", "922222222", consentimiento=True); raise SystemExit("doble reserva")
except L.ErrorCita: pass
# Sin consentimiento
try: L.crear_cita("ecografia", d, libres[1]["hora"], libres[1]["trabajador_id"], "Rosa Diaz", "922222222"); raise SystemExit("sin consentimiento")
except L.ErrorCita: pass
# Ecografía solo la hacen Obstetra 2 y 4; Obstetra 1 no
try: L.crear_cita("ecografia", d, "10:00", 1, "Rosa Diaz", "922222222", consentimiento=True); raise SystemExit("servicio no permitido")
except L.ErrorCita: pass
# Con 2 ecografistas, el mismo horario aún puede tomarlo la otra
otros = [x for x in L.horarios_libres("ecografia", d) if x["hora"] == h["hora"]]
assert otros and otros[0]["trabajador_id"] != h["trabajador_id"]
# Reprogramar y cancelar
nuevo = L.horarios_libres("ecografia", d, h["trabajador_id"])[-1]
L.reprogramar_cita(1, "911111111", d, nuevo["hora"])
assert L.citas_de_paciente("911111111")[0]["hora"] == nuevo["hora"]
L.cancelar_cita(1, "911111111")
assert L.citas_de_paciente("911111111")[0]["estado"] == "cancelada"
assert any(x["hora"] == nuevo["hora"] and x["trabajador_id"] == h["trabajador_id"] for x in L.horarios_libres("ecografia", d, h["trabajador_id"]))
# Domingo cerrado
dom = date.today() + timedelta(days=(6 - date.today().weekday()) % 7 or 7)
assert L.horarios_libres("prenatal", dom) == []

# Chatbot: alarma, FAQ y reserva completa
est = L.nuevo_estado()
r, est, info = L.procesar_mensaje(est, "Estoy embarazada y tengo sangrado fuerte")
assert info[1] is True and "106" in r
r, est, info = L.procesar_mensaje(est, "¿Qué horario tienen?"); assert "lunes" in r.lower()
r, est, info = L.procesar_mensaje(est, "Dame los números de contacto"); assert "987654321" in r
r, est, info = L.procesar_mensaje(est, "Quiero una cita de ecografía"); assert est["paso"] == "fecha", r
r, est, info = L.procesar_mensaje(est, "1"); assert est["paso"] == "hora", r
r, est, info = L.procesar_mensaje(est, "1"); assert est["paso"] == "nombre"
r, est, info = L.procesar_mensaje(est, "Maria Lopez"); assert est["paso"] == "telefono"
r, est, info = L.procesar_mensaje(est, "12345"); assert est["paso"] == "telefono" and "9 dígitos" in r
r, est, info = L.procesar_mensaje(est, "933333333"); assert est["paso"] == "confirmar"
r, est, info = L.procesar_mensaje(est, "sí"); assert "Cita registrada" in r and est["paso"] is None, r
assert L.citas_de_paciente("933333333")[0]["origen"] == "asistente"
r, est, _ = L.procesar_mensaje(est, "quiero una cita"); assert est["paso"] == "servicio"
r, est, _ = L.procesar_mensaje(est, "salir"); assert est["paso"] is None
# Anonimización
assert "[número]" in L.anonimizar("mi cel es 987654321") and "[correo]" in L.anonimizar("a@b.com")
print("TODAS LAS PRUEBAS PASARON")
