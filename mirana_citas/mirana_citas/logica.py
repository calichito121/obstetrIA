# -*- coding: utf-8 -*-
"""
Lógica del prototipo (sin Streamlit, para poder probarla aparte).
Mirana Consultores S.A.C. - Plataforma de citas obstétricas con asistente virtual (MVP, semana 8).
Todos los datos de ejemplo son SINTÉTICOS.
"""
import os
import re
import math
import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta

DB_PATH = os.environ.get("MIRANA_DB", "mirana.db")
SLOT_MIN = 30                       # granularidad de la agenda (minutos)
MARGEN_MIN = 30                     # no se reserva con menos de 30 min de anticipación
DIAS_ADELANTE = 30                  # ventana máxima de reserva

# Horario de atención (supuesto editable): lunes a viernes 9-13 y 15-19, sábado 9-13.
HORARIO = {
    0: [(time(9), time(13)), (time(15), time(19))],
    1: [(time(9), time(13)), (time(15), time(19))],
    2: [(time(9), time(13)), (time(15), time(19))],
    3: [(time(9), time(13)), (time(15), time(19))],
    4: [(time(9), time(13)), (time(15), time(19))],
    5: [(time(9), time(13))],
}

# Tipos de cita. La duración se redondea a bloques de SLOT_MIN.
SERVICIOS = {
    "prenatal":     {"nombre": "Control prenatal",             "min": 30, "descr": "Seguimiento del embarazo."},
    "ecografia":    {"nombre": "Ecografía obstétrica",         "min": 30, "descr": "Estudio por imágenes durante el embarazo."},
    "psicoprofilaxis": {"nombre": "Psicoprofilaxis obstétrica", "min": 60, "descr": "Preparación para el parto y la maternidad."},
    "planificacion": {"nombre": "Planificación familiar",      "min": 30, "descr": "Orientación sobre métodos anticonceptivos."},
    "papanicolaou": {"nombre": "Papanicolaou",                 "min": 30, "descr": "Toma de muestra para prevención de cáncer de cuello uterino."},
    "puerperio":    {"nombre": "Control de puerperio",         "min": 30, "descr": "Control después del parto."},
    "ginecologia":  {"nombre": "Consulta ginecológica",        "min": 30, "descr": "Consulta preventiva de salud ginecológica."},
}

# Las 4 trabajadoras (nombres y teléfonos SINTÉTICOS; se editan desde el panel del personal).
TRABAJADORES_INICIALES = [
    ("Obstetra 1", "900000001", "prenatal,puerperio,psicoprofilaxis"),
    ("Obstetra 2", "900000002", "ecografia,prenatal"),
    ("Obstetra 3", "900000003", "planificacion,papanicolaou,ginecologia"),
    ("Obstetra 4", "900000004", "ecografia,papanicolaou,planificacion,puerperio,ginecologia"),
]
ESTADOS = ["confirmada", "atendida", "no asistio", "cancelada"]
DIAS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


class ErrorCita(Exception):
    """Error de validación o de negocio mostrable al usuario."""


# ----------------------------------------------------------------- base de datos
@contextmanager
def conexion():
    con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    try:
        yield con
    finally:
        con.close()


def iniciar_bd():
    with conexion() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS trabajadores(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                telefono TEXT NOT NULL,
                servicios TEXT NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS citas(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                servicio TEXT NOT NULL,
                trabajador_id INTEGER NOT NULL REFERENCES trabajadores(id),
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                duracion_min INTEGER NOT NULL,
                paciente_nombre TEXT NOT NULL,
                paciente_tel TEXT NOT NULL,
                motivo TEXT,
                estado TEXT NOT NULL DEFAULT 'confirmada',
                origen TEXT NOT NULL DEFAULT 'web',
                consentimiento_en TEXT NOT NULL,
                creado_en TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS ix_citas_agenda ON citas(trabajador_id, fecha);
            CREATE TABLE IF NOT EXISTS consultas_anonimas(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                texto_anonimizado TEXT,
                intencion TEXT NOT NULL,
                alerta_urgencia INTEGER NOT NULL DEFAULT 0);
            """
        )
        if con.execute("SELECT COUNT(*) FROM trabajadores").fetchone()[0] == 0:
            con.executemany(
                "INSERT INTO trabajadores(nombre, telefono, servicios) VALUES (?,?,?)",
                TRABAJADORES_INICIALES,
            )


# ----------------------------------------------------------------- validaciones
def normalizar_telefono(tel):
    t = re.sub(r"[\s\-().]", "", str(tel or ""))
    if t.startswith("+51"):
        t = t[3:]
    elif t.startswith("51") and len(t) == 11:
        t = t[2:]
    if not re.fullmatch(r"9\d{8}", t):
        raise ErrorCita("El teléfono debe ser un celular peruano de 9 dígitos que empiece con 9.")
    return t


def validar_nombre(nombre, digitos=False):
    n = re.sub(r"\s+", " ", str(nombre or "")).strip()
    patron = r"[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ' .-]+" if digitos else r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ' .-]+"
    if not (3 <= len(n) <= 60) or not re.fullmatch(patron, n):
        raise ErrorCita("Escribe un nombre válido (solo letras, entre 3 y 60 caracteres).")
    return n


def _texto_corto(t, maximo=200):
    return re.sub(r"[\x00-\x1f<>]", " ", str(t or "")).strip()[:maximo]


# ----------------------------------------------------------------- trabajadores
def listar_trabajadores(solo_activos=False):
    with conexion() as con:
        q = "SELECT * FROM trabajadores" + (" WHERE activo=1" if solo_activos else "") + " ORDER BY id"
        return [dict(r) for r in con.execute(q)]


def trabajadores_para(servicio):
    return [t for t in listar_trabajadores(True) if servicio in t["servicios"].split(",")]


def actualizar_trabajador(tid, nombre, telefono, activo=True):
    nombre = validar_nombre(nombre, digitos=True)
    telefono = normalizar_telefono(telefono)
    with conexion() as con:
        cur = con.execute(
            "UPDATE trabajadores SET nombre=?, telefono=?, activo=? WHERE id=?",
            (nombre, telefono, 1 if activo else 0, int(tid)),
        )
        if cur.rowcount == 0:
            raise ErrorCita("No existe ese trabajador.")


# ----------------------------------------------------------------- agenda
def _n_slots(servicio):
    return max(1, math.ceil(SERVICIOS[servicio]["min"] / SLOT_MIN))


def _inicios_posibles(fecha, n_slots):
    ahora = datetime.now()
    if fecha < ahora.date() or fecha > ahora.date() + timedelta(days=DIAS_ADELANTE):
        return []
    res = []
    for ini, fin in HORARIO.get(fecha.weekday(), []):
        t = datetime.combine(fecha, ini)
        limite = datetime.combine(fecha, fin)
        while t + timedelta(minutes=SLOT_MIN * n_slots) <= limite:
            if t >= ahora + timedelta(minutes=MARGEN_MIN):
                res.append(t)
            t += timedelta(minutes=SLOT_MIN)
    return res


def _libre(con, tid, inicio, fin, ignorar_id=None):
    filas = con.execute(
        "SELECT id, hora, duracion_min FROM citas WHERE trabajador_id=? AND fecha=? "
        "AND estado IN ('confirmada','atendida')",
        (tid, inicio.date().isoformat()),
    ).fetchall()
    for f in filas:
        if ignorar_id and f["id"] == ignorar_id:
            continue
        h, m = map(int, f["hora"].split(":"))
        b_ini = datetime.combine(inicio.date(), time(h, m))
        b_fin = b_ini + timedelta(minutes=f["duracion_min"])
        if inicio < b_fin and fin > b_ini:
            return False
    return True


def horarios_libres(servicio, fecha, trabajador_id=None):
    """Lista de {'hora','trabajador_id','trabajador'}. Sin trabajador elegido, se asigna
    la persona libre con menos citas ese día (reparto de carga)."""
    if servicio not in SERVICIOS:
        return []
    n = _n_slots(servicio)
    trabs = trabajadores_para(servicio)
    if trabajador_id:
        trabs = [t for t in trabs if t["id"] == int(trabajador_id)]
    if not trabs:
        return []
    salida = []
    with conexion() as con:
        carga = {
            t["id"]: con.execute(
                "SELECT COUNT(*) FROM citas WHERE trabajador_id=? AND fecha=? AND estado IN ('confirmada','atendida')",
                (t["id"], fecha.isoformat()),
            ).fetchone()[0]
            for t in trabs
        }
        orden = sorted(trabs, key=lambda t: (carga[t["id"]], t["id"]))
        for ini in _inicios_posibles(fecha, n):
            fin = ini + timedelta(minutes=SLOT_MIN * n)
            for t in orden:
                if _libre(con, t["id"], ini, fin):
                    salida.append({"hora": ini.strftime("%H:%M"), "trabajador_id": t["id"], "trabajador": t["nombre"]})
                    if trabajador_id is None:
                        break
    return salida


def crear_cita(servicio, fecha, hora, trabajador_id, nombre, telefono, motivo="", origen="web", consentimiento=False):
    if not consentimiento:
        raise ErrorCita("Debes aceptar el tratamiento de tus datos personales para reservar.")
    if servicio not in SERVICIOS:
        raise ErrorCita("Tipo de cita no válido.")
    nombre = validar_nombre(nombre)
    telefono = normalizar_telefono(telefono)
    motivo = _texto_corto(motivo)
    if not re.fullmatch(r"\d{2}:\d{2}", str(hora)):
        raise ErrorCita("Hora no válida.")
    h, m = map(int, hora.split(":"))
    ini = datetime.combine(fecha, time(h, m))
    n = _n_slots(servicio)
    fin = ini + timedelta(minutes=SLOT_MIN * n)
    if ini not in _inicios_posibles(fecha, n):
        raise ErrorCita("Ese horario ya no está disponible. Elige otro.")
    with conexion() as con:
        con.execute("BEGIN IMMEDIATE")            # evita reservas simultáneas del mismo horario
        try:
            t = con.execute("SELECT * FROM trabajadores WHERE id=? AND activo=1", (int(trabajador_id),)).fetchone()
            if not t or servicio not in t["servicios"].split(","):
                raise ErrorCita("Esa profesional no atiende este tipo de cita.")
            if not _libre(con, t["id"], ini, fin):
                raise ErrorCita("Ese horario acaba de ser reservado. Elige otro.")
            propias = con.execute(
                "SELECT hora, duracion_min FROM citas WHERE paciente_tel=? AND fecha=? AND estado='confirmada'",
                (telefono, fecha.isoformat()),
            ).fetchall()
            for p in propias:
                ph, pm = map(int, p["hora"].split(":"))
                p_ini = datetime.combine(fecha, time(ph, pm))
                if ini < p_ini + timedelta(minutes=p["duracion_min"]) and fin > p_ini:
                    raise ErrorCita("Ya tienes una cita a esa hora con ese teléfono.")
            ahora = datetime.now().isoformat(timespec="seconds")
            cur = con.execute(
                "INSERT INTO citas(servicio,trabajador_id,fecha,hora,duracion_min,paciente_nombre,paciente_tel,"
                "motivo,estado,origen,consentimiento_en,creado_en) VALUES (?,?,?,?,?,?,?,?, 'confirmada',?,?,?)",
                (servicio, t["id"], fecha.isoformat(), hora, SLOT_MIN * n, nombre, telefono, motivo, origen, ahora, ahora),
            )
            con.execute("COMMIT")
            return {"id": cur.lastrowid, "trabajador": t["nombre"], "telefono_trabajador": t["telefono"],
                    "servicio": SERVICIOS[servicio]["nombre"], "fecha": fecha, "hora": hora}
        except Exception:
            con.execute("ROLLBACK")
            raise


def citas_de_paciente(telefono):
    tel = normalizar_telefono(telefono)
    with conexion() as con:
        q = ("SELECT c.*, t.nombre AS trabajador, t.telefono AS tel_trabajador FROM citas c "
             "JOIN trabajadores t ON t.id=c.trabajador_id WHERE c.paciente_tel=? ORDER BY c.fecha DESC, c.hora DESC")
        return [dict(r) for r in con.execute(q, (tel,))]


def cancelar_cita(cita_id, telefono):
    tel = normalizar_telefono(telefono)
    with conexion() as con:
        cur = con.execute(
            "UPDATE citas SET estado='cancelada' WHERE id=? AND paciente_tel=? AND estado='confirmada'",
            (int(cita_id), tel),
        )
        if cur.rowcount == 0:
            raise ErrorCita("No se encontró una cita confirmada con esos datos.")


def reprogramar_cita(cita_id, telefono, fecha, hora):
    tel = normalizar_telefono(telefono)
    with conexion() as con:
        con.execute("BEGIN IMMEDIATE")
        try:
            c = con.execute("SELECT * FROM citas WHERE id=? AND paciente_tel=? AND estado='confirmada'",
                            (int(cita_id), tel)).fetchone()
            if not c:
                raise ErrorCita("No se encontró una cita confirmada con esos datos.")
            n = max(1, math.ceil(c["duracion_min"] / SLOT_MIN))
            h, m = map(int, hora.split(":"))
            ini = datetime.combine(fecha, time(h, m))
            if ini not in _inicios_posibles(fecha, n):
                raise ErrorCita("Ese horario no está disponible.")
            if not _libre(con, c["trabajador_id"], ini, ini + timedelta(minutes=c["duracion_min"]), ignorar_id=c["id"]):
                raise ErrorCita("Ese horario ya fue reservado. Elige otro.")
            con.execute("UPDATE citas SET fecha=?, hora=? WHERE id=?", (fecha.isoformat(), hora, c["id"]))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise


def agenda(desde, hasta):
    with conexion() as con:
        q = ("SELECT c.id, c.fecha, c.hora, c.duracion_min, c.servicio, t.nombre AS profesional, "
             "c.paciente_nombre, c.paciente_tel, c.motivo, c.estado, c.origen FROM citas c "
             "JOIN trabajadores t ON t.id=c.trabajador_id WHERE c.fecha BETWEEN ? AND ? ORDER BY c.fecha, c.hora")
        filas = [dict(r) for r in con.execute(q, (desde.isoformat(), hasta.isoformat()))]
    for f in filas:
        f["servicio"] = SERVICIOS.get(f["servicio"], {}).get("nombre", f["servicio"])
    return filas


def cambiar_estado(cita_id, estado):
    if estado not in ESTADOS:
        raise ErrorCita("Estado no válido.")
    with conexion() as con:
        con.execute("UPDATE citas SET estado=? WHERE id=?", (estado, int(cita_id)))


# ----------------------------------------------------------------- registro anonimizado
def anonimizar(texto):
    t = re.sub(r"\S+@\S+", "[correo]", str(texto))
    t = re.sub(r"\d[\d\s\-]{2,}\d|\d{3,}", "[número]", t)
    return t[:200]


def registrar_consulta(texto, intencion, alerta):
    with conexion() as con:
        con.execute(
            "INSERT INTO consultas_anonimas(fecha,texto_anonimizado,intencion,alerta_urgencia) VALUES (?,?,?,?)",
            (date.today().isoformat(), anonimizar(texto) if texto else None, intencion, 1 if alerta else 0),
        )


def consultas_anonimas(limite=200):
    with conexion() as con:
        return [dict(r) for r in con.execute(
            "SELECT fecha, texto_anonimizado, intencion, alerta_urgencia FROM consultas_anonimas ORDER BY id DESC LIMIT ?",
            (limite,))]


# ----------------------------------------------------------------- asistente (reglas)
def normalizar(texto):
    t = unicodedata.normalize("NFD", str(texto).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9: ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


ALARMAS = [
    "sangrad", "sangro", "sangre", "hemorrag", "perdida de liquido", "perdiendo liquido",
    "rompi la fuente", "rompio la fuente", "se rompio la fuente", "contraccion", "contracciones",
    "dolor fuerte", "dolor intenso", "bebe no se mueve", "no siento al bebe", "no siento moverse",
    "no se mueve", "convulsion", "desmay", "fiebre alta", "vision borrosa", "dolor de cabeza fuerte",
    "falta de aire", "dificultad para respirar",
]
MSG_ALARMA = ("⚠️ **Lo que describes puede ser una urgencia.** No esperes una cita: acude de inmediato al "
              "establecimiento de emergencia más cercano o llama al **106 (SAMU)**. "
              "Este asistente no puede evaluar síntomas ni dar diagnósticos. "
              "Avisaré a la obstetra de tu consulta.")

SERVICIO_PATRONES = {
    "ecografia": r"\beco\b|ecograf",
    "psicoprofilaxis": r"psicoprofilaxis|preparacion (para )?(el )?parto|curso de parto",
    "papanicolaou": r"papanicolaou|\bpap\b|citologia",
    "planificacion": r"planificacion|anticoncep|metodo anticonceptivo|\bmac\b",
    "puerperio": r"puerperio|postparto|post parto|despues del parto",
    "prenatal": r"prenatal|embaraz|gestante|gestacion",
    "ginecologia": r"ginecolog|consulta general",
}


def detectar_servicio(txt):
    for clave, pat in SERVICIO_PATRONES.items():
        if re.search(pat, txt):
            return clave
    return None


def detectar_intencion(txt):
    if any(a in txt for a in ALARMAS):
        return "alarma"
    if re.search(r"cancelar|anular|reprogramar|cambiar (mi )?cita|mis citas", txt):
        return "mis_citas"
    if re.search(r"\b(reservar|agendar|separar|programar|solicitar|sacar|pedir)\b", txt) or \
       re.search(r"\b(quiero|necesito|deseo|me gustaria)\b.*\b(cita|atencion|control|ecograf|papanicolaou|pap|consulta)", txt) or \
       txt in ("cita", "una cita", "citas"):
        return "reservar"
    if re.search(r"telefono|numero|llamar|contacto|whatsapp|celular", txt):
        return "contacto"
    if re.search(r"horario|hora de atencion|a que hora|abren|dias de atencion", txt):
        return "horarios"
    if re.search(r"servicio|ofrecen|atienden|que hacen|que atienden|precio|costo", txt):
        return "servicios"
    if re.search(r"donde|direccion|ubicacion|ubican|como llego|carabayllo", txt):
        return "ubicacion"
    if re.search(r"\b(hola|buenas|buen dia|buenos dias|buenas tardes|buenas noches|hey)\b", txt):
        return "saludo"
    if re.search(r"gracias|listo|ok gracias", txt):
        return "gracias"
    return "otro"


def nuevo_estado():
    return {"paso": None, "servicio": None, "fecha": None, "hora": None, "trabajador_id": None,
            "nombre": None, "opciones": [], "consentimiento": False}


def _lista_servicios():
    return "\n".join(f"{i}) {v['nombre']}" for i, (k, v) in enumerate(SERVICIOS.items(), 1))


def _eleccion(txt, n):
    m = re.fullmatch(r"(?:opcion )?(\d{1,2})", txt)
    if m and 1 <= int(m.group(1)) <= n:
        return int(m.group(1)) - 1
    return None


def _fmt_fecha(f):
    return f"{DIAS_ES[f.weekday()]} {f.strftime('%d/%m')}"


def _ofrecer_fechas(est):
    hoy = date.today()
    ops, lineas = [], []
    for d in range(0, DIAS_ADELANTE + 1):
        f = hoy + timedelta(days=d)
        libres = horarios_libres(est["servicio"], f, est["trabajador_id"])
        if libres:
            ops.append(f.isoformat())
            lineas.append(f"{len(ops)}) {_fmt_fecha(f)} ({len(libres)} horarios)")
        if len(ops) == 7:
            break
    if not ops:
        est["paso"] = None
        return "Por ahora no hay horarios libres para ese tipo de cita. Intenta más tarde o llama al consultorio."
    est["opciones"], est["paso"] = ops, "fecha"
    return "¿Qué día prefieres? Escribe el número:\n" + "\n".join(lineas)


def _ofrecer_horas(est):
    f = date.fromisoformat(est["fecha"])
    libres = horarios_libres(est["servicio"], f, est["trabajador_id"])
    if not libres:
        return _ofrecer_fechas(est)
    libres = libres[:12]
    est["opciones"], est["paso"] = libres, "hora"
    lineas = [f"{i}) {x['hora']}" for i, x in enumerate(libres, 1)]
    return f"Horarios libres el {_fmt_fecha(f)}. Escribe el número o la hora (ej. 10:30):\n" + "\n".join(lineas)


def _info_contacto():
    return "\n".join(f"- {t['nombre']}: {t['telefono']}" for t in listar_trabajadores(True))


def _info_horario():
    return ("Atendemos de **lunes a viernes de 9:00 a 13:00 y de 15:00 a 19:00**, y los **sábados de 9:00 a 13:00**. "
            "Los domingos no hay atención.")


def procesar_mensaje(est, texto):
    """Devuelve (respuesta, estado, (intencion, alerta, registrar_texto))."""
    txt = normalizar(texto)[:300]
    if not txt:
        return "Escribe tu consulta o di «quiero una cita».", est, ("otro", False, False)

    en_flujo = est["paso"] is not None
    # 1) Los signos de alarma tienen prioridad sobre cualquier otra regla.
    if any(a in txt for a in ALARMAS):
        nuevo = nuevo_estado()
        return MSG_ALARMA, nuevo, ("alarma", True, True)

    # 2) Dentro del flujo de reserva
    if en_flujo:
        if txt in ("salir", "menu", "volver", "cancelar", "no quiero", "nada"):
            return "Listo, detuve la reserva. ¿En qué más te ayudo?", nuevo_estado(), ("reservar_abandonada", False, False)
        paso = est["paso"]
        if paso == "servicio":
            clave = detectar_servicio(txt)
            if clave is None:
                i = _eleccion(txt, len(SERVICIOS))
                clave = list(SERVICIOS)[i] if i is not None else None
            if clave is None:
                return "No te entendí. Escribe el número del tipo de cita:\n" + _lista_servicios(), est, ("reservar", False, False)
            est["servicio"] = clave
            return f"Perfecto: **{SERVICIOS[clave]['nombre']}**.\n\n" + _ofrecer_fechas(est), est, ("reservar", False, False)
        if paso == "fecha":
            i = _eleccion(txt, len(est["opciones"]))
            if i is None:
                return "Escribe solo el número del día que prefieres.", est, ("reservar", False, False)
            est["fecha"] = est["opciones"][i]
            return _ofrecer_horas(est), est, ("reservar", False, False)
        if paso == "hora":
            ops = est["opciones"]
            i = _eleccion(txt, len(ops))
            if i is None:
                m = re.fullmatch(r"(\d{1,2})[: ]?(\d{2})", txt)
                if m:
                    hh = f"{int(m.group(1)):02d}:{m.group(2)}"
                    i = next((k for k, x in enumerate(ops) if x["hora"] == hh), None)
            if i is None:
                return "Elige uno de los horarios de la lista (número u hora).", est, ("reservar", False, False)
            est["hora"], est["trabajador_id"] = ops[i]["hora"], ops[i]["trabajador_id"]
            est["trabajador"] = ops[i]["trabajador"]
            est["paso"] = "nombre"
            return "¿Cuál es tu nombre completo?", est, ("reservar", False, False)
        if paso == "nombre":
            try:
                est["nombre"] = validar_nombre(texto)
            except ErrorCita as e:
                return str(e), est, ("reservar", False, False)
            est["paso"] = "telefono"
            return "¿Cuál es tu número de celular (9 dígitos)?", est, ("reservar", False, False)
        if paso == "telefono":
            try:
                est["telefono"] = normalizar_telefono(texto)
            except ErrorCita as e:
                return str(e), est, ("reservar", False, False)
            est["paso"] = "confirmar"
            f = date.fromisoformat(est["fecha"])
            return (f"Confirma tu cita:\n\n- **{SERVICIOS[est['servicio']]['nombre']}**\n- {_fmt_fecha(f)} a las **{est['hora']}**\n"
                    f"- Atiende: {est['trabajador']}\n\nAl confirmar aceptas que Mirana Consultores use tu nombre y "
                    "teléfono solo para gestionar tu cita (Ley N.° 29733). ¿Confirmas? (sí / no)"), est, ("reservar", False, False)
        if paso == "confirmar":
            if re.fullmatch(r"si|confirmo|confirmar|ok|dale|claro|correcto|de acuerdo|si confirmo", txt):
                try:
                    c = crear_cita(est["servicio"], date.fromisoformat(est["fecha"]), est["hora"], est["trabajador_id"],
                                   est["nombre"], est["telefono"], "", "asistente", True)
                except ErrorCita as e:
                    return (str(e) + "\n\nEscribe «quiero una cita» para elegir otro horario."), nuevo_estado(), ("reservar", False, False)
                msg = (f"✅ **Cita registrada** (N.° {c['id']}): {c['servicio']}, {_fmt_fecha(c['fecha'])} a las {c['hora']} con {c['trabajador']}.\n\n"
                       f"Si necesitas cambiarla, puedes llamar al {c['telefono_trabajador']} o usar la sección «Mis citas». "
                       "Llega unos minutos antes.")
                return msg, nuevo_estado(), ("reservar_completada", False, False)
            if re.fullmatch(r"no|nop|no confirmo", txt):
                return "Entendido, no registré la cita. ¿Deseas elegir otro horario? Escribe «quiero una cita».", nuevo_estado(), ("reservar_abandonada", False, False)
            return "Responde **sí** para confirmar o **no** para descartar.", est, ("reservar", False, False)

    # 3) Fuera del flujo: intención por reglas
    intent = detectar_intencion(txt)
    if intent == "reservar":
        est = nuevo_estado()
        clave = detectar_servicio(txt)
        if clave:
            est["servicio"] = clave
            return f"Claro, reservemos **{SERVICIOS[clave]['nombre']}**.\n\n" + _ofrecer_fechas(est), est, ("reservar", False, True)
        est["paso"] = "servicio"
        return "Con gusto. ¿Para qué es la cita? Escribe el número:\n" + _lista_servicios(), est, ("reservar", False, True)
    if intent == "mis_citas":
        return "Para ver, cancelar o reprogramar tus citas usa la sección **«Mis citas»** del menú e ingresa tu celular.", est, (intent, False, True)
    if intent == "servicios":
        return "Estos son los tipos de cita disponibles:\n" + "\n".join(f"- **{v['nombre']}**: {v['descr']}" for v in SERVICIOS.values()) + "\n\nDi «quiero una cita» para reservar.", est, (intent, False, True)
    if intent == "horarios":
        return _info_horario(), est, (intent, False, True)
    if intent == "contacto":
        return "Puedes comunicarte con nuestro equipo:\n" + _info_contacto(), est, (intent, False, True)
    if intent == "ubicacion":
        return "Mirana Consultores S.A.C. tiene su domicilio legal en el distrito de Carabayllo, Lima. Confirma la dirección exacta del consultorio con el equipo.", est, (intent, False, True)
    if intent == "saludo":
        return "¡Hola! Soy el asistente virtual de Mirana Consultores. Puedo ayudarte a reservar una cita o resolver dudas frecuentes. No hago diagnósticos. ¿Qué necesitas?", est, (intent, False, False)
    if intent == "gracias":
        return "¡Con gusto! Si necesitas algo más, escríbeme.", est, (intent, False, False)
    return ("No estoy seguro de haber entendido. Puedo ayudarte con: **reservar una cita**, ver **servicios**, **horarios** o "
            "**contacto**. Para consultas sobre tu salud, agenda una cita con la obstetra."), est, ("otro", False, True)
