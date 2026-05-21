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
tab_doc, tab_guias, tab_ocs, tab_despacho, tab_facturas, tab_nelida = st.tabs([
    "Documentación",
    "Guías",
    "OCs",
    "Despacho",
    "Facturas",
    "Control Nélida",
])

@st.cache_data(ttl=300)
def cargar_ocs_items():
    r = (supabase.table("ocs")
         .select("*")
         .order("codigo_oc")
         .order("item")
         .execute())
    return pd.DataFrame(r.data) if r.data else pd.DataFrame()

@st.cache_data(ttl=300)
def cargar_despacho():
    r = (supabase.table("ocs_despacho_v")
         .select("*")
         .order("mes")
         .order("codigo_oc")
         .execute())
    return pd.DataFrame(r.data) if r.data else pd.DataFrame()

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
    | **Guías** | Guías de remisión selladas y digitales — descargables por mes y tipo o como ZIP |
    | **OCs** | PDFs de órdenes de compra Antapaccay — descarga individual o ZIP por mes |
    | **Despacho** | Estado de cada OC (pendiente / despachado) con guías vinculadas e ítems por entregar |
    | **Facturas** | Facturas emitidas con montos, estado de pago y referencias |
    | **Control Nélida** | Proyectos 2026 y estado COUPA de Antapaccay |

    ---

    ### Cómo descargar un archivo

    1. Ve a la pestaña **Guías** u **OCs**
    2. Selecciona el mes que necesitas
    3. Haz clic en **Descargar mes como ZIP** para bajar todo el mes de una vez,
       o expande la lista para descargar archivos individuales
    4. Cuando aparezca **Guardar archivo** o **Guardar ZIP**, haz clic para guardarlo

    > La descarga tiene dos pasos para garantizar que siempre funcione.

    ---

    ### Cómo usar la pestaña Despacho

    1. Selecciona el **mes** y el **estado** que quieres ver (por defecto muestra las pendientes)
    2. La tabla superior muestra cada OC con su estado, guías vinculadas y fechas de traslado
    3. La tabla inferior muestra todos los **ítems** de esas OCs ordenados por fecha de entrega —
       los más urgentes aparecen primero
    4. Cuando se sube una guía nueva, el estado se actualiza automáticamente

    ---

    ### Actualización de datos

    Los datos se sincronizan manualmente desde la PC-Netsat. **Nadie más necesita hacer nada** —
    el sistema se actualiza solo cuando Ricky corre la sincronización.

    | Quién | Qué hace | Qué pasa automáticamente |
    |-------|----------|--------------------------|
    | **Héctor** | Sube PDFs de guías a la carpeta de red | Ricky sincroniza y aparecen en Guías y Despacho |
    | **Nélida** | Actualiza su Excel de facturas | Ricky sincroniza y aparecen en Facturas y Control Nélida |
    | **Ricardo (padre)** | Envía PDFs de OCs nuevas | Ricky los sube y aparecen en OCs y Despacho |
    | **Ricky** | Corre la sincronización | Todo lo demás se actualiza solo |

    ---

    ### Usuarios del sistema

    | Usuario | Rol |
    |---------|-----|
    | **Ricky** | Desarrollo, sincronización y administración |
    | **Héctor** | Sube guías al servidor — no necesita hacer nada más |
    | **Ricardo (padre)** | Consulta OCs y estado de despacho |
    | **Nélida** | Mantiene su Excel — los datos llegan solos a la app |
    """)

# ============================================================
# TAB 2: Guias
# ============================================================
with tab_guias:
    st.header("Guías de Remisión 2026")

    @st.cache_data(ttl=300)
    def cargar_archivos():
        r = supabase.table("archivos").select("*").order("guia_numero").order("bucket").execute()
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
            f_tipo = st.selectbox("Tipo", ["Sellada", "Digital", "Todos"], key="g_tipo")
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
                df_f["guia_numero"].fillna("").str.contains(f_buscar, case=False) |
                df_f["oc_extraida"].fillna("").str.contains(f_buscar, case=False)
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
                    width="stretch",
                )
            else:
                if st.button("📦 Descargar mes como ZIP", key=f"fetch_{zip_key}", width="stretch", disabled=df_f.empty):
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
# TAB 3: OCs Antapaccay
# ============================================================
with tab_ocs:
    st.header("OCs Antapaccay 2026")

    @st.cache_data(ttl=300)
    def cargar_ocs_archivos():
        r = (supabase.table("archivos")
             .select("*")
             .eq("tipo", "OC")
             .order("nombre")
             .execute())
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()

    if st.button("Recargar datos", key="reload_ocs"):
        cargar_ocs_archivos.clear()
        cargar_ocs_items.clear()
        st.rerun()

    df_arch_oc = cargar_ocs_archivos()

    if df_arch_oc.empty:
        st.info("No hay OCs cargadas. Ejecutar sync_ocs.py.")
    else:
        # ── Filtros ──────────────────────────────────────────
        col1, col2 = st.columns([1, 2])
        with col1:
            meses_oc = sorted(df_arch_oc["mes"].dropna().unique().tolist())
            f_mes = st.selectbox("Mes", meses_oc, index=len(meses_oc) - 1, key="oc_mes")
        with col2:
            f_buscar = st.text_input("Buscar (código OC o nombre de archivo)", key="oc_buscar")

        df_f = df_arch_oc[df_arch_oc["mes"] == f_mes].copy()
        if f_buscar:
            df_f = df_f[df_f["nombre"].str.contains(f_buscar, case=False, na=False)]

        # Extraer código OC del storage_path: "ocs/antapaccay/C004248376/..."
        def _codigo_de_path(path: str) -> str:
            partes = str(path).split("/")
            return partes[2] if len(partes) >= 3 else ""

        df_f["codigo_oc"] = df_f["storage_path"].apply(_codigo_de_path)

        st.caption(f"{len(df_f)} OCs en {f_mes}")

        # ── Descarga ZIP ──────────────────────────────────────
        zip_key = f"zip_ocs_{f_mes}"
        if zip_key in st.session_state:
            def _limpiar_zip_oc():
                st.session_state.pop(zip_key, None)
            st.download_button(
                label="💾 Guardar ZIP",
                data=st.session_state[zip_key],
                file_name=f"OCs_Antapaccay_{f_mes}.zip",
                mime="application/zip",
                key=f"dl_{zip_key}",
                on_click=_limpiar_zip_oc,
                width="stretch",
            )
        else:
            if st.button("📦 Descargar mes como ZIP", key=f"fetch_{zip_key}",
                         width="stretch", disabled=df_f.empty):
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

        # ── Archivos individuales ─────────────────────────────
        with st.expander(f"Ver archivos individuales ({len(df_f)})"):
            h1, h2, h3 = st.columns([5, 2, 1])
            h1.markdown("**Archivo**")
            h2.markdown("**Código OC**")
            h3.markdown("**Acción**")
            st.divider()

            for _, row in df_f.iterrows():
                uid = str(row["id"])
                c1, c2, c3 = st.columns([5, 2, 1])
                with c1:
                    st.write(row["nombre"])
                with c2:
                    st.write(row["codigo_oc"])
                with c3:
                    boton_descarga(row["bucket"], row["storage_path"], row["nombre"], uid)

        # ── Ítems de la OC seleccionada ───────────────────────
        st.divider()
        st.subheader("Ítems de la OC")

        df_items = cargar_ocs_items()
        codigos_con_items = (df_items["codigo_oc"].unique().tolist()
                             if not df_items.empty else [])
        codigos_del_mes = sorted(df_f["codigo_oc"].tolist())

        if not codigos_del_mes:
            st.info("No hay OCs en el mes seleccionado.")
        else:
            oc_sel = st.selectbox(
                "Seleccionar OC para ver sus ítems",
                options=codigos_del_mes,
                key="oc_sel_items",
            )

            if oc_sel in codigos_con_items:
                df_det = df_items[df_items["codigo_oc"] == oc_sel]
                cols = [c for c in [
                    "item", "descripcion", "cantidad",
                    "venta_unit_usd", "venta_total_usd", "observaciones"
                ] if c in df_det.columns]
                total = pd.to_numeric(df_det["venta_total_usd"], errors="coerce").sum()
                st.caption(f"{len(df_det)} ítems · Total: ${total:,.2f} USD")
                st.dataframe(df_det[cols], width="stretch", hide_index=True)
            else:
                st.info(
                    f"La OC **{oc_sel}** no tiene ítems registrados. "
                    "Los datos de ítems provienen del Excel del padre "
                    "y están disponibles para 31 de las 96 OCs."
                )

# ============================================================
# TAB 4: Despacho
# ============================================================
with tab_despacho:
    st.header("Despacho OCs Antapaccay 2026")

    if st.button("Recargar datos", key="reload_despacho"):
        cargar_despacho.clear()
        cargar_ocs_items.clear()
        st.rerun()

    df_desp = cargar_despacho()

    if df_desp.empty:
        st.info("Sin datos en ocs_despacho_v. Verificar que la vista existe en Supabase.")
    else:
        ESTADOS = ["PENDIENTE", "DESPACHADO", "PARCIAL", "COMPLETO"]

        col1, col2 = st.columns([1, 2])
        with col1:
            meses_disp = sorted(df_desp["mes"].dropna().unique().tolist())
            f_mes_d = st.selectbox("Mes", meses_disp,
                                   index=len(meses_disp) - 1, key="desp_mes")
        with col2:
            f_estados = st.multiselect("Estado", ESTADOS,
                                       default=["PENDIENTE"], key="desp_estado")

        df_f = df_desp[df_desp["mes"] == f_mes_d].copy()
        if f_estados:
            df_f = df_f[df_f["estado_real"].isin(f_estados)]

        n_pend  = (df_f["estado_real"] == "PENDIENTE").sum()
        n_desp  = (df_f["estado_real"] == "DESPACHADO").sum()
        n_otros = (df_f["estado_real"].isin(["PARCIAL", "COMPLETO"])).sum()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Total OCs", len(df_f))
        col2.metric("Pendiente",      n_pend)
        col3.metric("Despachado",     n_desp)
        col4.metric("Parcial/Completo", n_otros)

        st.caption(f"{len(df_f)} OC(s)")

        COLS_TABLA = [c for c in [
            "codigo_oc", "fecha_oc", "monto_total_usd", "estado_real",
            "total_guias", "primer_traslado", "ultimo_traslado", "guias",
        ] if c in df_f.columns]
        st.dataframe(df_f[COLS_TABLA], hide_index=True, width="stretch")

        st.divider()
        st.subheader("Ítems de las OCs seleccionadas")

        df_items_all = cargar_ocs_items()
        codigos_filtrados = df_f["codigo_oc"].dropna().unique().tolist()

        if df_items_all.empty or not codigos_filtrados:
            st.info("No hay ítems registrados para las OCs seleccionadas.")
        else:
            df_items_f = df_items_all[df_items_all["codigo_oc"].isin(codigos_filtrados)].copy()
            if df_items_f.empty:
                st.info("Las OCs seleccionadas no tienen ítems registrados.")
            else:
                COLS_ITEMS = [c for c in [
                    "codigo_oc", "item", "descripcion", "codigo_material",
                    "cantidad", "unidad", "fecha_entrega",
                ] if c in df_items_f.columns]
                st.caption(f"{len(df_items_f)} ítem(s) en {len(codigos_filtrados)} OC(s)")
                st.dataframe(
                    df_items_f[COLS_ITEMS].sort_values(["fecha_entrega", "codigo_oc", "item"]),
                    hide_index=True, width="stretch",
                )

# ============================================================
# TAB 5: Facturas
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
