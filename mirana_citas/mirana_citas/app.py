# -*- coding: utf-8 -*-
"""
Mirana Consultores S.A.C. - Plataforma web con asistente virtual para citas obstétricas
Prototipo (MVP, semana 8). Ejecutar con:  streamlit run app.py
Todos los datos de ejemplo son SINTÉTICOS.
"""
import hmac
import os
from datetime import date, timedelta

import streamlit as st

import logica as L

st.set_page_config(page_title="Mirana Consultores – Citas obstétricas", page_icon="🩺", layout="centered")
L.iniciar_bd()

CONSENTIMIENTO = ("Acepto que Mirana Consultores S.A.C. use mi nombre y teléfono únicamente para gestionar mi cita, "
                  "conforme a la Ley N.° 29733 de Protección de Datos Personales.")


def fmt_fecha(f):
    return f"{L.DIAS_ES[f.weekday()]} {f.strftime('%d/%m/%Y')}"


def nombre_servicio(clave):
    return L.SERVICIOS.get(clave, {}).get("nombre", clave)


# ------------------------------------------------------------------ Reservar cita
def pagina_reservar():
    st.header("Reservar una cita")
    st.caption("Elige para qué es la cita, el día y el horario. Atendemos de lunes a sábado.")

    clave = st.selectbox(
        "¿Para qué es la cita?",
        list(L.SERVICIOS),
        format_func=lambda k: f"{L.SERVICIOS[k]['nombre']} ({L.SERVICIOS[k]['min']} min)",
    )
    st.caption(L.SERVICIOS[clave]["descr"])

    trabs = L.trabajadores_para(clave)
    if not trabs:
        st.warning("Por ahora no hay profesionales habilitadas para este tipo de cita.")
        return
    nombres = {t["id"]: t["nombre"] for t in trabs}
    prof = st.selectbox(
        "Profesional",
        [None] + list(nombres),
        format_func=lambda i: "Cualquiera disponible" if i is None else nombres[i],
    )

    hoy = date.today()
    f = st.date_input("Fecha", value=hoy + timedelta(days=1), min_value=hoy,
                      max_value=hoy + timedelta(days=L.DIAS_ADELANTE))
    libres = L.horarios_libres(clave, f, prof)
    idx = None
    if libres:
        idx = st.selectbox("Horario", range(len(libres)),
                           format_func=lambda i: f"{libres[i]['hora']} · {libres[i]['trabajador']}")
    else:
        st.warning("No hay horarios libres ese día (domingo cerrado, o agenda llena). Prueba con otra fecha.")

    nombre = st.text_input("Nombre completo", max_chars=60)
    tel = st.text_input("Celular (9 dígitos)", max_chars=15, placeholder="9XXXXXXXX")
    motivo = st.text_area("Motivo o comentario (opcional, no escribas datos médicos sensibles)", max_chars=200)
    acepto = st.checkbox(CONSENTIMIENTO)

    if st.button("Confirmar reserva", type="primary", disabled=not libres):
        try:
            h = libres[idx]
            c = L.crear_cita(clave, f, h["hora"], h["trabajador_id"], nombre, tel, motivo, "web", acepto)
            st.success(f"✅ Cita registrada (N.° {c['id']}): {c['servicio']}, {fmt_fecha(c['fecha'])} a las "
                       f"{c['hora']} con {c['trabajador']}. Para cambios puedes llamar al {c['telefono_trabajador']}.")
        except L.ErrorCita as e:
            st.error(str(e))


# ------------------------------------------------------------------ Asistente virtual
def pagina_chat():
    st.header("Asistente virtual")
    st.info("Conversas con un **asistente automático** basado en reglas. No da diagnósticos ni indica tratamientos. "
            "Si es una urgencia, acude a emergencias o llama al 106 (SAMU).")

    if "chat_estado" not in st.session_state:
        st.session_state.chat_estado = L.nuevo_estado()
        st.session_state.chat_msgs = [{"rol": "assistant", "texto":
                                        "¡Hola! Soy el asistente de Mirana Consultores. Puedo ayudarte a **reservar una cita** "
                                        "(control prenatal, ecografía, psicoprofilaxis, planificación familiar, Papanicolaou, "
                                        "puerperio o consulta ginecológica) y resolver dudas sobre **horarios, servicios y contacto**."}]

    if st.button("Reiniciar conversación"):
        del st.session_state["chat_estado"]
        del st.session_state["chat_msgs"]
        st.rerun()

    for m in st.session_state.chat_msgs:
        with st.chat_message(m["rol"]):
            st.markdown(m["texto"])

    entrada = st.chat_input("Escribe tu mensaje…", max_chars=300)
    if entrada:
        st.session_state.chat_msgs.append({"rol": "user", "texto": entrada})
        resp, estado, (intencion, alerta, registrar) = L.procesar_mensaje(st.session_state.chat_estado, entrada)
        st.session_state.chat_estado = estado
        st.session_state.chat_msgs.append({"rol": "assistant", "texto": resp})
        # Registro anonimizado: nunca se guarda el texto de los pasos de nombre o teléfono.
        L.registrar_consulta(entrada if registrar else None, intencion, alerta)
        st.rerun()


# ------------------------------------------------------------------ Mis citas
def pagina_mis_citas():
    st.header("Mis citas")
    tel = st.text_input("Ingresa el celular con el que reservaste", max_chars=15, placeholder="9XXXXXXXX")
    if st.button("Buscar mis citas"):
        st.session_state.tel_busqueda = tel
    tel = st.session_state.get("tel_busqueda")
    if not tel:
        return
    try:
        citas = L.citas_de_paciente(tel)
    except L.ErrorCita as e:
        st.error(str(e))
        return
    if not citas:
        st.info("No encontramos citas con ese celular.")
        return
    hoy = date.today()
    for c in citas:
        f = date.fromisoformat(c["fecha"])
        with st.container(border=True):
            st.markdown(f"**{nombre_servicio(c['servicio'])}** · {fmt_fecha(f)} {c['hora']} · {c['trabajador']}")
            st.caption(f"Cita N.° {c['id']} · Estado: {c['estado']}")
            if c["estado"] == "confirmada" and f >= hoy:
                col1, col2 = st.columns(2)
                if col1.button("Cancelar cita", key=f"can_{c['id']}"):
                    try:
                        L.cancelar_cita(c["id"], tel)
                        st.success("Cita cancelada.")
                        st.rerun()
                    except L.ErrorCita as e:
                        st.error(str(e))
                with col2.expander("Reprogramar"):
                    nf = st.date_input("Nueva fecha", value=max(f, hoy + timedelta(days=1)), min_value=hoy,
                                       max_value=hoy + timedelta(days=L.DIAS_ADELANTE), key=f"nf_{c['id']}")
                    libres = [x for x in L.horarios_libres(c["servicio"], nf, c["trabajador_id"])]
                    if libres:
                        h = st.selectbox("Nuevo horario", [x["hora"] for x in libres], key=f"nh_{c['id']}")
                        if st.button("Confirmar cambio", key=f"rep_{c['id']}"):
                            try:
                                L.reprogramar_cita(c["id"], tel, nf, h)
                                st.success("Cita reprogramada.")
                                st.rerun()
                            except L.ErrorCita as e:
                                st.error(str(e))
                    else:
                        st.caption("Sin horarios libres ese día con la misma profesional.")


# ------------------------------------------------------------------ Panel del personal
def clave_panel():
    try:
        if "PANEL_CLAVE" in st.secrets:
            return str(st.secrets["PANEL_CLAVE"])
    except Exception:
        pass
    return os.environ.get("PANEL_CLAVE", "demo1234")


def pagina_panel():
    st.header("Panel del personal")
    if not st.session_state.get("panel_ok"):
        ingreso = st.text_input("Clave de acceso", type="password")
        if st.button("Ingresar"):
            if hmac.compare_digest(ingreso.encode(), clave_panel().encode()):
                st.session_state.panel_ok = True
                st.rerun()
            else:
                st.error("Clave incorrecta.")
        if clave_panel() == "demo1234":
            st.caption("Modo demostración: clave por defecto «demo1234». Define PANEL_CLAVE en los secretos antes de publicar.")
        return

    if st.button("Cerrar sesión"):
        st.session_state.panel_ok = False
        st.rerun()

    t_agenda, t_estado, t_equipo, t_consultas = st.tabs(["Agenda", "Cambiar estado", "Equipo y teléfonos", "Consultas anónimas"])

    with t_agenda:
        hoy = date.today()
        c1, c2 = st.columns(2)
        desde = c1.date_input("Desde", value=hoy, key="ag_desde")
        hasta = c2.date_input("Hasta", value=hoy + timedelta(days=7), key="ag_hasta")
        filas = L.agenda(desde, hasta)
        if filas:
            st.dataframe(filas, use_container_width=True, hide_index=True)
        else:
            st.info("No hay citas en ese rango.")

    with t_estado:
        filas = [f for f in L.agenda(date.today() - timedelta(days=30), date.today() + timedelta(days=L.DIAS_ADELANTE))]
        if not filas:
            st.info("No hay citas para gestionar.")
        else:
            sel = st.selectbox("Cita", filas, format_func=lambda f: f"N.° {f['id']} · {f['fecha']} {f['hora']} · {f['servicio']} · {f['profesional']} · {f['estado']}")
            nuevo = st.selectbox("Nuevo estado", L.ESTADOS, index=L.ESTADOS.index(sel["estado"]) if sel["estado"] in L.ESTADOS else 0)
            if st.button("Guardar estado"):
                L.cambiar_estado(sel["id"], nuevo)
                st.success("Estado actualizado.")
                st.rerun()

    with t_equipo:
        st.caption("Edita el nombre y el teléfono de cada integrante del equipo. Estos teléfonos los muestra el asistente a las pacientes.")
        for t in L.listar_trabajadores():
            with st.form(f"form_trab_{t['id']}"):
                st.markdown("**Atiende:** " + ", ".join(nombre_servicio(s) for s in t["servicios"].split(",")))
                nom = st.text_input("Nombre", value=t["nombre"], max_chars=60, key=f"nom_{t['id']}")
                tel = st.text_input("Teléfono celular", value=t["telefono"], max_chars=15, key=f"tel_{t['id']}")
                act = st.checkbox("Activa (recibe citas)", value=bool(t["activo"]), key=f"act_{t['id']}")
                if st.form_submit_button("Guardar cambios"):
                    try:
                        L.actualizar_trabajador(t["id"], nom, tel, act)
                        st.success("Datos actualizados.")
                    except L.ErrorCita as e:
                        st.error(str(e))

    with t_consultas:
        filas = L.consultas_anonimas()
        if not filas:
            st.info("Aún no hay consultas registradas.")
        else:
            conteo = {}
            for f in filas:
                conteo[f["intencion"]] = conteo.get(f["intencion"], 0) + 1
            st.bar_chart(conteo)
            st.metric("Alertas de urgencia detectadas", sum(f["alerta_urgencia"] for f in filas))
            st.dataframe(filas, use_container_width=True, hide_index=True)


# ------------------------------------------------------------------ Navegación
st.sidebar.title("🩺 Mirana Consultores")
pagina = st.sidebar.radio("Menú", ["Reservar cita", "Asistente virtual", "Mis citas", "Panel del personal"])
st.sidebar.caption("Prototipo con datos sintéticos · No reemplaza la atención profesional.")

if pagina == "Reservar cita":
    pagina_reservar()
elif pagina == "Asistente virtual":
    pagina_chat()
elif pagina == "Mis citas":
    pagina_mis_citas()
else:
    pagina_panel()
