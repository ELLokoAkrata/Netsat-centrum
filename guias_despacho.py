import streamlit as st
import pandas as pd
import pdfplumber
import re
import os
import io
import zipfile
from datetime import datetime
from auth import require_login

# ─── FUENTES DE DATOS ──────────────────────────────────────────────────────────

_NELIDA_PRIMARY = r"C:\Users\herru\OneDrive\Escritorio\Drive-Compartido\CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx"
_NELIDA_BACKUP  = "CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx"

def _nelida_path():
    return _NELIDA_PRIMARY if os.path.exists(_NELIDA_PRIMARY) else _NELIDA_BACKUP

# OCs con error tipográfico confirmado en guía impresa
OC_CORRECCIONES = {
    "C003932633": "C003932631",  # T001-591
    "C004018882": "C004018872",  # T001-604
}

_RED_BASE   = r"Z:\NETSAT\NETSAT 2026\FACTURAS GUIAS NETSAT SRL 2026\GUIAS 2026"
_LOCAL_BASE = ""

def _base():
    return _RED_BASE if os.path.exists(_RED_BASE) else _LOCAL_BASE

def _guias_folders():
    base = _base()
    return [
        (os.path.join(base, "GUIAS ENERO 2026",   "GUIAS SELLADAS 2026", "GUIAS SELLADAS ENERO 26"), os.path.join(base, "GUIAS ENERO 2026")),
        (os.path.join(base, "GUIAS FEBRERO 2026",  "GUIAS SELLADAS FEBRERO 2026"),                   os.path.join(base, "GUIAS FEBRERO 2026")),
        (os.path.join(base, "GUIAS MARZO 2026",    "GUIAS SELLADAS MARZO 2026"),                     os.path.join(base, "GUIAS MARZO 2026")),
        (os.path.join(base, "GUIAS ABRIL 2026",    "GUIAS SELLADAS ABRIL 2026"),                     os.path.join(base, "GUIAS ABRIL 2026")),
    ]


# ─── CARGA ─────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=0)
def cargar_nelida_guias():
    """Hoja GUIAS del archivo de Nélida — fuente de verdad."""
    df = pd.read_excel(_nelida_path(), sheet_name="GUIAS", header=0)
    # Renombrar por posición (encoding corrupto en encabezados)
    cols = list(df.columns)
    nombres = ["Guia", "Fecha", "OC", "Estatus", "Factura", "Detalle"]
    for i, nombre in enumerate(nombres):
        if i < len(cols):
            df.rename(columns={cols[i]: nombre}, inplace=True)
    df = df[nombres].copy()
    df["Fecha"]    = pd.to_datetime(df["Fecha"], errors="coerce")
    df["OC"]       = df["OC"].astype(str).str.strip()
    df["OC"]       = df["OC"].replace(OC_CORRECCIONES)
    df["Factura"]  = df["Factura"].astype(str)
    df["Guia_num"] = df["Guia"].astype(str).str.extract(r"T001-(\d+)")[0].astype(float)
    df = df[df["Fecha"].dt.year == 2026].dropna(subset=["Guia_num"])
    return df.sort_values("Guia_num").reset_index(drop=True)


@st.cache_data(ttl=0)
def cargar_pdfs():
    """PDFs sellados en Z: — confirmación física del despacho."""
    registros = []
    for folder_selladas, folder_orig in _guias_folders():
        if not os.path.exists(folder_selladas):
            continue
        for filename in sorted(os.listdir(folder_selladas)):
            if not filename.lower().endswith(".pdf"):
                continue
            m_num = re.search(r"T001-(\d+)", filename)
            m_oc  = re.search(r"OC_(C\d+)", filename)
            if not m_num:
                continue
            num     = int(m_num.group(1))
            guia_id = f"T001-{num}"
            oc      = m_oc.group(1) if m_oc else None

            # Fecha de traslado del PDF original digital (OCR perfecto)
            fecha_str  = None
            orig_path  = os.path.join(folder_orig, f"20505504781-09-T001-{num:03d}.pdf")
            try:
                with pdfplumber.open(orig_path) as pdf:
                    texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
                m = re.search(r"Fecha del Traslado:\s*(\d{2}/\d{2}/\d{4})", texto)
                if m:
                    fecha_str = m.group(1)
            except Exception:
                pass

            registros.append({
                "Guia":           guia_id,
                "Guia_num":       num,
                "OC_pdf":         oc,
                "Fecha_Traslado": fecha_str,
                "Mes":            os.path.basename(folder_orig),
                "Archivo":        filename,
            })

    if not registros:
        return pd.DataFrame(columns=["Guia", "Guia_num", "OC_pdf", "Fecha_Traslado", "Mes", "Archivo"])

    df = pd.DataFrame(registros)
    df["Fecha_Traslado"] = pd.to_datetime(df["Fecha_Traslado"], format="%d/%m/%Y", errors="coerce")
    return df.sort_values("Guia_num").reset_index(drop=True)


def zip_guias_mes(mes_folder_orig: str, mes_folder_selladas: str) -> bytes | None:
    """Empaqueta todos los PDFs sellados de un mes en un ZIP en memoria."""
    if not os.path.exists(mes_folder_selladas):
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename in sorted(os.listdir(mes_folder_selladas)):
            if filename.lower().endswith(".pdf"):
                zf.write(os.path.join(mes_folder_selladas, filename), filename)
    buf.seek(0)
    data = buf.read()
    return data if data else None


def cruzar(nelida, pdfs):
    """Une guías de Nélida con PDFs sellados por número de guía."""
    pdf_map = pdfs.set_index("Guia_num")[["Fecha_Traslado", "Mes", "Archivo"]].to_dict("index") if not pdfs.empty else {}

    def _pdf_info(num):
        info = pdf_map.get(num)
        if not info:
            return pd.Series({"PDF_Sellado": "❌", "Fecha_Traslado": pd.NaT, "Mes": "", "Archivo": ""})
        return pd.Series({
            "PDF_Sellado":    "✅",
            "Fecha_Traslado": info["Fecha_Traslado"],
            "Mes":            info["Mes"],
            "Archivo":        info["Archivo"],
        })

    extra = nelida["Guia_num"].apply(_pdf_info)
    return pd.concat([nelida, extra], axis=1)


# ─── UI ────────────────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Guías de despacho — NETSAT",
    layout="wide",
    page_icon="🚚",
)

require_login()

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; }
[data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

col_title, col_reload = st.columns([5, 1])
with col_title:
    st.title("🚚 Guías de despacho — Antapaccay 2026")
with col_reload:
    st.write("")
    if st.button("🔄 Recargar datos", use_container_width=True):
        cargar_nelida_guias.clear()
        cargar_pdfs.clear()

_fuente_nelida = "🌐 Drive Compartido" if os.path.exists(_NELIDA_PRIMARY) else "💾 local"
_fuente_pdfs   = "🌐 red" if os.path.exists(_RED_BASE) else "💾 local"
st.caption(f"Nélida: {_fuente_nelida} · PDFs: {_fuente_pdfs} · {datetime.now().strftime('%d/%m/%Y %H:%M')}")

with st.spinner("Cargando..."):
    nelida = cargar_nelida_guias()
    pdfs   = cargar_pdfs()

df = cruzar(nelida, pdfs)

# ─── MÉTRICAS ──────────────────────────────────────────────────────────────────
total       = len(df)
completas   = (df["Estatus"].astype(str).str.upper() == "COMPLETO").sum()
incompletas = (df["Estatus"].astype(str).str.upper() == "INCOMPLETO").sum()
con_pdf     = (df["PDF_Sellado"] == "✅").sum()

c1, c2, c3, c4 = st.columns(4)
c1.metric("📄 Guías 2026",      total)
c2.metric("✅ Completas",       completas)
c3.metric("⚠️ Incompletas",    incompletas)
c4.metric("📁 PDFs sellados",   con_pdf)

st.divider()

# ─── TABS ──────────────────────────────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["📋 Todas las guías", "📄 PDFs en Z:", "🔍 Buscar por OC"])


# ══════════════════════════════════════════════════════════════
with tab1:
    f1, f2, f3 = st.columns([2, 2, 2])
    with f1:
        filtro_estatus = st.selectbox("Estatus", ["Todos", "COMPLETO", "INCOMPLETO"])
    with f2:
        meses = ["Todos"] + sorted(df["Mes"].dropna().replace("", float("nan")).dropna().unique().tolist())
        filtro_mes = st.selectbox("Mes (PDF)", meses)
    with f3:
        filtro_oc = st.text_input("Buscar por OC", placeholder="C004158380")

    vista = df.copy()
    if filtro_estatus != "Todos":
        vista = vista[vista["Estatus"].astype(str).str.upper() == filtro_estatus]
    if filtro_mes != "Todos":
        vista = vista[vista["Mes"] == filtro_mes]
    if filtro_oc:
        vista = vista[vista["OC"].str.contains(filtro_oc, case=False, na=False)]

    vista_disp = vista[["Guia", "Fecha", "OC", "Estatus", "Factura",
                         "PDF_Sellado", "Fecha_Traslado", "Detalle"]].copy()
    vista_disp["Fecha"]          = vista_disp["Fecha"].dt.strftime("%d/%m/%Y")
    vista_disp["Fecha_Traslado"] = vista_disp["Fecha_Traslado"].dt.strftime("%d/%m/%Y")

    st.caption(f"{len(vista_disp)} guías")
    st.dataframe(
        vista_disp,
        width="stretch",
        height=520,
        column_config={
            "Guia":           st.column_config.TextColumn("Guía",           width=90),
            "Fecha":          st.column_config.TextColumn("Fecha emisión",  width=105),
            "OC":             st.column_config.TextColumn("Orden de compra",width=140),
            "Estatus":        st.column_config.TextColumn("Estatus",        width=100),
            "Factura":        st.column_config.TextColumn("Factura",        width=100),
            "PDF_Sellado":    st.column_config.TextColumn("PDF sellado",    width=95),
            "Fecha_Traslado": st.column_config.TextColumn("Fecha traslado", width=110),
            "Detalle":        st.column_config.TextColumn("Detalle",        width=380),
        },
        hide_index=True,
    )


# ══════════════════════════════════════════════════════════════
with tab2:
    if pdfs.empty:
        st.warning("No se encontraron PDFs sellados en Z:. Verifica que la red esté conectada.")
    else:
        # ── Descarga por mes ──────────────────────────────────────
        st.subheader("⬇️ Descargar guías por mes")

        _folders = _guias_folders()
        _meses_disponibles = {
            os.path.basename(f_orig): (f_sell, f_orig)
            for f_sell, f_orig in _folders
            if os.path.exists(f_sell)
        }

        if not _meses_disponibles:
            st.info("No hay carpetas de guías selladas accesibles en la red.")
        else:
            col_sel, col_info, col_btn = st.columns([3, 2, 2])
            with col_sel:
                mes_elegido = st.selectbox(
                    "Seleccionar mes",
                    options=list(_meses_disponibles.keys()),
                    key="dl_mes",
                )
            f_sell_sel, f_orig_sel = _meses_disponibles[mes_elegido]
            pdfs_en_mes = len([f for f in os.listdir(f_sell_sel) if f.lower().endswith(".pdf")])
            with col_info:
                st.write("")
                st.info(f"{pdfs_en_mes} PDFs en este mes")
            with col_btn:
                st.write("")
                zip_data = zip_guias_mes(f_orig_sel, f_sell_sel)
                if zip_data:
                    st.download_button(
                        label="📦 Descargar ZIP",
                        data=zip_data,
                        file_name=f"Guias_{mes_elegido.replace(' ', '_')}.zip",
                        mime="application/zip",
                        use_container_width=True,
                    )
                else:
                    st.warning("No se pudo generar el ZIP.")

        st.divider()

        # ── Tabla completa ────────────────────────────────────────
        pdfs_disp = pdfs[["Guia", "OC_pdf", "Fecha_Traslado", "Mes", "Archivo"]].copy()
        pdfs_disp["Fecha_Traslado"] = pdfs_disp["Fecha_Traslado"].dt.strftime("%d/%m/%Y")

        # Indicar si esta guía está registrada en Nélida
        nelida_nums = set(nelida["Guia_num"].dropna())
        pdfs_disp["En Nélida"] = pdfs["Guia_num"].apply(lambda n: "✅" if n in nelida_nums else "❌")

        st.caption(f"{len(pdfs_disp)} PDFs sellados en Z:")
        st.dataframe(
            pdfs_disp,
            width="stretch",
            height=500,
            column_config={
                "Guia":           st.column_config.TextColumn("Guía",           width=90),
                "OC_pdf":         st.column_config.TextColumn("OC (en PDF)",    width=140),
                "Fecha_Traslado": st.column_config.TextColumn("Fecha traslado", width=110),
                "Mes":            st.column_config.TextColumn("Mes",            width=160),
                "En Nélida":      st.column_config.TextColumn("En Nélida",      width=90),
                "Archivo":        st.column_config.TextColumn("Archivo",        width=280),
            },
            hide_index=True,
        )


# ══════════════════════════════════════════════════════════════
with tab3:
    col_input, col_limpiar = st.columns([4, 1])
    with col_input:
        buscar = st.text_input("OC (parcial o completa)", placeholder="C004158380", key="buscar_oc")
    with col_limpiar:
        st.write("")
        if st.button("✖ Limpiar", use_container_width=True):
            st.session_state["buscar_oc"] = ""
            st.rerun()

    if buscar:
        guias_match = df[df["OC"].str.contains(buscar, case=False, na=False)]
        pdfs_match  = pdfs[pdfs["OC_pdf"].fillna("").str.contains(buscar, case=False)]

        st.markdown(f"**{len(guias_match)} guía(s) en archivo Nélida**")
        if not guias_match.empty:
            gm = guias_match[["Guia", "Fecha", "OC", "Estatus", "Factura",
                               "PDF_Sellado", "Fecha_Traslado", "Detalle"]].copy()
            gm["Fecha"]          = gm["Fecha"].dt.strftime("%d/%m/%Y")
            gm["Fecha_Traslado"] = gm["Fecha_Traslado"].dt.strftime("%d/%m/%Y")
            st.dataframe(gm, width="stretch", hide_index=True)
        else:
            st.info("No encontrado en el archivo de Nélida.")

        st.markdown(f"**{len(pdfs_match)} PDF(s) sellado(s) en Z:**")
        if not pdfs_match.empty:
            pm = pdfs_match[["Guia", "OC_pdf", "Fecha_Traslado", "Archivo"]].copy()
            pm["Fecha_Traslado"] = pm["Fecha_Traslado"].dt.strftime("%d/%m/%Y")
            st.dataframe(pm, width="stretch", hide_index=True)
        else:
            st.info("No encontrado en PDFs de Z:.")
