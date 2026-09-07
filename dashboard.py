import streamlit as st
import json
import os
import sys
import time
import hmac
import hashlib
import requests
import asyncio
import calendar
import platform
import subprocess
import threading
from urllib.parse import urlencode
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timezone, timedelta

# --- 1. GESTIÓN DE RUTAS Y VARIABLES GLOBALES ---
TZ_VZLA = timezone(timedelta(hours=-4))
DOMINIO_LICENCIAS = "https://bot-p2p-pankipay-licencias.9zousu.easypanel.host"

# 🔥 FIX VITAL: Ruta absoluta obligatoria al volumen blindado de EasyPanel 🔥
DIR_DATA = "/app/data"
os.makedirs(DIR_DATA, exist_ok=True)
DB_FILE_CONTA = os.path.join(DIR_DATA, "contabilidad.json")
ESTADO_FILE = os.path.join(DIR_DATA, "estado_bot.json")

def obtener_hwid_actual():
    hwid_env = os.environ.get("BOT_HWID", "").strip()
    if hwid_env: return hwid_env.upper()
    try:
        if platform.system() == "Windows":
            cmd = 'powershell "(Get-CimInstance Win32_ComputerSystemProduct).UUID"'
            resultado = subprocess.check_output(cmd, shell=True).decode().strip()
        else:
            resultado = platform.node()
        return hashlib.md5(resultado.encode()).hexdigest()[:10].upper()
    except Exception: return "DEFAULT_HWID"

# --- 2. GESTIÓN DE ESTADO P2P ---
def sanitizar_estado(estado):
    if not isinstance(estado, dict): estado = {}
    if "estrategias_sniper" in estado:
        for k, v in estado["estrategias_sniper"].items():
            v.pop("limite_min_bs", None)
            v.pop("limite_max_bs", None)
    for k in ["bancos", "cuentas", "limites", "credenciales", "saldos", "cuentas_fondeo"]:
        if k not in estado: estado[k] = {}
    if "config" not in estado: estado["config"] = {"dinero_durmiendo": 100000.0, "nombre_bot": "PANKIPAY"}
    if "estrategias_sniper" not in estado: estado["estrategias_sniper"] = {}
    if "ordenes_vivas" not in estado: estado["ordenes_vivas"] = {"pendientes": [], "por_liberar": [], "en_cuarentena": [], "procesando": []}
    if "cola_test" not in estado: estado["cola_test"] = []
    if "cola_fondeo" not in estado: estado["cola_fondeo"] = []
    if "anuncios_detectados" not in estado: estado["anuncios_detectados"] = []
    if "sniper_switch" not in estado: estado["sniper_switch"] = False
    if "master_switch" not in estado: estado["master_switch"] = False
    return estado

def cargar_estado():
    if os.path.exists(ESTADO_FILE):
        for _ in range(10):
            try:
                with open(ESTADO_FILE, "rb") as f:
                    contenido = f.read().decode("utf-8", errors="ignore")
                    estado = json.loads(contenido)
                    if estado: return sanitizar_estado(estado)
            except Exception: time.sleep(0.1)
    return sanitizar_estado({})

def guardar_estado(estado):
    # 🔥 ESCUDO ANTI-BORRADOS EN EL PANEL (100% LOCAL) 🔥
    if not estado or "bancos" not in estado: return
    
    os.makedirs(DIR_DATA, exist_ok=True)
    temp_file = os.path.join(DIR_DATA, "estado_bot_tmp.json")
    try:
        json_data = json.dumps(estado, ensure_ascii=False, indent=4)
        with open(temp_file, "w", encoding="utf-8") as f: 
            f.write(json_data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, ESTADO_FILE)
    except Exception: pass

estado_global = cargar_estado()
NOMBRE_BOT = estado_global.get("config", {}).get("nombre_bot", "VORTEX").strip().upper()

# --- 3. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title=NOMBRE_BOT, page_icon="logo.jpg", layout="wide") 

if "last_refresh_count" not in st.session_state: st.session_state.last_refresh_count = 0
if "posiciones_mercado" not in st.session_state: st.session_state.posiciones_mercado = {}

# --- 4. FUNCIÓN DE BLOQUEO / LOGIN ---
def check_password():
    SUPER_USER = "FrankDiaz14"
    SUPER_PASS = "Panki18**"
    
    TEMP_USER = os.environ.get("ADMIN_USER", "usuario")
    TEMP_PASS = os.environ.get("ADMIN_PASS", "12345")
    
    cliente_user = TEMP_USER
    cliente_pass = TEMP_PASS
    try:
        if os.path.exists(ESTADO_FILE):
            with open(ESTADO_FILE, "rb") as f:
                data_tmp = json.loads(f.read().decode("utf-8", errors="ignore"))
                cliente_user = data_tmp.get("config", {}).get("login_user", TEMP_USER)
                cliente_pass = data_tmp.get("config", {}).get("login_pass", TEMP_PASS)
    except: pass

    token_url = ""
    try:
        if hasattr(st, "query_params"): token_url = st.query_params.get("token", "")
        else: token_url = st.experimental_get_query_params().get("token", [""])[0]
    except: pass
    
    if token_url == SUPER_PASS or token_url == cliente_pass: 
        return True

    def password_entered():
        input_u = st.session_state["username"]
        input_p = st.session_state["password"]
        
        es_master = (input_u == SUPER_USER and input_p == SUPER_PASS)
        es_cliente = (input_u == cliente_user and input_p == cliente_pass)
        
        if es_master or es_cliente:
            st.session_state["password_correct"] = True
            try:
                if hasattr(st, "query_params"): st.query_params["token"] = input_p
                else: st.experimental_set_query_params(token=input_p)
            except: pass
            del st.session_state["password"] 
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state or not st.session_state["password_correct"]:
        st.markdown(f"<h1 style='text-align: center; color: #3b82f6; margin-top: 50px;'>⬢ {NOMBRE_BOT}</h1>", unsafe_allow_html=True)
        st.markdown("<h4 style='text-align: center; margin-bottom: 30px;'>Acceso de Usuario</h4>", unsafe_allow_html=True)
        col1, col2, col3 = st.columns([1, 1.5, 1])
        with col2:
            with st.container(border=True):
                st.text_input("Usuario", key="username")
                st.text_input("Contraseña", type="password", key="password")
                st.markdown("<br>", unsafe_allow_html=True)
                st.button("Iniciar Sesión", on_click=password_entered, type="primary", use_container_width=True)
                if "password_correct" in st.session_state and not st.session_state["password_correct"]:
                    st.error("🚫 Usuario o contraseña incorrectos")
        return False
    return True

if not check_password(): st.stop()

# --- FUNCIONES DE BASE DE DATOS CONTABILIDAD ---
def cargar_db_conta():
    os.makedirs(DIR_DATA, exist_ok=True)
    if os.path.exists(DB_FILE_CONTA):
        try:
            with open(DB_FILE_CONTA, "rb") as f:
                contenido = f.read().decode("utf-8", errors="ignore")
                data = json.loads(contenido)
                if "flujo" not in data: data["flujo"] = []
                if "deudas" not in data: data["deudas"] = []
                if "flujo_personal" not in data: data["flujo_personal"] = []
                if "config" not in data: data["config"] = {"mes_preferido": datetime.now(TZ_VZLA).strftime("%Y-%m")}
                return data
        except Exception: pass
    return {"flujo": [], "deudas": [], "flujo_personal": [], "config": {"mes_preferido": datetime.now(TZ_VZLA).strftime("%Y-%m")}}

def guardar_db_conta(data):
    if not data: return # 🔥 ESCUDO CONTABILIDAD
    os.makedirs(DIR_DATA, exist_ok=True)
    temp_file = os.path.join(DIR_DATA, "contabilidad_tmp.json")
    try:
        json_data = json.dumps(data, ensure_ascii=False, indent=4)
        with open(temp_file, "w", encoding="utf-8") as f:
            f.write(json_data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, DB_FILE_CONTA)
    except Exception: pass

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
            if c3.button("🗑️", key=f"del_dia_{mov['id']}", help="Eliminar"):
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

# --- FUNCIONES DE BINANCE API ---
def fetch_mis_anuncios(api_key, api_secret):
    if not api_key or not api_secret: return {"success": False, "msg": "Faltan credenciales API"}
    url = "https://api.binance.com/sapi/v1/c2c/ads/listWithPagination"
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    signature = hmac.new(api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    payload_json = {"page": 1, "rows": 50}
    headers = {"X-MBX-APIKEY": api_key, "Content-Type": "application/json;charset=utf-8", "clientType": "WEB"}
    try:
        response = requests.post(f"{url}?{query_string}&signature={signature}", headers=headers, json=payload_json, timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("success") or str(res_json.get("code")) == "000000": return {"success": True, "data": res_json.get("data", [])}
            else: return {"success": False, "msg": str(res_json.get("message", "Error Binance"))}
        else: return {"success": False, "msg": f"HTTP {response.status_code}"}
    except Exception as e: return {"success": False, "msg": str(e)}

def cambiar_estado_anuncio(api_key, api_secret, ad_number, nuevo_estado):
    if not api_key or not api_secret: return {"success": False, "msg": "Faltan credenciales API"}
    url = "https://api.binance.com/sapi/v1/c2c/ads/updateStatus"
    timestamp = int(time.time() * 1000)
    query_string = f"timestamp={timestamp}"
    signature = hmac.new(api_secret.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()
    payload_json = {"advNos": [str(ad_number)], "advStatus": int(nuevo_estado)}
    headers = {"X-MBX-APIKEY": api_key, "Content-Type": "application/json;charset=utf-8", "clientType": "WEB"}
    try:
        response = requests.post(f"{url}?{query_string}&signature={signature}", headers=headers, json=payload_json, timeout=10)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("success") or str(res_json.get("code")) == "000000": return {"success": True}
            else: return {"success": False, "msg": str(res_json.get("message", "Error Binance"))}
        else: return {"success": False, "msg": f"HTTP {response.status_code}"}
    except Exception as e: return {"success": False, "msg": str(e)}

def obtener_posicion_real_mercado(asset, fiat, trade_type, ad_config, mi_precio, mi_nickname):
    url = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"
    search_type = "SELL" if trade_type.upper() == "BUY" else "BUY"
    payload = {"page": 1, "rows": 20, "asset": asset, "tradeType": search_type, "fiat": fiat, "publisherType": "merchant"}
    vol_min = float(ad_config.get("volumen_minimo", 0.0))
    if vol_min > 0: payload["transAmount"] = str(int(vol_min)) if vol_min.is_integer() else str(vol_min)
    pay_types = ad_config.get("pay_types", [])
    if pay_types and pay_types[0] not in ["Todos", "all", "cualquiera"]: payload["payTypes"] = pay_types
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=3)
        if resp.status_code == 200:
            data = resp.json().get("data", [])
            posicion_real = 1
            for comp in data:
                nick = comp.get("advertiser", {}).get("nickName", "").strip().lower()
                if mi_nickname and nick == mi_nickname.strip().lower(): return posicion_real
                posicion_real += 1
            pos_estimada = 1
            mi_precio_float = float(mi_precio)
            for comp in data:
                comp_price = float(comp.get("adv", {}).get("price", 0.0))
                if search_type == "BUY": 
                    if mi_precio_float <= comp_price: return pos_estimada
                else: 
                    if mi_precio_float >= comp_price: return pos_estimada
                pos_estimada += 1
            return min(pos_estimada, 20)
    except Exception: pass
    return int(ad_config.get("posicion_objetivo", 1))

# CSS OPTIMIZADO ANTI-PARPADEO E INTEGRADO
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;} header {visibility: hidden;} footer {visibility: hidden;}
    [data-testid="stAppViewContainer"] > main { opacity: 1 !important; transition: none !important; filter: none !important; }
    [data-testid="stAppViewBlockContainer"] { opacity: 1 !important; transition: none !important; filter: none !important; pointer-events: auto !important; }
    div[data-testid="stStatusWidget"] { display: none !important; visibility: hidden !important; opacity: 0 !important; }
    div[data-testid="stVerticalBlock"] { transition: none !important; opacity: 1 !important; }
    .element-container { transition: none !important; opacity: 1 !important; }
    .stApp { opacity: 1 !important; background-color: #050810 !important; transition: none !important; }
    .block-container { max-width: 1200px; padding-top: 2rem; }
    div[data-testid="stVerticalBlock"] > div[style*="border"] { background-color: #0f172a !important; border: 1px solid #1e293b !important; border-radius: 16px !important; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5) !important; padding: 20px !important; }
    p, .stMarkdown p { color: #94a3b8; } h1, h2, h3, h4, h5, h6 { color: #f8fafc !important; font-weight: 600 !important; }
    .stTabs [data-baseweb="tab-list"] { gap: 10px; background-color: #0f172a; padding: 10px; border-radius: 12px; border: 1px solid #1e293b; flex-wrap: wrap; }
    .stTabs [data-baseweb="tab"] { background-color: transparent !important; border: none !important; color: #94a3b8 !important; border-radius: 8px !important; padding: 10px 20px !important; }
    .stTabs [aria-selected="true"] { background-color: #1e293b !important; color: #3b82f6 !important; box-shadow: 0 0 10px rgba(59, 130, 246, 0.2); }
    .stButton > button[kind="primary"] { background-color: #3b82f6 !important; color: #ffffff !important; border: none !important; border-radius: 8px !important; font-weight: bold !important; }
    .stButton > button[kind="primary"]:hover { background-color: #2563eb !important; box-shadow: 0 0 15px rgba(59, 130, 246, 0.4) !important; }
    .stButton > button[kind="secondary"] { background-color: #1e293b !important; color: #60a5fa !important; border: 1px solid #3b82f6 !important; border-radius: 8px !important; font-weight: bold !important; }
    .badge-rojo { background-color: #450a0a; color: #fca5a5; border: 1px solid #7f1d1d; padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: bold; }
    .badge-verde { background-color: #064e3b; color: #6ee7b7; border: 1px solid #065f46; padding: 4px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: bold; }
    .cuarentena-box { background-color: #450a0a; border-left: 4px solid #ef4444; padding: 10px; margin-bottom: 10px; border-radius: 4px; }
    
    /* CSS ESPECIFICO FINANZAS */
    .summary-card { background: linear-gradient(145deg, #0f172a 0%, #0b1120 100%); border: 1px solid #1e293b; border-radius: 12px; padding: 25px; margin-bottom: 20px; display: flex; justify-content: space-between;}
    .patrimonio-card { background: linear-gradient(145deg, #064e3b 0%, #022c22 100%); border: 1px solid #047857; border-radius: 16px; padding: 30px; text-align: center; margin-top: 30px; box-shadow: 0 10px 20px rgba(0,0,0,0.5);}
    .mes-card { background-color: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 20px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; }
    div[data-testid="column"]:has(button[title="Abrir día"]) { position: relative; }
    div[data-testid="stButton"]:has(button[title="Abrir día"]) { position: absolute !important; top: 0; left: 0; right: 0; bottom: 0; z-index: 10; margin: 0 !important; padding: 0 !important; }
    button[title="Abrir día"] { background-color: transparent !important; border: 2px solid transparent !important; color: transparent !important; height: 90px !important; width: 100% !important; box-shadow: none !important; padding: 0 !important; border-radius: 12px !important; transition: all 0.2s ease; }
    button[title="Abrir día"]:hover { border: 2px solid #10b981 !important; background-color: rgba(16, 185, 129, 0.1) !important; box-shadow: 0 0 15px rgba(16, 185, 129, 0.3) !important; }
    </style>
""", unsafe_allow_html=True)

cuentas_totales = list(estado_global.get("cuentas", {}).keys())
cuentas_operadoras = [c for c in cuentas_totales if estado_global.get("bancos", {}).get(c, {}).get("tipo", "Operadora") == "Operadora"]
cuentas_matrices = [c for c in cuentas_totales if estado_global.get("bancos", {}).get(c, {}).get("tipo", "Operadora") == "Matriz"]
cuentas_directorio_fondeo = estado_global.get("cuentas_fondeo", {})

def parse_monto(m_str):
    try:
        return float(str(m_str).replace(".", "").replace(",", "."))
    except:
        return 0.0

@st.dialog("🧪 Test de Disparo Banesco")
def abrir_modal_test(lista_cuentas):
    # 🔥 AHORA ES UN SELECTOR DESPLEGABLE 🔥
    cuenta_activa = st.selectbox("Cuenta emisora:", lista_cuentas)
    
    tipo_test = st.radio("Tipo de Operación:", ["Pago Móvil", "Transferencia Banesco"])
    
    if tipo_test == "Pago Móvil":
        banco_destino = st.selectbox("Banco Destino:", [
            "0102 - Venezuela", "0104 - Ven. de Crédito", "0105 - Mercantil", 
            "0108 - Provincial", "0114 - Bancaribe", "0134 - Banesco", 
            "0151 - BFC", "0156 - 100% Banco", "0172 - Bancamiga", 
            "0175 - Bicentenario", "0191 - BNC"
        ], index=10)
        codigo_banco = banco_destino[:4]
        telefono = st.text_input("Teléfono:", value="04127808697")
        ci_destino = st.text_input("Cédula:", value="V28719673")
        cuenta_destino = ""
    else:
        cuenta_destino = st.text_input("Cuenta Banesco (20 dígitos):", value="01340087320871069020")
        ci_destino = st.text_input("Cédula:", value="28046607")
        telefono = ""
        codigo_banco = ""

    monto_test = st.text_input("Monto (Bs):", value="1.00")
    
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    
    if col1.button("🚀 Lanzar Prueba", type="primary", use_container_width=True):
        if not ci_destino:
            st.error("Faltan datos por llenar.")
            return
            
        payload = {
            "id": f"TEST-{int(time.time())}",
            "tipo": "PAGO_MOVIL" if tipo_test == "Pago Móvil" else "TRANSFERENCIA",
            "monto": monto_test,
            "cuenta_origen": cuenta_activa,
            "cuenta_destino": cuenta_destino,
            "ci_destino": ci_destino,
            "telefono": telefono,
            "banco_destino": codigo_banco
        }
        estado_global["cola_test"].append(payload)
        guardar_estado(estado_global)
        st.session_state.forzar_pausa = False # 🔥 QUITA LA PAUSA INVISIBLE
        st.toast("✅ Orden de prueba enviada al motor.")
        st.rerun()
        
    if col2.button("Cancelar", use_container_width=True): 
        st.session_state.forzar_pausa = False # 🔥 QUITA LA PAUSA INVISIBLE
        st.rerun()

if "forzar_pausa" not in st.session_state: st.session_state.forzar_pausa = False

col_logo, col_espacio, col_enc = st.columns([1, 0.5, 1.5])
with col_logo: 
    st.markdown(f"<strong style='color: #3b82f6; font-size: 1.2rem;'><span style='font-size: 1.5rem;'>⬢</span> {NOMBRE_BOT}</strong> <span style='color: #475569; font-size: 0.8rem; margin-left: 10px;'>PRO TERMINAL</span>", unsafe_allow_html=True)

with col_enc: 
    c_p1, c_p2 = st.columns([1.5, 1])
    # Le quitamos el "key" al toggle para que Streamlit no lo bloquee
    with c_p1: modo_edicion = st.toggle("⏸️ Pausar Panel (Para escribir)", value=False)
    with c_p2: st.markdown("<div style='text-align: right; padding-top: 5px;'><span class='badge-verde'>🟢 SECURE</span></div>", unsafe_allow_html=True)

refresh_count = 0
# 🔥 El auto-refresco se detiene si le das al Toggle manual O si el modal activa la pausa invisible 🔥
if not modo_edicion and not st.session_state.forzar_pausa: 
    refresh_count = st_autorefresh(interval=5000, limit=None, key="panel_refresh")
else: 
    refresh_count = st.session_state.last_refresh_count
    
is_timer_rerun = (refresh_count != st.session_state.last_refresh_count)
st.session_state.last_refresh_count = refresh_count

st.markdown("<br>", unsafe_allow_html=True)
tab_panel, tab_autoad, tab_fondeo, tab_config, tab_conta = st.tabs(["🤖 Auto-Pay Bot", "📢 Auto-Ad", "💸 Fondeo Matriz", "⚙️ Configuración", "📊 Contabilidad"])

# ==========================================
# 🤖 PESTAÑA: AUTO-PAY BOT
# ==========================================
with tab_panel:
    col_title, col_test, col_motor = st.columns([2.5, 1, 1.5]) 
    with col_title:
        st.markdown("### 🗄️ Auto-Pay Bot")
        st.caption("Solo cuentas operadoras asignadas a Binance.")
    with col_test:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("🧪 TEST", use_container_width=True):
            # 🔥 REVISA SI HAY CUENTAS REGISTRADAS, SIN IMPORTAR SI ESTÁN APAGADAS 🔥
            if not cuentas_operadoras: 
                st.error("No tienes cuentas Operadoras registradas en Configuración.")
            else: 
                st.session_state.forzar_pausa = True # 🔥 ACTIVA LA PAUSA INVISIBLE
                abrir_modal_test(cuentas_operadoras) # 🔥 MANDA TODAS LAS CUENTAS AL MODAL
    with col_motor:
        st.markdown("""<style>button:has(div:contains("KILL SWITCH")) { background-color: #dc2626 !important; border-color: #991b1b !important; color: white !important; } button:has(div:contains("KILL SWITCH")):hover { background-color: #b91c1c !important; box-shadow: 0 0 15px rgba(220, 38, 38, 0.5) !important; }</style>""", unsafe_allow_html=True)
        is_master_on = estado_global.get("master_switch", False)
        if is_master_on:
            st.markdown("<div style='margin-top: -5px;'></div>", unsafe_allow_html=True)
            if st.button("🛑 PARADA SUAVE", help="Deja de tomar órdenes nuevas.", use_container_width=True):
                estado_global["master_switch"] = False; guardar_estado(estado_global); st.rerun()
            
            if st.button("🚨 KILL SWITCH", help="Mata el programa al instante.", use_container_width=True):
                estado_global["master_switch"] = False
                estado_global["emergencia"] = True
                if "ordenes_vivas" in estado_global:
                    estado_global["ordenes_vivas"]["procesando"] = []
                guardar_estado(estado_global)
                st.toast("🚨 SEÑAL DE EMERGENCIA Y LIMPIEZA", icon="🚨")
                st.rerun()
        else:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("▶ INICIAR AUTO-PAY", type="primary", use_container_width=True):
                estado_global["master_switch"] = True
                estado_global["emergencia"] = False  
                guardar_estado(estado_global)
                st.rerun()

    st.markdown("---")
    col_izq, col_der = st.columns([1.2, 2])
    
    with col_izq:
        with st.container(border=True):
            st.markdown("#### 🔗 Configuración RPA")
            st.caption("Logs de pagos en Telegram.")
            if is_master_on: st.markdown("<span class='badge-verde'>🟢 Motor Activo</span>", unsafe_allow_html=True)
            else: st.markdown("<span class='badge-rojo'>⏹ Motor Inactivo</span>", unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown("#### 🏦 Hub Financiero (Operadoras)")
            saldo_operativo = sum(float(estado_global.get("saldos", {}).get(c, 0.0)) for c in cuentas_operadoras)
            st.markdown(f"<div style='background-color: #064e3b; padding: 15px; border-radius: 8px; color: #34d399; margin-bottom: 15px; border: 1px solid #047857;'><b>💰 Capital Operativo:</b><br><span style='font-size: 1.5rem;'>Bs. {saldo_operativo:,.2f}</span></div>", unsafe_allow_html=True)
            if not cuentas_operadoras: st.caption("No hay cuentas Operadoras registradas.")
            for cuenta in cuentas_operadoras:
                with st.container(border=True):
                    c_nombre, c_toggle = st.columns([3, 1])
                    saldo_individual = float(estado_global.get("saldos", {}).get(cuenta, 0.0))
                    banco_str = estado_global.get("bancos", {}).get(cuenta, {}).get("banco", "Banesco")
                    c_nombre.markdown(f"**{cuenta}** <span style='font-size:0.75rem; color:#60a5fa;'>({banco_str})</span><br><span style='color: #94a3b8; font-size: 0.8rem;'>💳 Bs. {saldo_individual:,.2f}</span>", unsafe_allow_html=True)
                    
                    is_active = estado_global["cuentas"].get(cuenta, False)
                    toggle_key = f"tgl_{cuenta}"
                    if toggle_key not in st.session_state: st.session_state[toggle_key] = is_active
                    elif st.session_state[toggle_key] != is_active: st.session_state[toggle_key] = is_active
                    
                    def callback_toggle(c_name):
                        est = cargar_estado(); est["cuentas"][c_name] = st.session_state[f"tgl_{c_name}"]; guardar_estado(est)
                    nuevo_estado = c_toggle.toggle(" ", key=toggle_key, on_change=callback_toggle, args=(cuenta,), label_visibility="collapsed")
                    
                    if nuevo_estado:
                        limites_acc = estado_global["limites"].get(cuenta, {})
                        if "TRANSFERENCIA" not in limites_acc:
                            v_min = limites_acc.get("min", "0")
                            v_max = limites_acc.get("max", "9999999")
                            limites_acc = {
                                "TRANSFERENCIA": {"activo": True, "min": v_min, "max": v_max},
                                "PAGO_MOVIL": {"activo": False, "min": "0", "max": "50000"}
                            }
                            estado_global["limites"][cuenta] = limites_acc
                            guardar_estado(estado_global)
                        
                        st.markdown("<div style='font-size:0.75rem; font-weight:bold; color:#cbd5e1; margin-top:10px; margin-bottom:5px; border-bottom:1px solid #1e293b; padding-bottom:3px;'>MÉTODOS HABILITADOS</div>", unsafe_allow_html=True)
                        
                        c_chk1, c_min1, c_max1 = st.columns([1.5, 1, 1])
                        act_trans = c_chk1.checkbox("🏦 Transf.", value=limites_acc["TRANSFERENCIA"]["activo"], key=f"trans_{cuenta}")
                        min_trans, max_trans = limites_acc["TRANSFERENCIA"]["min"], limites_acc["TRANSFERENCIA"]["max"]
                        if act_trans:
                            min_trans = c_min1.text_input("Min (Bs)", value=limites_acc["TRANSFERENCIA"]["min"], key=f"mint_{cuenta}", label_visibility="collapsed")
                            max_trans = c_max1.text_input("Max (Bs)", value=limites_acc["TRANSFERENCIA"]["max"], key=f"maxt_{cuenta}", label_visibility="collapsed")

                        c_chk2, c_min2, c_max2 = st.columns([1.5, 1, 1])
                        act_pm = c_chk2.checkbox("📱 Pago Móvil", value=limites_acc["PAGO_MOVIL"]["activo"], key=f"pm_{cuenta}")
                        min_pm, max_pm = limites_acc["PAGO_MOVIL"]["min"], limites_acc["PAGO_MOVIL"]["max"]
                        if act_pm:
                            min_pm = c_min2.text_input("Min (Bs)", value=limites_acc["PAGO_MOVIL"]["min"], key=f"minp_{cuenta}", label_visibility="collapsed")
                            max_pm = c_max2.text_input("Max (Bs)", value=limites_acc["PAGO_MOVIL"]["max"], key=f"maxp_{cuenta}", label_visibility="collapsed")
                            
                        if (act_trans != limites_acc["TRANSFERENCIA"]["activo"] or min_trans != limites_acc["TRANSFERENCIA"]["min"] or max_trans != limites_acc["TRANSFERENCIA"]["max"] or
                            act_pm != limites_acc["PAGO_MOVIL"]["activo"] or min_pm != limites_acc["PAGO_MOVIL"]["min"] or max_pm != limites_acc["PAGO_MOVIL"]["max"]):
                            estado_global["limites"][cuenta] = {
                                "TRANSFERENCIA": {"activo": act_trans, "min": min_trans, "max": max_trans},
                                "PAGO_MOVIL": {"activo": act_pm, "min": min_pm, "max": max_pm}
                            }
                            guardar_estado(estado_global)

    with col_der:
        with st.container(border=True):
            st.markdown("#### 🖥 Terminal de Operaciones")
            st.markdown("""<div class="terminal-box"><div class="icon-server">🗄️</div><h3 style="color:white;">Motor de Pagos</h3><p style="color:#94a3b8;">Controla la emisión y liberación P2P.</p></div>""", unsafe_allow_html=True)

        balances = estado_global.get("balances_binance", {})
        if balances:
            usdt_disp = balances.get("usdt_disponible", 0.0)
            usdt_ord = balances.get("usdt_en_ordenes", 0.0)
            cap_total = balances.get("capital_total", 0.0)
            
            with st.container(border=True):
                st.markdown("#### 💼 Capital Binance")
                c1, c2, c3 = st.columns(3)
                c1.metric("USDT Billeteras (Spot+Fondos)", f"{usdt_disp:,.2f}")
                c2.metric("USDT en Órdenes", f"+ {usdt_ord:,.2f}")
                c3.metric("Capital Total (USDT)", f"{cap_total:,.2f}")

        with st.container(border=True):
            c_tit_ord, c_btn_ord = st.columns([2.5, 1])
            with c_tit_ord:
                st.markdown("#### 👁 Órdenes (En Vivo)")
            with c_btn_ord:
                if st.button("🧹 Limpiar", use_container_width=True, help="Borra fantasmas visuales congelados."):
                    if "ordenes_vivas" in estado_global:
                        estado_global["ordenes_vivas"] = {"pendientes": [], "por_liberar": [], "en_cuarentena": [], "procesando": []}
                    estado_global["emergencia"] = False 
                    guardar_estado(estado_global)
                    st.toast("✅ Pizarra limpiada perfectamente.")
                    st.rerun()

            procesando = estado_global["ordenes_vivas"].get("procesando", [])
            en_cuarentena = estado_global["ordenes_vivas"].get("en_cuarentena", [])
            pendientes = estado_global["ordenes_vivas"].get("pendientes", [])
            por_liberar = estado_global["ordenes_vivas"].get("por_liberar", [])

            tot_ves = 0.0
            tot_usdt = 0.0
            for ord_list in [procesando, en_cuarentena, pendientes]:
                for o in ord_list:
                    tot_ves += parse_monto(o.get("monto", "0"))
                    tot_usdt += parse_monto(o.get("monto_usdt", "0"))

            tot_acum_ves = 0.0
            tot_acum_usdt = 0.0
            for o in por_liberar:
                tot_acum_ves += parse_monto(o.get("monto", "0"))
                tot_acum_usdt += parse_monto(o.get("monto_usdt", "0"))

            if tot_ves > 0 or tot_usdt > 0 or tot_acum_ves > 0 or tot_acum_usdt > 0:
                st.markdown(f"""
                <div style='display: flex; gap: 15px; margin-bottom: 15px; flex-wrap: wrap;'>
                    <div style='flex: 1; min-width: 200px; background-color: #0b1120; border: 1px solid #1e293b; border-radius: 8px; padding: 12px;'>
                        <div style='color: #94a3b8; font-size: 0.75rem; text-align: center; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px;'>Pendiente por Pagar</div>
                        <div style='display: flex; justify-content: space-around; align-items: center;'>
                            <div style='text-align: center;'><span style='color: #ef4444; font-weight: bold; font-size: 1.1rem;'>Bs. {tot_ves:,.2f}</span></div>
                            <div style='color: #334155;'>|</div>
                            <div style='text-align: center;'><span style='color: #60a5fa; font-weight: bold; font-size: 1.1rem;'>{tot_usdt:,.2f} USDT</span></div>
                        </div>
                    </div>
                    <div style='flex: 1; min-width: 200px; background-color: #0b1120; border: 1px solid #1e293b; border-radius: 8px; padding: 12px;'>
                        <div style='color: #94a3b8; font-size: 0.75rem; text-align: center; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 5px;'>Acumulado (Por Liberar)</div>
                        <div style='display: flex; justify-content: space-around; align-items: center;'>
                            <div style='text-align: center;'><span style='color: #10b981; font-weight: bold; font-size: 1.1rem;'>Bs. {tot_acum_ves:,.2f}</span></div>
                            <div style='color: #334155;'>|</div>
                            <div style='text-align: center;'><span style='color: #60a5fa; font-weight: bold; font-size: 1.1rem;'>{tot_acum_usdt:,.2f} USDT</span></div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            if procesando:
                st.markdown(f"**⚡ Procesando Pago ({len(procesando)})**")
                for ord in procesando: 
                    usdt_text = f"<br><span style='color:#60a5fa; font-size: 0.9rem;'>Recibe: <strong>{ord.get('monto_usdt', '0,00')} USDT</strong></span>"
                    st.markdown(f"<div style='background-color: #064e3b; border-left: 4px solid #10b981; padding: 10px; margin-bottom: 10px; border-radius: 4px;'><span style='color: #6ee7b7; font-size: 0.85rem;'>Bot operando en el banco...</span><br><code>{ord['id']}</code> — <strong>{ord['monto']} VES</strong>{usdt_text}</div>", unsafe_allow_html=True)
                st.divider()

            st.markdown(f"**⚠️ En Cuarentena (Chat) ({len(en_cuarentena)})**")
            if en_cuarentena: 
                for ord in en_cuarentena: 
                    usdt_text = f"<br><span style='color:#60a5fa; font-size: 0.9rem;'>Recibe: <strong>{ord.get('monto_usdt', '0,00')} USDT</strong></span>"
                    st.markdown(f"<div class='cuarentena-box'><code>{ord['id']}</code> — <strong>{ord['monto']} VES</strong>{usdt_text}</div>", unsafe_allow_html=True)
            elif not procesando:
                st.caption("Ninguna orden en espera.")
            st.divider()
            
            st.markdown(f"**Pendiente por pagar ({len(pendientes)})**")
            if pendientes:
                for ord in pendientes: 
                    usdt_text = f"<br><span style='color:#60a5fa; font-size: 0.85rem; margin-left: 18px;'>↳ Recibe: {ord.get('monto_usdt', '0,00')} USDT</span>"
                    st.markdown(f"↳ `{ord['id']}` — **{ord['monto']} VES**{usdt_text}", unsafe_allow_html=True)
            else:
                st.caption("Ninguna orden bajo control.")
            st.divider() 
            
            st.markdown(f"**Por liberar ({len(por_liberar)})**")
            if por_liberar:
                for ord in por_liberar: 
                    usdt_text = f"<br><span style='color:#60a5fa; font-size: 0.85rem; margin-left: 18px;'>↳ Recibe: {ord.get('monto_usdt', '0,00')} USDT</span>"
                    st.markdown(f"↳ `{ord['id']}` — **{ord['monto']} VES**{usdt_text}", unsafe_allow_html=True)
            else:
                st.caption("Ninguna orden esperando.")

# ==========================================
# 📢 PESTAÑA: AUTO-AD (Radar y Sniper)
# ==========================================
with tab_autoad:
    col_title_ad, col_motor_ad = st.columns([3, 1.2])
    with col_title_ad:
        st.markdown("### 📢 Auto-Ad (Multi-Sniper)")
        is_sniper_on = estado_global.get("sniper_switch", False)
        if is_sniper_on: st.markdown("<span class='badge-verde'>🟢 SNIPER GLOBAL ACTIVO</span>", unsafe_allow_html=True)
        else: st.markdown("<span class='badge-rojo'>⏹ SNIPER GLOBAL INACTIVO</span>", unsafe_allow_html=True)
        
    with col_motor_ad:
        st.markdown("<br>", unsafe_allow_html=True)
        if is_sniper_on:
            if st.button("🛑 DETENER TODO EL SNIPER", type="primary", use_container_width=True):
                estado_global["sniper_switch"] = False; guardar_estado(estado_global); st.rerun()
        else:
            if st.button("▶ INICIAR MULTI-SNIPER", type="primary", use_container_width=True):
                estado_global["sniper_switch"] = True; guardar_estado(estado_global); st.rerun()
                
    st.markdown("---")

    vivas_ad = estado_global.get("ordenes_vivas", {})
    procesando_ad = vivas_ad.get("procesando", [])
    cuarentena_ad = vivas_ad.get("en_cuarentena", [])
    pendientes_ad = vivas_ad.get("pendientes", [])
    
    tot_pagar_ves_ad = 0.0
    tot_pagar_usdt_ad = 0.0
    for ord_list in [procesando_ad, cuarentena_ad, pendientes_ad]:
        for o in ord_list:
            tot_pagar_ves_ad += parse_monto(o.get("monto", "0"))
            tot_pagar_usdt_ad += parse_monto(o.get("monto_usdt", "0"))

    if tot_pagar_ves_ad > 0 or tot_pagar_usdt_ad > 0:
        st.markdown(f"""
        <div style='background: linear-gradient(145deg, #0f172a 0%, #0b1120 100%); border: 1px solid #3b82f6; border-radius: 12px; padding: 20px; margin-bottom: 25px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 4px 10px rgba(0,0,0,0.3);'>
            <div>
                <span style='color: #93c5fd; font-size: 0.85rem; font-weight: bold; text-transform: uppercase; letter-spacing: 1px;'>⏳ Pendiente por Pagar (En Espera + Cuarentena)</span><br>
                <span style='color: #ef4444; font-size: 1.6rem; font-weight: bold;'>Bs. {tot_pagar_ves_ad:,.2f}</span>
            </div>
            <div style='text-align: right;'>
                <span style='color: #60a5fa; font-size: 2.2rem; font-weight: bold; text-shadow: 0 0 10px rgba(59, 130, 246, 0.4);'>{tot_pagar_usdt_ad:,.2f} USDT</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

    api_k_current = estado_global.get("credenciales", {}).get("binance_api_key", "")
    api_s_current = estado_global.get("credenciales", {}).get("binance_api_secret", "")
    mi_nickname_global = estado_global.get("config", {}).get("mi_nickname", "")
    
    with st.container(border=True):
        col_f1, col_f2, col_f3, col_btn = st.columns([1.5, 1.5, 1.5, 1])
        with col_f1: filtro_tipo = st.radio("Tipo", ["Todo", "Compra", "Venta"], horizontal=True, label_visibility="collapsed")
        with col_f2: filtro_estado = st.radio("Estado", ["Todo", "Activos", "Pausados", "Cerrados"], horizontal=True, label_visibility="collapsed")
        with col_f3: 
            auto_refresh = st.toggle("⏱️ Auto-Refrescar (5s)", value=False)
            if auto_refresh and not is_sniper_on: st.markdown("<div style='margin-top:-10px;'><span style='color:#ef4444; font-size:0.75rem;'>⚠️ En pausa</span></div>", unsafe_allow_html=True)
        with col_btn:
            do_refresh = st.button("🔄 Refrescar", type="secondary", use_container_width=True)
            
            if do_refresh or (auto_refresh and is_timer_rerun and is_sniper_on):
                res = fetch_mis_anuncios(api_k_current, api_s_current)
                if res["success"]:
                    estado_global["anuncios_detectados"] = res["data"]
                    guardar_estado(estado_global)
                    if do_refresh: 
                        st.session_state.posiciones_mercado = {} 
                        st.rerun()
                else: 
                    if not auto_refresh: st.error(f"Error: {res['msg']}")
                        
    anuncios = estado_global.get("anuncios_detectados", [])
    anuncios_filtrados = []
    for ad in anuncios:
        tipo_binance = ad.get("tradeType", "")
        estado_binance = ad.get("advStatus", 0) 
        if filtro_tipo == "Compra" and tipo_binance != "BUY": continue
        if filtro_tipo == "Venta" and tipo_binance != "SELL": continue
        if filtro_estado == "Activos" and estado_binance != 1: continue
        if filtro_estado == "Pausados" and estado_binance != 3: continue
        if filtro_estado == "Cerrados" and estado_binance == 4: continue
        anuncios_filtrados.append(ad)
        
    st.markdown("<br>", unsafe_allow_html=True)
    if not anuncios_filtrados: st.markdown("<div style='text-align:center; padding:50px; border:1px dashed #334155; border-radius:10px;'>No se encontraron anuncios.</div>", unsafe_allow_html=True)
    else:
        for ad in anuncios_filtrados:
            ad_no = ad.get("advNo", "N/A"); asset = ad.get("asset", "USDT"); fiat = ad.get("fiatUnit", "VES"); price = ad.get("price", "0.00"); trade_type = ad.get("tradeType", "N/A"); adv_status = ad.get("advStatus", 0)
            tipo_color = "#10b981" if trade_type == "BUY" else "#ef4444" 
            tipo_label = "COMPRA" if trade_type == "BUY" else "VENTA"
            ad_config = estado_global.get("estrategias_sniper", {}).get(ad_no, {})
            es_sniper_activo = ad_config.get("activo", False)
            
            if adv_status == 1: badge_status = "<span class='badge-verde'>Activo</span>"
            elif adv_status == 3: badge_status = "<span class='badge-gris'>Pausado</span>"
            elif adv_status == 4: badge_status = "<span class='badge-rojo'>Cerrado</span>"
            else: badge_status = f"<span class='badge-gris'>Desconocido</span>"
            if es_sniper_activo: badge_status += " <span class='badge-sniper'>🎯 SNIPER</span>"
                
            with st.container(border=True):
                col1, col2, col3 = st.columns([2.5, 2, 1])
                with col1:
                    st.markdown(f"<strong style='color: {tipo_color};'>{tipo_label} {asset}</strong> <span style='color: #94a3b8; font-size: 0.85rem; margin-left: 10px;'>ID: {ad_no}</span>", unsafe_allow_html=True)
                    st.markdown(f"<span style='color: #94a3b8; font-size: 0.85rem;'>Precio actual</span><br><span style='font-size: 1.3rem; font-weight: bold; color: #f8fafc;'>{price} {fiat}</span>", unsafe_allow_html=True)
                with col2:
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown(f"<div style='text-align: right;'><span style='color: #94a3b8; font-size: 0.85rem;'>Limites Binance</span><br><span style='color: #e2e8f0; font-size: 0.9rem;'>{ad.get('minSingleTransAmount', '0')} - {ad.get('maxSingleTransAmount', '0')} {fiat}</span></div>", unsafe_allow_html=True)
                with col3:
                    st.markdown(f"<div style='text-align: right; margin-bottom: 10px;'>{badge_status}</div>", unsafe_allow_html=True)
                    if adv_status == 1:
                        if st.button("⏸ Pausar", key=f"pause_{ad_no}", use_container_width=True):
                            if cambiar_estado_anuncio(api_k_current, api_s_current, ad_no, 3)["success"]:
                                res_r = fetch_mis_anuncios(api_k_current, api_s_current)
                                if res_r["success"]: estado_global["anuncios_detectados"] = res_r["data"]; guardar_estado(estado_global)
                                st.rerun()
                    elif adv_status == 3:
                        if st.button("▶ Activar", key=f"play_{ad_no}", type="primary", use_container_width=True):
                            if cambiar_estado_anuncio(api_k_current, api_s_current, ad_no, 1)["success"]:
                                res_r = fetch_mis_anuncios(api_k_current, api_s_current)
                                if res_r["success"]: estado_global["anuncios_detectados"] = res_r["data"]; guardar_estado(estado_global)
                                st.rerun()
                
                if adv_status in [1, 3]: 
                    if ad_no not in st.session_state.posiciones_mercado: 
                        with st.spinner("🔍 Analizando posición en el mercado..."):
                            st.session_state.posiciones_mercado[ad_no] = obtener_posicion_real_mercado(asset, fiat, trade_type, ad_config, price, mi_nickname_global)
                    pos_actual_real = st.session_state.posiciones_mercado[ad_no]
                else: 
                    pos_actual_real = int(ad_config.get("posicion_objetivo", 1))
                    
                st.markdown(f"<div style='text-align: center; color: #94a3b8; font-size: 0.85rem; margin-bottom: 10px;'>📍 Tu posición en mercado: <b style='color:#60a5fa;'>#{pos_actual_real}</b></div>", unsafe_allow_html=True)

                col_man1, col_man2 = st.columns(2)
                pos_arriba = max(1, pos_actual_real - 1)
                pos_abajo = pos_actual_real + 1
                if col_man1.button(f"🔼 Atacar Posición {pos_arriba}" if pos_actual_real > 1 else "🔄 Defender Posición 1", key=f"btn_up_{ad_no}", use_container_width=True):
                    with st.spinner("Apuntando y ejecutando ajuste..."):
                        if "estrategias_sniper" not in estado_global: estado_global["estrategias_sniper"] = {}
                        if ad_no not in estado_global["estrategias_sniper"]: estado_global["estrategias_sniper"][ad_no] = {}
                        estado_global["estrategias_sniper"][ad_no]["posicion_objetivo"] = pos_arriba
                        estado_global["estrategias_sniper"][ad_no]["activo"] = True 
                        guardar_estado(estado_global)
                        
                        try:
                            from actions.auto_pricer import ejecutar_ajuste_mercado
                            temp_config = estado_global["estrategias_sniper"][ad_no].copy()
                            temp_config["mi_nickname"] = mi_nickname_global
                            asyncio.run(ejecutar_ajuste_mercado(temp_config, estado_global))
                        except Exception as e: pass
                        
                        st.session_state.posiciones_mercado.pop(ad_no, None)
                        st.rerun()

                if col_man2.button(f"🔽 Atacar Posición {pos_abajo}", key=f"btn_down_{ad_no}", use_container_width=True):
                    with st.spinner("Apuntando y ejecutando ajuste..."):
                        if "estrategias_sniper" not in estado_global: estado_global["estrategias_sniper"] = {}
                        if ad_no not in estado_global["estrategias_sniper"]: estado_global["estrategias_sniper"][ad_no] = {}
                        estado_global["estrategias_sniper"][ad_no]["posicion_objetivo"] = pos_abajo
                        estado_global["estrategias_sniper"][ad_no]["activo"] = True 
                        guardar_estado(estado_global)
                        
                        try:
                            from actions.auto_pricer import ejecutar_ajuste_mercado
                            temp_config = estado_global["estrategias_sniper"][ad_no].copy()
                            temp_config["mi_nickname"] = mi_nickname_global
                            asyncio.run(ejecutar_ajuste_mercado(temp_config, estado_global))
                        except Exception as e: pass
                        
                        st.session_state.posiciones_mercado.pop(ad_no, None)
                        st.rerun()

                with st.expander("🎯 Configurar Estrategia Sniper"):
                    with st.form(key=f"form_sniper_{ad_no}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            pricer_activo = st.toggle("Activar Auto-Ajustador", value=ad_config.get("activo", False), key=f"act_{ad_no}")
                            vol_min_input = st.number_input("Monto simulación (Bs)", value=float(ad_config.get("volumen_minimo", 50000.0)), step=10000.0, key=f"vol_{ad_no}")
                            intervalo = st.number_input("Frecuencia (Seg)", value=int(ad_config.get("intervalo_segundos", 5)), step=1, key=f"int_{ad_no}")
                            posicion_objetivo = st.number_input("Posición en tabla", min_value=1, max_value=50, value=int(ad_config.get("posicion_objetivo", 1)), step=1, key=f"pos_{ad_no}")
                            tope_salto = st.number_input("Freno (Tope salto)", value=float(ad_config.get("tope_salto", 0.500)), format="%.3f", step=0.100, key=f"tope_{ad_no}")
                        with c2:
                            precio_max = st.number_input("Freno TECHO", value=float(ad_config.get("precio_maximo", 999.0)), format="%.3f", key=f"pmax_{ad_no}")
                            precio_min = st.number_input("Freno SUELO", value=float(ad_config.get("precio_minimo", 0.0)), format="%.3f", key=f"pmin_{ad_no}")
                            opciones_bancos = ["Todos", "Banesco", "Provincial", "Mercantil", "PagoMovil"]
                            banco_idx = opciones_bancos.index(ad_config["pay_types"][0]) if ad_config.get("pay_types") and ad_config["pay_types"][0] in opciones_bancos else 0
                            banco_filtro = st.selectbox("Competir contra banco", opciones_bancos, index=banco_idx, key=f"banco_{ad_no}")
                            margen = st.number_input("Margen mejora", value=float(ad_config.get("margen_victoria", 0.001)), format="%.3f", step=0.001, key=f"marg_{ad_no}")

                        if st.form_submit_button("Guardar Estrategia", type="primary", use_container_width=True):
                            pay_types_array = [] if banco_filtro == "Todos" else [banco_filtro]
                            if "estrategias_sniper" not in estado_global: estado_global["estrategias_sniper"] = {}
                            estado_global["estrategias_sniper"][ad_no] = {
                                "activo": pricer_activo, "ad_number": ad_no, "trade_type": "BUY" if trade_type == "BUY" else "SELL", 
                                "precio_actual": float(price), "volumen_minimo": vol_min_input, "precio_maximo": precio_max, "precio_minimo": precio_min,
                                "intervalo_segundos": intervalo, "pay_types": pay_types_array, "posicion_objetivo": posicion_objetivo,
                                "margen_victoria": margen, "tope_salto": tope_salto, "cantidad_usdt": "MAX"
                            }
                            guardar_estado(estado_global)
                            
                            with st.spinner("Aplicando cambio en Binance..."):
                                try:
                                    from actions.auto_pricer import ejecutar_ajuste_mercado
                                    temp_config = estado_global["estrategias_sniper"][ad_no].copy()
                                    temp_config["mi_nickname"] = mi_nickname_global
                                    temp_config["activo"] = True
                                    asyncio.run(ejecutar_ajuste_mercado(temp_config, estado_global))
                                except Exception as e: pass
                                
                            st.session_state.posiciones_mercado.pop(ad_no, None)
                            st.toast("✅ ¡Estrategia Guardada e Inyectada!"); st.rerun()

# ==========================================
# 💸 PESTAÑA: FONDEO MATRIZ
# ==========================================
with tab_fondeo:
    st.markdown("### 🏦 Fondeo Matriz (Recarga de Operativos)")
    if not cuentas_matrices: st.warning("No tienes ninguna cuenta registrada como 'Matriz'. Ve a Config.")
    elif not cuentas_directorio_fondeo: st.warning("No tienes cuentas de destino agregadas en el Directorio.")
    else:
        with st.container(border=True):
            cuenta_origen = st.selectbox("El dinero saldrá desde la cuenta de:", cuentas_matrices)
            saldo_matriz = float(estado_global.get("saldos", {}).get(cuenta_origen, 0.0))
            st.markdown(f"<span class='badge-matriz'>Saldo Matriz Estimado: Bs. {saldo_matriz:,.2f}</span>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("#### Seleccionar Destinos y Montos")
            
            # 🔥 CALCULADORA DE REPARTO AUTOMÁTICO 🔥
            c_rep1, c_rep2 = st.columns([1.5, 1])
            capital_a_repartir = c_rep1.number_input("⚡ Capital Total a Repartir (Bs):", min_value=0.0, step=100.0, help="Escribe el total y ve marcando las cuentas. El panel hará la división.")
            
            # Contamos cuántas casillas están marcadas leyendo la memoria en vivo del panel
            cuentas_marcadas = sum(1 for alias in cuentas_directorio_fondeo.keys() if st.session_state.get(f"chk_{alias}", False))
            
            monto_dividido = ""
            if capital_a_repartir > 0 and cuentas_marcadas > 0:
                # Calculamos y redondeamos a 2 decimales para los bancos
                monto_dividido = str(round(capital_a_repartir / cuentas_marcadas, 2))
                c_rep2.markdown(f"<div style='text-align:center; padding-top:28px; color:#10b981; font-weight:bold; font-size:1.1rem;'>= {monto_dividido} Bs c/u</div>", unsafe_allow_html=True)
            
            st.markdown("<hr style='margin: 10px 0; border-color: #1e293b;'>", unsafe_allow_html=True)
            
            destinos_seleccionados = {}
            for alias_cuenta, datos_cuenta in cuentas_directorio_fondeo.items():
                col1, col2 = st.columns([1, 1.5])
                activar = col1.checkbox(f"**{alias_cuenta}**", key=f"chk_{alias_cuenta}")
                if activar:
                    monto = col2.text_input("Monto a enviar (Bs):", value=monto_dividido, key=f"mnt_{alias_cuenta}_{monto_dividido}")
                    if monto: destinos_seleccionados[alias_cuenta] = {"monto": monto, "cuenta": datos_cuenta["cuenta"], "cedula": datos_cuenta["cedula"], "tipo_doc": datos_cuenta["tipo_doc"]}
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            if len(estado_global.get("cola_fondeo", [])) > 0:
                st.warning("⏳ Hay una operación de fondeo ejecutándose.")
                if st.button("🚨 FORZAR DETENCIÓN INMEDIATA", type="primary", use_container_width=True):
                    open("data/freno_fondeo.flag", "w").close() 
                    estado_global["cola_fondeo"] = []
                    estado_global["detener_fondeo"] = False
                    guardar_estado(estado_global)
                    st.rerun()
            else:
                if st.button("🚀 Ejecutar Fondeo Múltiple", type="primary", use_container_width=True):
                    if not destinos_seleccionados: st.error("❌ Selecciona destino y monto.")
                    else:
                        try:
                            if os.path.exists("data/freno_fondeo.flag"):
                                os.remove("data/freno_fondeo.flag")
                        except: pass
                        
                        estado_global["cola_fondeo"].append({"id_fondeo": f"FND-{int(time.time())}", "cuenta_origen": cuenta_origen, "destinos": destinos_seleccionados})
                        guardar_estado(estado_global)
                        st.toast("✅ Orden de fondeo enviada.")
                        st.rerun()

# ==========================================
# ⚙️ PESTAÑA: CONFIGURACIÓN
# ==========================================
with tab_config:
    st.markdown("### ⚙️ Control total del sistema y credenciales")
    sub_api, sub_anuncios, sub_bancos = st.tabs(["🔑 Configuración General", "📈 Identidad Sniper", "💳 Métodos de Pago"])
    
    with sub_api:
        def status_lbl(n, k): return f"{n} ✅" if estado_global["credenciales"].get(k) else n
        with st.form("form_credenciales", clear_on_submit=False):
            with st.container(border=True):
                st.markdown("#### 🌐 Entorno y Capital")
                col_env1, col_env2 = st.columns(2)
                with col_env1: dinero_durmiendo = st.number_input("Dinero Durmiendo (Bs. intocables)", value=float(estado_global.get("config", {}).get("dinero_durmiendo", 100000.0)), step=10000.0)
                with col_env2:
                    proxy_server = st.text_input("Servidor Proxy IP:PORT", value=estado_global.get("config", {}).get("proxy_server", ""))
                    col_px_u, col_px_p = st.columns(2)
                    proxy_user = col_px_u.text_input("Usuario Proxy", value=estado_global.get("config", {}).get("proxy_username", ""))
                    proxy_pass = col_px_p.text_input("Clave Proxy", value=estado_global.get("config", {}).get("proxy_password", ""), type="password")
            with st.container(border=True):
                st.markdown("#### 🔑 Credenciales")
                c1, c2 = st.columns(2)
                with c1: api_key = st.text_input(status_lbl("Binance API Key", "binance_api_key"), type="password"); api_secret = st.text_input(status_lbl("Binance API Secret", "binance_api_secret"), type="password")
                with c2: cookie = st.text_input(status_lbl("BINANCE_COOKIE", "binance_cookie"), type="password"); csrf = st.text_input(status_lbl("BINANCE_CSRF", "binance_csrf"), type="password")
            with st.container(border=True):
                c1, c2 = st.columns(2)
                with c1: tg_token = st.text_input(status_lbl("Telegram Token", "telegram_bot_token"), type="password")
                with c2: chat_exitos = st.text_input("Chat Éxitos", value=estado_global["credenciales"].get("telegram_chat_id_exitos", "")); chat_reportes = st.text_input("Chat Errores", value=estado_global["credenciales"].get("telegram_chat_id_errores", ""))
            if st.form_submit_button("💾 Guardar Configuración", type="primary", use_container_width=True):
                if "config" not in estado_global: estado_global["config"] = {}
                estado_global["config"]["dinero_durmiendo"] = dinero_durmiendo; estado_global["config"]["proxy_server"] = proxy_server; estado_global["config"]["proxy_username"] = proxy_user; estado_global["config"]["proxy_password"] = proxy_pass
                if api_key: estado_global["credenciales"]["binance_api_key"] = api_key
                if api_secret: estado_global["credenciales"]["binance_api_secret"] = api_secret
                if cookie: estado_global["credenciales"]["binance_cookie"] = cookie
                if csrf: estado_global["credenciales"]["binance_csrf"] = csrf
                if tg_token: estado_global["credenciales"]["telegram_bot_token"] = tg_token
                estado_global["credenciales"]["telegram_chat_id_exitos"] = chat_exitos; estado_global["credenciales"]["telegram_chat_id_errores"] = chat_reportes
                guardar_estado(estado_global); st.toast("✅ Configuración guardada."); st.rerun()

        with st.expander("🔐 Personalizar Bot (Nombre y Accesos)", expanded=False):
            st.caption("Puedes cambiar solo el nombre y dejar los accesos en blanco para no alterarlos.")
            with st.form("form_cambio_login", clear_on_submit=False):
                nuevo_nombre = st.text_input("Nombre del Bot (Ej. MiEmpresa P2P)", value=estado_global.get("config", {}).get("nombre_bot", "PANKIPAY"))
                c_usr, c_pwd = st.columns(2)
                nuevo_user = c_usr.text_input("Nuevo Usuario (Opcional)", placeholder="Deja vacío para no cambiarlo")
                nuevo_pass = c_pwd.text_input("Nueva Contraseña (Opcional)", type="password", placeholder="Deja vacío para no cambiarla")
                
                if st.form_submit_button("Actualizar Personalización", type="primary"):
                    if not nuevo_nombre.strip():
                        st.error("⚠️ El nombre del bot no puede estar vacío.")
                    else:
                        if "config" not in estado_global: estado_global["config"] = {}
                        estado_global["config"]["nombre_bot"] = nuevo_nombre.strip().upper()
                        if nuevo_user.strip(): estado_global["config"]["login_user"] = nuevo_user.strip()
                        if nuevo_pass.strip(): estado_global["config"]["login_pass"] = nuevo_pass.strip()
                        guardar_estado(estado_global)
                        st.success("✅ ¡Actualizado! Recarga la página para ver los cambios.")

    with sub_anuncios:
        with st.form("form_nickname"):
            mi_nickname = st.text_input("Tu Nickname en Binance (Exacto)", value=estado_global.get("config", {}).get("mi_nickname", ""))
            if st.form_submit_button("💾 Guardar Nickname", type="primary"):
                if "config" not in estado_global: estado_global["config"] = {}
                estado_global["config"]["mi_nickname"] = mi_nickname.strip(); guardar_estado(estado_global); st.toast("✅ Nickname guardado."); st.rerun()

    with sub_bancos:
        with st.expander("➕ Añadir nueva cuenta Bancaria", expanded=False):
            with st.form("form_banesco", clear_on_submit=True):
                tipo_cuenta = st.radio("Rol de la cuenta:", ["Operadora", "Matriz"], horizontal=True)
                banco_sel = st.selectbox("Institución Bancaria:", ["Banesco", "Mercantil", "BDV (Venezuela)"])
                nuevo_nombre = st.text_input("Alias identificador (Ej. Pedro Banesco)")
                c1, c2 = st.columns(2); usuario_banco = c1.text_input("Usuario del Banco"); clave_banco = c2.text_input("Clave del Banco", type="password")
                c1, c2 = st.columns(2); correo_banco = c1.text_input("Correo Gmail"); clave_correo = c2.text_input("Clave de App Gmail", type="password")
                
                st.markdown("<span style='font-size:0.8rem; color:#94a3b8;'>Preguntas de Seguridad / Coordenadas (Obligatorio para Banesco)</span>", unsafe_allow_html=True)
                q1, r1 = st.columns(2); k1 = q1.text_input("Pregunta 1"); v1 = r1.text_input("Respuesta 1")
                q2, r2 = st.columns(2); k2 = q2.text_input("Pregunta 2"); v2 = r2.text_input("Respuesta 2")
                q3, r3 = st.columns(2); k3 = q3.text_input("Pregunta 3"); v3 = r3.text_input("Respuesta 3")
                q4, r4 = st.columns(2); k4 = q4.text_input("Pregunta 4"); v4 = r4.text_input("Respuesta 4")
                
                if st.form_submit_button("➕ Registrar", type="primary"):
                    if nuevo_nombre and usuario_banco and correo_banco and clave_correo:
                        estado_global["cuentas"][nuevo_nombre] = False
                        estado_global["limites"][nuevo_nombre] = {
                            "TRANSFERENCIA": {"activo": True, "min": "0", "max": "9999999"},
                            "PAGO_MOVIL": {"activo": False, "min": "0", "max": "50000"}
                        }
                        banco_clean = "BDV" if "BDV" in banco_sel else banco_sel
                        estado_global["bancos"][nuevo_nombre] = { 
                            "banco": banco_clean, 
                            "tipo": "Matriz" if "Matriz" in tipo_cuenta else "Operadora", 
                            "usuario": usuario_banco, 
                            "clave": clave_banco, 
                            "correo": correo_banco, 
                            "clave_correo": clave_correo, 
                            "preguntas": {k1.lower(): v1, k2.lower(): v2, k3.lower(): v3, k4.lower(): v4} 
                        }
                        guardar_estado(estado_global); st.toast("✅ Cuenta registrada y sincronizada."); st.rerun()
                    else:
                        st.error("Faltan datos obligatorios (Alias, Usuario, Correo, Clave App).")
        
        with st.expander("🗑️ Eliminar cuenta", expanded=False):
            if cuentas_totales:
                c_del = st.selectbox("Cuenta a eliminar:", ["Seleccionar..."] + cuentas_totales)
                if c_del != "Seleccionar..." and st.button("🗑️ Confirmar Eliminación", type="primary"):
                    estado_global.get("cuentas", {}).pop(c_del, None)
                    estado_global.get("limites", {}).pop(c_del, None)
                    estado_global.get("bancos", {}).pop(c_del, None)
                    estado_global.get("saldos", {}).pop(c_del, None)
                    guardar_estado(estado_global)
                    st.rerun()

        with st.expander("✏️ Editar credenciales de cuenta Bancaria", expanded=False):
            if not cuentas_totales:
                st.warning("No hay cuentas registradas en el sistema para editar.")
            else:
                cuenta_a_editar = st.selectbox("Selecciona la cuenta que deseas modificar:", ["Seleccionar..."] + cuentas_totales)

                if cuenta_a_editar != "Seleccionar...":
                    cuenta_data = estado_global.get("bancos", {}).get(cuenta_a_editar, {})
                    
                    st.info("💡 **Instrucciones:** Solo llena los campos que deseas cambiar. **Deja en blanco** los que quieras mantener intactos. Las contraseñas están ocultas por seguridad.")

                    with st.form(key=f"form_editar_{cuenta_a_editar}"):
                        st.markdown("### 🔑 Credenciales de Acceso al Banco")
                        
                        usuario_actual = cuenta_data.get("usuario", "")
                        nuevo_usuario = st.text_input("Usuario / Login", placeholder=f"Actual: {usuario_actual}")
                        nueva_clave = st.text_input("Nueva Contraseña del Banco", type="password", placeholder="Escribe aquí solo si deseas cambiar la contraseña...")

                        st.markdown("### 🔐 Seguridad y OTP (Correo / Preguntas)")
                        
                        correo_actual = cuenta_data.get("correo", "")
                        nuevo_correo = st.text_input("Correo Gmail", placeholder=f"Actual: {correo_actual}")
                        nueva_clave_correo = st.text_input("Nueva Clave de App Gmail", type="password", placeholder="Escribe para cambiar la clave del correo...")

                        preguntas_actuales = cuenta_data.get("preguntas", {})
                        nuevas_respuestas = {}
                        
                        if preguntas_actuales:
                            st.markdown("**Respuestas de Seguridad:**")
                            for pregunta in preguntas_actuales.keys():
                                ans = st.text_input(f"Nueva respuesta para: {pregunta.capitalize()}", type="password", placeholder="***")
                                nuevas_respuestas[pregunta] = ans

                        submit_edicion = st.form_submit_button("💾 Guardar Cambios", type="primary")

                        if submit_edicion:
                            modificado = False

                            if nuevo_usuario.strip():
                                cuenta_data["usuario"] = nuevo_usuario.strip()
                                modificado = True
                            
                            if nueva_clave.strip():
                                cuenta_data["clave"] = nueva_clave.strip()
                                modificado = True

                            if nuevo_correo.strip():
                                cuenta_data["correo"] = nuevo_correo.strip()
                                modificado = True
                                
                            if nueva_clave_correo.strip():
                                cuenta_data["clave_correo"] = nueva_clave_correo.strip()
                                modificado = True

                            for preg, resp in nuevas_respuestas.items():
                                if resp.strip():
                                    cuenta_data["preguntas"][preg] = resp.strip()
                                    modificado = True

                            if modificado:
                                estado_global["bancos"][cuenta_a_editar] = cuenta_data
                                guardar_estado(estado_global)
                                st.toast(f"✅ ¡Credenciales de {cuenta_a_editar} actualizadas!")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.warning("No escribiste ningún dato nuevo. La cuenta quedó intacta.")

        with st.expander("🎯 Directorio de Fondeo", expanded=False):
            with st.form("form_fondeo_dir", clear_on_submit=True):
                alias_fondeo = st.text_input("Alias"); cuenta_20 = st.text_input("Cuenta Banesco (20 dígitos)", max_chars=20)
                c1, c2 = st.columns([1, 3]); tipo_documento = c1.selectbox("Tipo", ["V", "E", "J", "G", "P"]); numero_documento = c2.text_input("Cédula / RIF")
                if st.form_submit_button("💾 Guardar Destino", type="primary"):
                    if alias_fondeo and len(cuenta_20) == 20:
                        estado_global["cuentas_fondeo"][alias_fondeo] = { "banco": "Banesco", "cuenta": cuenta_20, "tipo_doc": tipo_documento, "cedula": numero_documento }
                        guardar_estado(estado_global); st.toast("✅ Destino guardado."); st.rerun()
            for alias_dir, datos_dir in cuentas_directorio_fondeo.items():
                c1, c2 = st.columns([4, 1])
                c1.markdown(f"**{alias_dir}** - `{datos_dir['cuenta']}`")
                if c2.button("Eliminar", key=f"del_dir_{alias_dir}"): del estado_global["cuentas_fondeo"][alias_dir]; guardar_estado(estado_global); st.rerun()

# ==========================================
# 📊 PESTAÑA: CONTABILIDAD 
# ==========================================
with tab_conta:
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
