import streamlit as st
import json
import os
import time
import calendar
from datetime import datetime, timezone, timedelta

# --- ZONA HORARIA VENEZUELA (UTC-4) ---
TZ_VZLA = timezone(timedelta(hours=-4))
DB_FILE_CONTA = "data/contabilidad.json"

def cargar_db_conta():
    os.makedirs("data", exist_ok=True)
    if os.path.exists(DB_FILE_CONTA):
        try:
            with open(DB_FILE_CONTA, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "flujo" not in data: data["flujo"] = []
                if "deudas" not in data: data["deudas"] = []
                if "flujo_personal" not in data: data["flujo_personal"] = []
                if "config" not in data: data["config"] = {"mes_preferido": datetime.now(TZ_VZLA).strftime("%Y-%m")}
                return data
        except Exception: pass
    return {"flujo": [], "deudas": [], "flujo_personal": [], "config": {"mes_preferido": datetime.now(TZ_VZLA).strftime("%Y-%m")}}

def guardar_db_conta(data):
    os.makedirs("data", exist_ok=True)
    with open(DB_FILE_CONTA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def eliminar_movimiento_db(mov_id):
    db = cargar_db_conta()
    db["flujo"] = [m for m in db["flujo"] if m["id"] != mov_id]
    guardar_db_conta(db)

def eliminar_deuda_db(deuda_id):
    db = cargar_db_conta()
    db["deudas"] = [d for d in db["deudas"] if d["id"] != deuda_id]
    guardar_db_conta(db)
    
def eliminar_personal_db(mov_id):
    db = cargar_db_conta()
    db["flujo_personal"] = [m for m in db["flujo_personal"] if m["id"] != mov_id]
    guardar_db_conta(db)

def liquidar_deuda_db(deuda_id):
    db = cargar_db_conta()
    for d in db["deudas"]:
        if d["id"] == deuda_id:
            d["estado"] = "Liquidada"
    guardar_db_conta(db)

@st.dialog("⚠️ Eliminar Movimiento")
def modal_confirmar_eliminacion(mov_id, concepto, monto, moneda):
    st.markdown(f"Vas a eliminar:<br>**{concepto}** por valor de **{monto:,.2f} {moneda}**", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Sí, Eliminar", type="primary", use_container_width=True):
        eliminar_movimiento_db(mov_id)
        st.rerun()
    if c2.button("Cancelar", use_container_width=True): st.rerun()

@st.dialog("⚠️ Eliminar Deuda")
def modal_confirmar_eliminacion_deuda(deuda_id, entidad, monto, moneda):
    st.markdown(f"Vas a eliminar la cuenta de:<br>**{entidad}** por **{monto:,.2f} {moneda}**", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Sí, Eliminar", type="primary", use_container_width=True):
        eliminar_deuda_db(deuda_id)
        st.rerun()
    if c2.button("Cancelar", use_container_width=True): st.rerun()
    
@st.dialog("⚠️ Eliminar Movimiento Personal")
def modal_confirmar_eliminacion_personal(mov_id, concepto, monto, moneda):
    st.markdown(f"Vas a eliminar de tu bolsillo:<br>**{concepto}** por **{monto:,.2f} {moneda}**", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    if c1.button("🗑️ Sí, Eliminar", type="primary", use_container_width=True):
        eliminar_personal_db(mov_id)
        st.rerun()
    if c2.button("Cancelar", use_container_width=True): st.rerun()

@st.dialog("📅 Operativa del Día")
def modal_dia_contabilidad(fecha_str):
    st.markdown(f"<h4 style='text-align:center; color:#3b82f6;'>Día {fecha_str}</h4>", unsafe_allow_html=True)
    db = cargar_db_conta()
    
    registros_hoy = [m for m in db["flujo"] if m["fecha"].startswith(fecha_str) and m["tipo"] in ["Ingreso", "Pérdida"]]
    
    if registros_hoy:
        st.markdown("<p style='font-size:0.85rem; color:#94a3b8; margin-bottom:5px;'>Movimientos de Trading Hoy:</p>", unsafe_allow_html=True)
        for mov in registros_hoy:
            c1, c2, c3 = st.columns([3, 2, 0.8])
            color = "#10b981" if mov["tipo"] == "Ingreso" else "#ef4444"
            signo = "+" if mov["tipo"] == "Ingreso" else "-"
            c1.markdown(f"<span style='font-size:0.85rem; font-weight:bold;'>{mov['concepto']}</span>", unsafe_allow_html=True)
            c2.markdown(f"<div style='text-align:right; color:{color}; font-size:0.85rem; font-weight:bold;'>{signo}{mov['monto']:,.2f} {mov['moneda']}</div>", unsafe_allow_html=True)
            if c3.button("🗑️", key=f"del_dia_{mov['id']}", help="Eliminar para editar"):
                eliminar_movimiento_db(mov['id'])
                st.rerun()
        st.markdown("<hr style='margin: 10px 0; border-color: #1e293b;'>", unsafe_allow_html=True)
    
    with st.form("form_add_ganancia", clear_on_submit=True):
        tipo_mov = st.radio("Naturaleza del movimiento:", ["Ganancia (Ingreso)", "Pérdida (Gasto)"], horizontal=True)
        concepto = st.text_input("Concepto (Opcional)", placeholder="Ej. Arbitraje Binance")
        c1, c2 = st.columns(2)
        monto = c1.number_input("Monto", min_value=0.01, step=1.0)
        moneda = c2.selectbox("Moneda", ["USDT", "VES"])
        
        if st.form_submit_button("💾 Guardar Registro", type="primary", use_container_width=True):
            tipo_final = "Ingreso" if "Ganancia" in tipo_mov else "Pérdida"
            concepto_final = concepto.strip() if concepto.strip() else ("Ganancia P2P" if tipo_final == "Ingreso" else "Pérdida P2P")
            
            db["flujo"].insert(0, {
                "id": f"MOV-{int(time.time())}", 
                "fecha": f"{fecha_str} {datetime.now(TZ_VZLA).strftime('%H:%M')}",
                "tipo": tipo_final, 
                "concepto": concepto_final, 
                "monto": float(monto), 
                "moneda": moneda
            })
            guardar_db_conta(db)
            st.toast("✅ ¡Registro actualizado en la bitácora!")
            st.rerun()

def renderizar_contabilidad():
    st.markdown("""
        <style>
        .badge-rojo { background-color: #450a0a; color: #fca5a5; border: 1px solid #7f1d1d; padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: bold; }
        .badge-verde { background-color: #064e3b; color: #6ee7b7; border: 1px solid #065f46; padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: bold; }
        .summary-card { background: linear-gradient(145deg, #0f172a 0%, #0b1120 100%); border: 1px solid #1e293b; border-radius: 12px; padding: 25px; margin-bottom: 20px; display: flex; justify-content: space-between;}
        .patrimonio-card { background: linear-gradient(145deg, #064e3b 0%, #022c22 100%); border: 1px solid #047857; border-radius: 16px; padding: 30px; text-align: center; margin-top: 30px; box-shadow: 0 10px 20px rgba(0,0,0,0.5);}
        .mes-card { background-color: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; }
        div[data-testid="column"]:has(button[title="Abrir día"]) { position: relative; }
        div[data-testid="stButton"]:has(button[title="Abrir día"]) { position: absolute !important; top: 0; left: 0; right: 0; bottom: 0; z-index: 10; margin: 0 !important; padding: 0 !important; }
        button[title="Abrir día"] { background-color: transparent !important; border: 2px solid transparent !important; color: transparent !important; height: 90px !important; width: 100% !important; box-shadow: none !important; padding: 0 !important; border-radius: 12px !important; transition: all 0.2s ease; }
        button[title="Abrir día"]:hover { border: 2px solid #10b981 !important; background-color: rgba(16, 185, 129, 0.1) !important; box-shadow: 0 0 15px rgba(16, 185, 129, 0.3) !important; }
        </style>
    """, unsafe_allow_html=True)

    st.markdown("<h1 style='text-align:center; color:#3b82f6;'>Bóveda PankiPay 📊</h1>", unsafe_allow_html=True)
    db_conta = cargar_db_conta()

    def guardar_mes_preferido():
        db = cargar_db_conta()
        db["config"]["mes_preferido"] = st.session_state.selector_mes
        guardar_db_conta(db)

    MESES_ES = {"01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril", "05": "Mayo", "06": "Junio", "07": "Julio", "08": "Agosto", "09": "Septiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre"}

    mes_guardado_str = db_conta.get("config", {}).get("mes_preferido", datetime.now(TZ_VZLA).strftime("%Y-%m"))
    meses_completos = [f"{year}-{month:02d}" for year in range(2024, 2031) for month in range(1, 13)]
    meses_lista = sorted(meses_completos, reverse=True)
    idx_guardado = meses_lista.index(mes_guardado_str) if mes_guardado_str in meses_lista else 0

    col_selector, col_vacio = st.columns([1, 2])
    with col_selector:
        mes_seleccionado = st.selectbox(
            "📅 Elegir Mes de Operativa", 
            meses_lista, 
            index=idx_guardado, 
            key="selector_mes",
            on_change=guardar_mes_preferido,
            format_func=lambda x: f"{MESES_ES[x.split('-')[1]]} {x.split('-')[0]}"
        )

    flujo_mes_p2p = [m for m in db_conta["flujo"] if m["fecha"].startswith(mes_seleccionado) and m["moneda"] == "USDT" and m["tipo"] in ["Ingreso", "Gasto", "Pérdida"]]
    ing_mes_usdt = sum(float(m["monto"]) for m in flujo_mes_p2p if m["tipo"] == "Ingreso")
    gas_mes_usdt = sum(float(m["monto"]) for m in flujo_mes_p2p if m["tipo"] in ["Gasto", "Pérdida"])
    neto_mes_usdt = ing_mes_usdt - gas_mes_usdt

    color_n_mes = "#10b981" if neto_mes_usdt >= 0 else "#ef4444"
    signo_n_mes = "+" if neto_mes_usdt > 0 else ""

    st.markdown(f"""
    <div class='summary-card'>
        <div style='text-align: left; width: 33%;'>
            <span style='color: #64748b; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;'>Ganancia P2P (Bruta)</span><br>
            <span style='color: #10b981; font-size: 1.5rem; font-weight: bold;'>+ {ing_mes_usdt:,.2f} USDT</span>
        </div>
        <div style='text-align: center; width: 33%;'>
            <span style='color: #64748b; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;'>Gastos y Pérdidas P2P</span><br>
            <span style='color: #ef4444; font-size: 1.5rem; font-weight: bold;'>- {gas_mes_usdt:,.2f} USDT</span>
        </div>
        <div style='text-align: right; width: 33%;'>
            <span style='color: #64748b; font-size: 0.75rem; font-weight: bold; text-transform: uppercase;'>Profit Mes Actual P2P</span><br>
            <span style='color: {color_n_mes}; font-size: 2rem; font-weight: bold;'>{signo_n_mes}{neto_mes_usdt:,.2f} USDT</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    sub_bitacora, sub_gastos, sub_externos, sub_deudas, sub_historial, sub_personal = st.tabs(["🗓️ Bitácora (Ganancias)", "📉 Gastos P2P", "🌍 Flujos Externos", "🤝 Por Cobrar/Pagar", "📊 Historial Meses", "👤 Finanzas Personales"])

    with sub_bitacora:
        st.markdown("<p style='text-align: center; margin-bottom: 20px; color:#94a3b8;'>Toca cualquier día en el calendario para gestionar ingresos y pérdidas de trading.</p>", unsafe_allow_html=True)
        try:
            año_int, mes_int = map(int, mes_seleccionado.split('-'))
            cal_matrix = calendar.monthcalendar(año_int, mes_int)
            
            neto_diario = {}
            for mov in flujo_mes_p2p:
                dia = int(mov["fecha"].split(' ')[0].split('-')[2])
                if mov["tipo"] == "Ingreso":
                    neto_diario[dia] = neto_diario.get(dia, 0.0) + float(mov["monto"])
                elif mov["tipo"] == "Pérdida":
                    neto_diario[dia] = neto_diario.get(dia, 0.0) - float(mov["monto"])
                    
            dias_semana = ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]
            cols_header = st.columns(7)
            for i, d in enumerate(dias_semana): cols_header[i].markdown(f"<div style='text-align:center; color:#64748b; font-size:0.8rem; font-weight:bold; margin-bottom:10px;'>{d}</div>", unsafe_allow_html=True)
            
            for semana in cal_matrix:
                cols_dias = st.columns(7)
                for i, dia in enumerate(semana):
                    if dia == 0:
                        cols_dias[i].markdown("<div style='height: 90px;'></div>", unsafe_allow_html=True)
                    else:
                        fecha_iter = f"{año_int}-{mes_int:02d}-{dia:02d}"
                        balance_dia = neto_diario.get(dia, 0.0)
                        
                        color_dia = "#334155"
                        txt_dia = "0.00"
                        if balance_dia > 0:
                            color_dia = "#10b981"
                            txt_dia = f"+{balance_dia:,.2f}"
                        elif balance_dia < 0:
                            color_dia = "#ef4444"
                            txt_dia = f"{balance_dia:,.2f}"
                            
                        with cols_dias[i]:
                            st.markdown(f"<div style='text-align:center; height: 90px; display:flex; flex-direction:column; justify-content:center; border: 1px solid #1e293b; border-radius: 12px; background-color: #131b2f;'><span style='color:#94a3b8; font-size:1.1rem; font-weight:bold;'>{dia}</span><span style='color:{color_dia}; font-weight:bold; font-size:0.95rem;'>{txt_dia}</span></div>", unsafe_allow_html=True)
                            if st.button(" ", key=f"btn_dia_{fecha_iter}", help="Abrir día", use_container_width=True):
                                modal_dia_contabilidad(fecha_iter)
        except Exception as e: st.error(f"Error generando calendario: {e}")

    with sub_gastos:
        col_form_gasto, col_lista_gastos = st.columns([1, 2])
        with col_form_gasto:
            with st.container(border=True):
                st.markdown("#### ➖ Registrar Gasto Operativo")
                with st.form("form_flujo_gasto", clear_on_submit=True):
                    f_fecha = st.date_input("Fecha del gasto", value=datetime.now(TZ_VZLA).date())
                    f_concepto = st.text_input("Motivo (Opcional)", placeholder="Ej. Proxy, VPS, Salario")
                    fc_monto, fc_moneda = st.columns([2, 1])
                    f_monto = fc_monto.number_input("Monto", min_value=0.01, step=1.0)
                    f_moneda = fc_moneda.selectbox("Moneda", ["USDT", "VES"])
                    if st.form_submit_button("Guardar Gasto", type="primary", use_container_width=True):
                        concepto_final = f_concepto.strip() if f_concepto.strip() else "Gasto Operativo"
                        db_c = cargar_db_conta()
                        fecha_str_libre = f"{f_fecha.strftime('%Y-%m-%d')} {datetime.now(TZ_VZLA).strftime('%H:%M')}"
                        db_c["flujo"].insert(0, {"id": f"MOV-{int(time.time())}", "fecha": fecha_str_libre, "tipo": "Gasto", "concepto": concepto_final, "monto": float(f_monto), "moneda": f_moneda})
                        guardar_db_conta(db_c)
                        st.rerun()

        with col_lista_gastos:
            with st.container(border=True):
                st.markdown(f"#### 📜 Historial de Gastos P2P ({MESES_ES[mes_seleccionado.split('-')[1]]})")
                gastos_del_mes = [m for m in flujo_mes_p2p if m["tipo"] == "Gasto"]
                if not gastos_del_mes: st.caption(f"No hay gastos operativos registrados en {MESES_ES[mes_seleccionado.split('-')[1]]}.")
                else:
                    for mov in gastos_del_mes:
                        c_info, c_monto, c_del = st.columns([3, 1.5, 0.5])
                        c_info.markdown(f"**{mov['concepto']}**<br><span style='font-size:0.75rem; color:#64748b;'>{mov['fecha']}</span>", unsafe_allow_html=True)
                        c_monto.markdown(f"<div style='text-align: right; color: #ef4444; font-weight: bold;'>- {mov['monto']:,.2f} {mov['moneda']}</div>", unsafe_allow_html=True)
                        if c_del.button("🗑️", key=f"del_gasto_{mov['id']}"): modal_confirmar_eliminacion(mov['id'], mov['concepto'], mov['monto'], mov['moneda'])
                        st.markdown("<hr style='margin: 0.2em 0; border-color: #1e293b;'>", unsafe_allow_html=True)

    with sub_externos:
        col_form_ext, col_lista_ext = st.columns([1, 2])
        with col_form_ext:
            with st.container(border=True):
                st.markdown("#### 🌍 Nuevo Flujo Externo")
                with st.form("form_flujo_externo", clear_on_submit=True):
                    e_tipo = st.radio("Naturaleza:", ["Ingreso Externo", "Gasto Externo"], horizontal=True)
                    e_fecha = st.date_input("Fecha", value=datetime.now(TZ_VZLA).date())
                    e_concepto = st.text_input("Motivo", placeholder="Ej. Inversión")
                    ec_monto, ec_moneda = st.columns([2, 1])
                    e_monto = ec_monto.number_input("Monto", min_value=0.01, step=1.0)
                    e_moneda = ec_moneda.selectbox("Moneda", ["USDT", "VES"])
                    if st.form_submit_button("Guardar Flujo", type="primary", use_container_width=True):
                        db_c = cargar_db_conta()
                        fecha_str_libre = f"{e_fecha.strftime('%Y-%m-%d')} {datetime.now(TZ_VZLA).strftime('%H:%M')}"
                        db_c["flujo"].insert(0, {"id": f"MOV-{int(time.time())}", "fecha": fecha_str_libre, "tipo": e_tipo, "concepto": e_concepto, "monto": float(e_monto), "moneda": e_moneda})
                        guardar_db_conta(db_c)
                        st.rerun()

        with col_lista_ext:
            with st.container(border=True):
                st.markdown(f"#### 📜 Historial de Flujos Externos ({MESES_ES[mes_seleccionado.split('-')[1]]})")
                externos_del_mes = [m for m in db_conta["flujo"] if m["fecha"].startswith(mes_seleccionado) and m["tipo"] in ["Ingreso Externo", "Gasto Externo"]]
                for mov in externos_del_mes:
                    color = "#10b981" if mov["tipo"] == "Ingreso Externo" else "#ef4444"
                    signo = "+" if mov["tipo"] == "Ingreso Externo" else "-"
                    c_info, c_monto, c_del = st.columns([3, 1.5, 0.5])
                    c_info.markdown(f"**{mov['concepto']}** <span style='font-size:0.6rem; background-color:#334155; padding:2px 5px; border-radius:3px;'>EXT</span><br><span style='font-size:0.75rem; color:#64748b;'>{mov['fecha']}</span>", unsafe_allow_html=True)
                    c_monto.markdown(f"<div style='text-align: right; color: {color}; font-weight: bold;'>{signo} {mov['monto']:,.2f} {mov['moneda']}</div>", unsafe_allow_html=True)
                    if c_del.button("🗑️", key=f"del_ext_{mov['id']}"): modal_confirmar_eliminacion(mov['id'], mov['concepto'], mov['monto'], mov['moneda'])
                    st.markdown("<hr style='margin: 0.2em 0; border-color: #1e293b;'>", unsafe_allow_html=True)

    with sub_deudas:
        col_dform, col_dtabla = st.columns([1, 2])
        with col_dform:
            with st.container(border=True):
                st.markdown("#### 📝 Nueva Deuda")
                with st.form("form_deuda", clear_on_submit=True):
                    c_d1, c_d2 = st.columns([1.5, 1])
                    d_tipo = c_d1.radio("Naturaleza:", ["Cobrar (Me deben)", "Pagar (Yo debo)"], horizontal=True)
                    d_fecha = c_d2.date_input("Fecha", value=datetime.now(TZ_VZLA).date())
                    d_entidad = st.text_input("Entidad / Socio / Cliente")
                    dc_monto, dc_moneda = st.columns([2, 1])
                    d_monto = dc_monto.number_input("Monto", min_value=0.01, step=1.0)
                    d_moneda = dc_moneda.selectbox("Moneda", ["USDT", "VES"])
                    if st.form_submit_button("Crear Registro", type="primary", use_container_width=True):
                        if d_entidad.strip():
                            tipo_limpio = "Cobrar" if "Cobrar" in d_tipo else "Pagar"
                            db_conta["deudas"].insert(0, {"id": f"DEU-{int(time.time())}", "fecha": d_fecha.strftime("%Y-%m-%d"), "tipo": tipo_limpio, "entidad": d_entidad.strip(), "monto": float(d_monto), "moneda": d_moneda, "estado": "Pendiente"})
                            guardar_db_conta(db_conta)
                            st.rerun()

        with col_dtabla:
            with st.container(border=True):
                st.markdown("#### ⏳ Cuentas Pendientes")
                pendientes = [d for d in db_conta["deudas"] if d["estado"] == "Pendiente"]
                for d in pendientes:
                    col1, col2, col3, col4 = st.columns([2.5, 1.5, 1, 0.5])
                    badge = "🟢 Por Cobrar" if d["tipo"] == "Cobrar" else "🔴 Por Pagar"
                    col1.markdown(f"**{d['entidad']}**<br><span style='font-size:0.8rem; color:#64748b;'>{badge} | {d['fecha']}</span>", unsafe_allow_html=True)
                    col2.markdown(f"<div style='font-weight: bold;'>{d['monto']:,.2f} {d['moneda']}</div>", unsafe_allow_html=True)
                    if col3.button("✅ Liquidar", key=f"liq_deu_{d['id']}", type="secondary"): 
                        liquidar_deuda_db(d['id'])
                        st.rerun()
                    if col4.button("🗑️", key=f"del_deu_{d['id']}"): modal_confirmar_eliminacion_deuda(d['id'], d['entidad'], d['monto'], d['moneda'])
                    st.markdown("<hr style='margin: 0.2em 0; border-color: #1e293b;'>", unsafe_allow_html=True)

    with sub_historial:
        st.markdown("#### 📊 Historial Comparativo por Mes")
        resumen_meses = {}
        for m in db_conta["flujo"]:
            if m["moneda"] == "USDT":
                mes_llave = m["fecha"][:7] 
                if mes_llave not in resumen_meses: resumen_meses[mes_llave] = {"ingresos": 0.0, "gastos": 0.0}
                
                if m["tipo"] == "Ingreso": resumen_meses[mes_llave]["ingresos"] += float(m["monto"])
                elif m["tipo"] in ["Gasto", "Pérdida"]: resumen_meses[mes_llave]["gastos"] += float(m["monto"])
                    
        for mes in sorted(resumen_meses.keys(), reverse=True):
            ing = resumen_meses[mes]["ingresos"]
            gas = resumen_meses[mes]["gastos"]
            neto = ing - gas
            color_hist = "#10b981" if neto >= 0 else "#ef4444"
            signo_hist = "+" if neto > 0 else ""
            st.markdown(f"""
            <div class="mes-card">
                <div style='width: 25%; font-weight: bold; color: #f8fafc; font-size: 1.1rem;'>🗓️ {MESES_ES[mes.split('-')[1]]} {mes.split('-')[0]}</div>
                <div style='width: 25%; text-align: center;'><span style='font-size: 0.75rem; color:#64748b; text-transform: uppercase;'>Ingresos P2P</span><br><span style='color:#10b981; font-weight:bold; font-size: 1.1rem;'>+ {ing:,.2f} USDT</span></div>
                <div style='width: 25%; text-align: center;'><span style='font-size: 0.75rem; color:#64748b; text-transform: uppercase;'>Gastos P2P</span><br><span style='color:#ef4444; font-weight:bold; font-size: 1.1rem;'>- {gas:,.2f} USDT</span></div>
                <div style='width: 25%; text-align: right;'><span style='font-size: 0.75rem; color:#64748b; text-transform: uppercase;'>Profit Operativo</span><br><span style='color:{color_hist}; font-weight:bold; font-size: 1.4rem;'>{signo_hist}{neto:,.2f} USDT</span></div>
            </div>
            """, unsafe_allow_html=True)

    with sub_personal:
        flujo_per_usdt = [m for m in db_conta["flujo_personal"] if m["moneda"] == "USDT"]
        total_ingresos_per = sum(float(m["monto"]) for m in flujo_per_usdt if m["tipo"] == "Ingreso")
        total_gastos_per = sum(float(m["monto"]) for m in flujo_per_usdt if m["tipo"] == "Gasto")
        neto_personal = total_ingresos_per - total_gastos_per
        color_neto_per = "#10b981" if neto_personal >= 0 else "#ef4444"
        
        st.markdown(f"""
        <div style='background-color: #0f172a; border: 1px solid #3b82f6; border-radius: 12px; padding: 20px; display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;'>
            <div><span style='color: #64748b; font-size: 0.8rem; font-weight: bold; text-transform: uppercase;'>Dinero Entrante</span><br><span style='color: #10b981; font-size: 1.2rem; font-weight: bold;'>+ {total_ingresos_per:,.2f} USDT</span></div>
            <div><span style='color: #64748b; font-size: 0.8rem; font-weight: bold; text-transform: uppercase;'>Dinero Gastado</span><br><span style='color: #ef4444; font-size: 1.2rem; font-weight: bold;'>- {total_gastos_per:,.2f} USDT</span></div>
            <div style='text-align: right; background-color: #1e293b; padding: 10px 20px; border-radius: 8px;'><span style='color: #60a5fa; font-size: 0.85rem; font-weight: bold; text-transform: uppercase;'>Mi Bolsillo Actual</span><br><span style='color: {color_neto_per}; font-size: 1.8rem; font-weight: bold;'>{neto_personal:,.2f} USDT</span></div>
        </div>
        """, unsafe_allow_html=True)
        
        col_form_per, col_lista_per = st.columns([1, 2])
        with col_form_per:
            with st.container(border=True):
                st.markdown("#### ➕ Registrar Movimiento")
                with st.form("form_personal", clear_on_submit=True):
                    p_fecha = st.date_input("Fecha", value=datetime.now(TZ_VZLA).date())
                    p_tipo = st.radio("Tipo:", ["Ingreso", "Gasto"], horizontal=True)
                    p_concepto = st.text_input("Concepto (Opcional)")
                    pc_monto, pc_moneda = st.columns([2, 1])
                    p_monto = pc_monto.number_input("Monto", min_value=0.01, step=1.0)
                    p_moneda = pc_moneda.selectbox("Moneda", ["USDT", "VES"])
                    if st.form_submit_button("Guardar en mi bolsillo", type="primary", use_container_width=True):
                        db_c = cargar_db_conta()
                        fecha_str_per = f"{p_fecha.strftime('%Y-%m-%d')} {datetime.now(TZ_VZLA).strftime('%H:%M')}"
                        db_c["flujo_personal"].insert(0, {"id": f"PER-{int(time.time())}", "fecha": fecha_str_per, "tipo": p_tipo, "concepto": p_concepto, "monto": float(p_monto), "moneda": p_moneda})
                        guardar_db_conta(db_c)
                        st.rerun()
                        
        with col_lista_per:
            with st.container(border=True):
                st.markdown(f"#### 📜 Historial Personal ({MESES_ES[mes_seleccionado.split('-')[1]]})")
                personal_del_mes = [m for m in db_conta["flujo_personal"] if m["fecha"].startswith(mes_seleccionado)]
                for mov in personal_del_mes:
                    color = "#10b981" if mov["tipo"] == "Ingreso" else "#ef4444"
                    signo = "+" if mov["tipo"] == "Ingreso" else "-"
                    c_info, c_monto, c_del = st.columns([3, 1.5, 0.5])
                    c_info.markdown(f"**{mov['concepto']}**<br><span style='font-size:0.75rem; color:#64748b;'>{mov['fecha']}</span>", unsafe_allow_html=True)
                    c_monto.markdown(f"<div style='text-align: right; color: {color}; font-weight: bold;'>{signo} {mov['monto']:,.2f} {mov['moneda']}</div>", unsafe_allow_html=True)
                    if c_del.button("🗑️", key=f"del_per_{mov['id']}"): modal_confirmar_eliminacion_personal(mov['id'], mov['concepto'], mov['monto'], mov['moneda'])
                    st.markdown("<hr style='margin: 0.2em 0; border-color: #1e293b;'>", unsafe_allow_html=True)

    st.markdown("<hr style='border-color: #1e293b; margin: 40px 0;'>", unsafe_allow_html=True)
    st.markdown("<h3 style='text-align:center;'>🏦 Balance Patrimonial Global (Solo Empresa)</h3>", unsafe_allow_html=True)

    total_ingresos_empresa = sum(float(m["monto"]) for m in db_conta["flujo"] if m["moneda"] == "USDT" and m["tipo"] == "Ingreso")
    total_gastos_empresa = sum(float(m["monto"]) for m in db_conta["flujo"] if m["moneda"] == "USDT" and m["tipo"] in ["Gasto", "Pérdida"])
    profit_historico = total_ingresos_empresa - total_gastos_empresa

    ingreso_ext = sum(float(m["monto"]) for m in db_conta["flujo"] if m["moneda"] == "USDT" and m["tipo"] == "Ingreso Externo")
    gasto_ext = sum(float(m["monto"]) for m in db_conta["flujo"] if m["moneda"] == "USDT" and m["tipo"] == "Gasto Externo")
    capital_externo_neto = ingreso_ext - gasto_ext

    cobrar_usdt_global = sum(float(d["monto"]) for d in db_conta["deudas"] if d["tipo"] == "Cobrar" and d["moneda"] == "USDT" and d["estado"] == "Pendiente")
    pagar_usdt_global = sum(float(d["monto"]) for d in db_conta["deudas"] if d["tipo"] == "Pagar" and d["moneda"] == "USDT" and d["estado"] == "Pendiente")

    capital_total = profit_historico + capital_externo_neto + cobrar_usdt_global - pagar_usdt_global
    color_cap = "#10b981" if capital_total >= 0 else "#ef4444"

    st.markdown(f"""
    <div class='patrimonio-card'>
        <div style='display:flex; justify-content:space-between; margin-bottom: 20px;'>
            <div><span style='color:#a7f3d0; font-size:0.8rem;'>GANANCIAS (P2P)</span><br><span style='color:#34d399; font-weight:bold; font-size:1.1rem;'>+ {total_ingresos_empresa:,.2f}</span></div>
            <div><span style='color:#fca5a5; font-size:0.8rem;'>GASTOS (P2P)</span><br><span style='color:#ef4444; font-weight:bold; font-size:1.1rem;'>- {total_gastos_empresa:,.2f}</span></div>
            <div><span style='color:#e2e8f0; font-size:0.8rem;'>CAPITAL EXTERNO</span><br><span style='color:#cbd5e1; font-weight:bold; font-size:1.1rem;'>+ {capital_externo_neto:,.2f}</span></div>
            <div><span style='color:#bae6fd; font-size:0.8rem;'>POR COBRAR</span><br><span style='color:#38bdf8; font-weight:bold; font-size:1.1rem;'>+ {cobrar_usdt_global:,.2f}</span></div>
            <div><span style='color:#fca5a5; font-size:0.8rem;'>POR PAGAR</span><br><span style='color:#ef4444; font-weight:bold; font-size:1.1rem;'>- {pagar_usdt_global:,.2f}</span></div>
        </div>
        <div style='background-color:#022c22; padding: 15px; border-radius: 10px; border: 1px solid #065f46;'>
            <span style='color:#6ee7b7; font-size:1rem; font-weight:bold; text-transform:uppercase; letter-spacing:2px;'>Capital Total Estimado</span><br>
            <span style='color:{color_cap}; font-size:3rem; font-weight:bold;'>{capital_total:,.2f} USDT</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
