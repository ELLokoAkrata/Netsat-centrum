"""
app.py - Netsat Centrum
App unificada para gestión de documentos NETSAT SRL.
Deploy: Streamlit Community Cloud
Secrets requeridos: SUPABASE_URL, SUPABASE_KEY, APP_PASSWORD
"""
import streamlit as st
import pandas as pd
import io
import zipfile
from supabase import create_client, Client

st.set_page_config(
    page_title="Netsat Centrum",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
@st.cache_resource
def get_supabase() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def require_login():
    if st.session_state.get("auth"):
        return
    _, col, _ = st.columns([1, 1, 1])
    with col:
        st.markdown("## Netsat Centrum")
        st.caption("Sistema de gestión de documentos NETSAT SRL")
        st.divider()
        pwd = st.text_input("Contraseña", type="password")
        if st.button("Ingresar", width="stretch"):
            if pwd == st.secrets.get("APP_PASSWORD", ""):
                st.session_state.auth = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta")
    st.stop()

require_login()

supabase: Client = get_supabase()

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
col_titulo, col_logout = st.columns([6, 1])
with col_titulo:
    st.title("Netsat Centrum")
with col_logout:
    st.write("")
    if st.button("Cerrar sesión", width="stretch"):
        st.session_state.clear()
        st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# Helper: descarga en dos pasos (evita problemas de rerender en Streamlit)
# ---------------------------------------------------------------------------
def boton_descarga(bucket: str, path: str, nombre: str, uid: str):
    k = f"bytes_{uid}"
    if k in st.session_state:
        def _limpiar():
            st.session_state.pop(k, None)
        st.download_button(
            label="Guardar archivo",
            data=st.session_state[k],
            file_name=nombre,
            mime="application/pdf",
            key=f"dl_{uid}",
            on_click=_limpiar,
            width="stretch",
        )
    else:
        if st.button("Descargar", key=f"fetch_{uid}", width="stretch"):
            with st.spinner("Preparando..."):
                st.session_state[k] = supabase.storage.from_(bucket).download(path)
            st.rerun()

# ---------------------------------------------------------------------------
# Tabs principales
# ---------------------------------------------------------------------------
tab_doc, tab_guias, tab_ocs, tab_facturas, tab_nelida = st.tabs([
    "Documentación",
    "Guías",
    "OCs",
    "Facturas",
    "Control Nélida",
])

# ============================================================
# TAB 1: Documentacion
# ============================================================
with tab_doc:
    st.header("Cómo usar Netsat Centrum")
    st.markdown("""
    **Netsat Centrum** centraliza los documentos operativos de NETSAT SRL en una sola
    plataforma accesible desde cualquier dispositivo con internet.

    ---

    ### Pestañas disponibles

    | Pestaña | Qué contiene |
    |---------|-------------|
    | **Guías** | Guías de remisión selladas y digitales — descargables por mes y tipo |
    | **OCs** | Órdenes de compra internas con precios y cantidades |
    | **Facturas** | Facturas emitidas con montos, estado de pago y referencias |
    | **Control Nélida** | Proyectos 2026 y estado COUPA de Antapaccay |

    ---

    ### Cómo descargar un archivo

    1. Ve a la pestaña **Guías**
    2. Usa los filtros para encontrar la guía (por mes, tipo o número)
    3. Haz clic en **Descargar** — el sistema prepara el archivo
    4. Cuando aparezca **Guardar archivo**, haz clic para guardarlo en tu equipo

    > El proceso tiene dos pasos para garantizar que la descarga siempre funcione.

    ---

    ### Usuarios del sistema

    | Usuario | Equipo | Rol |
    |---------|--------|-----|
    | Ricardo Junior | Laptop / RDP | Desarrollo y administración |
    | Héctor | PC-Netsat | Sube guías y documentos |
    | Ricardo (padre) | Laptop | Consulta y descarga |
    | Nélida | PC propia | Control de facturas |
    """)

# ============================================================
# TAB 2: Guias
# ============================================================
with tab_guias:
    st.header("Guías de Remisión 2026")

    @st.cache_data(ttl=300)
    def cargar_archivos():
        r = supabase.table("archivos").select("*").order("nombre").execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()

    @st.cache_data(ttl=300)
    def cargar_guias_db():
        r = supabase.table("guias").select(
            "numero, fecha_emision, oc, estatus, mes"
        ).order("numero", desc=True).execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()

    if st.button("Recargar datos", key="reload_guias"):
        cargar_archivos.clear()
        cargar_guias_db.clear()
        st.rerun()

    df_arch = cargar_archivos()

    if df_arch.empty:
        st.info("No hay archivos cargados aún.")
    else:
        # Filtros
        col1, col2, col3 = st.columns(3)
        meses_disp = sorted(df_arch["mes"].dropna().unique().tolist())
        with col1:
            f_mes = st.selectbox("Mes", meses_disp, index=len(meses_disp) - 1, key="g_mes")
        with col2:
            f_tipo = st.selectbox("Tipo", ["Todos", "Sellada", "Digital"], key="g_tipo")
        with col3:
            f_buscar = st.text_input("Buscar (número guía o nombre)", key="g_buscar")

        df_f = df_arch[df_arch["mes"] == f_mes].copy()
        if f_tipo == "Sellada":
            df_f = df_f[df_f["bucket"].str.contains("selladas", na=False)]
        elif f_tipo == "Digital":
            df_f = df_f[df_f["bucket"].str.contains("digitales", na=False)]
        if f_buscar:
            mask = (
                df_f["nombre"].str.contains(f_buscar, case=False, na=False) |
                df_f["guia_numero"].fillna("").str.contains(f_buscar, case=False)
            )
            df_f = df_f[mask]

        st.caption(f"{len(df_f)} archivos")

        # ── Descarga ZIP (acción principal) ──────────────────────
        zip_key = f"zip_{f_mes}_{f_tipo}"
        bc1, bc2 = st.columns([1, 1])
        with bc1:
            if zip_key in st.session_state:
                def _limpiar_zip():
                    st.session_state.pop(zip_key, None)
                st.download_button(
                    label="💾 Guardar ZIP",
                    data=st.session_state[zip_key],
                    file_name=f"Guias_{f_mes.replace(' ', '_')}_{f_tipo}.zip",
                    mime="application/zip",
                    key=f"dl_{zip_key}",
                    on_click=_limpiar_zip,
                    use_container_width=True,
                )
            else:
                if st.button("📦 Descargar mes como ZIP", key=f"fetch_{zip_key}", use_container_width=True, disabled=df_f.empty):
                    buf = io.BytesIO()
                    with st.spinner(f"Preparando {len(df_f)} archivos..."):
                        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                            for _, row in df_f.iterrows():
                                try:
                                    data = supabase.storage.from_(row["bucket"]).download(row["storage_path"])
                                    zf.writestr(row["nombre"], data)
                                except Exception:
                                    pass
                    buf.seek(0)
                    st.session_state[zip_key] = buf.read()
                    st.rerun()

        # ── Archivos individuales (colapsado) ────────────────────
        with st.expander(f"Ver archivos individuales ({len(df_f)})"):
            h1, h2, h3, h4 = st.columns([4, 1, 1, 1])
            h1.markdown("**Archivo**")
            h2.markdown("**Mes**")
            h3.markdown("**Tipo**")
            h4.markdown("**Acción**")
            st.divider()

            for _, row in df_f.iterrows():
                uid = str(row["id"])
                tipo_label = "Sellada" if "selladas" in str(row.get("bucket", "")) else "Digital"
                guia = row.get("guia_numero") or ""

                c1, c2, c3, c4 = st.columns([4, 1, 1, 1])
                with c1:
                    st.write(f"**{guia}** {row['nombre']}" if guia else row["nombre"])
                with c2:
                    st.write(row.get("mes") or "")
                with c3:
                    st.write(tipo_label)
                with c4:
                    boton_descarga(row["bucket"], row["storage_path"], row["nombre"], uid)

        # Tabla de datos de guias
        df_guias = cargar_guias_db()
        if not df_guias.empty:
            st.divider()
            st.subheader("Datos de guías (control Nélida)")
            col1, col2 = st.columns(2)
            with col1:
                f_est = st.selectbox("Estatus", ["Todos", "COMPLETO", "INCOMPLETO"], key="g_est")
            with col2:
                meses_g = ["Todos"] + sorted(df_guias["mes"].dropna().unique().tolist())
                f_mes2 = st.selectbox("Mes", meses_g, key="g_mes2")

            df_g = df_guias.copy()
            if f_est != "Todos":
                df_g = df_g[df_g["estatus"] == f_est]
            if f_mes2 != "Todos":
                df_g = df_g[df_g["mes"] == f_mes2]

            st.dataframe(df_g, width='stretch', hide_index=True)

# ============================================================
# TAB 3: OCs
# ============================================================
with tab_ocs:
    st.header("Órdenes de Compra")

    @st.cache_data(ttl=300)
    def cargar_ocs():
        r = supabase.table("ocs").select("*").order("codigo_oc").execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()

    if st.button("Recargar datos", key="reload_ocs"):
        cargar_ocs.clear()
        st.rerun()

    df_ocs = cargar_ocs()

    if df_ocs.empty:
        st.info("No hay OCs cargadas aún.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            f_oc = st.text_input("Buscar código OC", key="oc_cod")
        with col2:
            f_desc = st.text_input("Buscar descripción", key="oc_desc")

        df_f = df_ocs.copy()
        if f_oc:
            df_f = df_f[df_f["codigo_oc"].str.contains(f_oc, case=False, na=False)]
        if f_desc:
            df_f = df_f[df_f["descripcion"].fillna("").str.contains(f_desc, case=False)]

        cols = [c for c in [
            "codigo_oc", "item", "descripcion", "cantidad",
            "venta_unit_usd", "venta_total_usd", "observaciones"
        ] if c in df_f.columns]

        st.caption(f"{len(df_f)} items")
        st.dataframe(df_f[cols], width='stretch', hide_index=True)

# ============================================================
# TAB 4: Facturas
# ============================================================
with tab_facturas:
    st.header("Facturas Emitidas")

    @st.cache_data(ttl=300)
    def cargar_facturas():
        r = supabase.table("facturas").select("*").order("numero", desc=True).execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()

    if st.button("Recargar datos", key="reload_facturas"):
        cargar_facturas.clear()
        st.rerun()

    df_fact = cargar_facturas()

    if df_fact.empty:
        st.info("No hay facturas cargadas aún.")
    else:
        # Metricas
        pagadas = 0
        total_usd = 0.0
        if "pagado" in df_fact.columns:
            pagadas = df_fact[df_fact["pagado"].fillna("").str.upper() == "SI"].shape[0]
        if "total_dolar" in df_fact.columns:
            total_usd = pd.to_numeric(df_fact["total_dolar"], errors="coerce").sum()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total facturas", len(df_fact))
        col2.metric("Pagadas", pagadas)
        col3.metric("Pendientes", len(df_fact) - pagadas)
        col4.metric("Total facturado (USD)", f"$ {total_usd:,.2f}")

        st.divider()

        # Filtros
        col1, col2, col3 = st.columns(3)
        with col1:
            f_num = st.text_input("Número factura", key="f_num")
        with col2:
            f_pag = st.selectbox("Estado de pago", ["Todos", "SI", "NO"], key="f_pag")
        with col3:
            f_oc = st.text_input("Orden de compra", key="f_oc_fac")

        df_f = df_fact.copy()
        if f_num:
            df_f = df_f[df_f["numero"].str.contains(f_num, case=False, na=False)]
        if f_pag != "Todos" and "pagado" in df_f.columns:
            df_f = df_f[df_f["pagado"].fillna("").str.upper() == f_pag]
        if f_oc and "orden_de_compra" in df_f.columns:
            df_f = df_f[df_f["orden_de_compra"].fillna("").str.contains(f_oc, case=False)]

        cols = [c for c in [
            "numero", "fecha_emision", "cliente", "total_soles", "total_dolar",
            "pagado", "guia_remision", "orden_de_compra"
        ] if c in df_f.columns]

        st.caption(f"{len(df_f)} facturas")
        st.dataframe(df_f[cols], width='stretch', hide_index=True)

# ============================================================
# TAB 5: Control Nelida
# ============================================================
with tab_nelida:
    st.header("Control Nélida")

    @st.cache_data(ttl=300)
    def cargar_proyectos():
        r = supabase.table("proyectos").select("*").execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()

    @st.cache_data(ttl=300)
    def cargar_coupa():
        r = supabase.table("coupa").select("*").execute()
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()

    if st.button("Recargar datos", key="reload_nelida"):
        cargar_proyectos.clear()
        cargar_coupa.clear()
        st.rerun()

    sub_proy, sub_coupa = st.tabs(["Proyectos 2026", "Estado COUPA"])

    with sub_proy:
        df_proy = cargar_proyectos()
        if df_proy.empty:
            st.info("No hay proyectos cargados aún.")
        else:
            f_oc = st.text_input("Buscar OC", key="n_oc")
            df_f = df_proy.copy()
            if f_oc and "codigo_oc" in df_f.columns:
                df_f = df_f[df_f["codigo_oc"].fillna("").str.contains(f_oc, case=False)]
            cols = [c for c in [
                "codigo_oc", "factura_venta", "guia", "factura_compra", "estado", "observaciones"
            ] if c in df_f.columns]
            st.caption(f"{len(df_f)} proyectos")
            st.dataframe(df_f[cols] if cols else df_f, width='stretch', hide_index=True)

    with sub_coupa:
        df_coupa = cargar_coupa()
        if df_coupa.empty:
            st.info("No hay datos COUPA cargados aún.")
        else:
            cols = [c for c in [
                "numero_factura", "fecha", "monto", "moneda", "estado_pago", "codigo_oc"
            ] if c in df_coupa.columns]
            st.caption(f"{len(df_coupa)} registros")
            st.dataframe(df_coupa[cols] if cols else df_coupa, width='stretch', hide_index=True)
