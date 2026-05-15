"""
migrate_to_supabase.py
Migración inicial: sube PDFs de guías y datos del Excel de Nélida a Supabase.
Corre UNA SOLA VEZ desde el servidor. Usa upsert para ser idempotente.

Requisitos:
    pip install supabase pandas openpyxl python-dotenv
"""

import os
import re
import sys
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://knkuyxjimwpquhzgxsro.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # service_role — bypasa RLS

if not SUPABASE_KEY:
    sys.exit("ERROR: define SUPABASE_SERVICE_KEY en el archivo .env")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
Z_BASE = Path(r"Z:\NETSAT\NETSAT 2026\FACTURAS GUIAS NETSAT SRL 2026\GUIAS 2026")
LOCAL_BASE = Path(r"C:\Users\herru\OneDrive\Escritorio\Netsat-Centrum")

NELIDA_PRIMARY = Path(r"C:\Users\herru\OneDrive\Escritorio\Drive-Compartido\CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx")
NELIDA_BACKUP  = LOCAL_BASE / "CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx"

def _base():
    return Z_BASE if Z_BASE.exists() else LOCAL_BASE

# (subcarpeta_selladas, subcarpeta_digitales, mes)
GUIAS_FOLDERS = [
    ("GUIAS ENERO 2026/GUIAS SELLADAS 2026/GUIAS SELLADAS ENERO 26", "GUIAS ENERO 2026",   "ENERO"),
    ("GUIAS FEBRERO 2026/GUIAS SELLADAS FEBRERO 2026",               "GUIAS FEBRERO 2026", "FEBRERO"),
    ("GUIAS MARZO 2026/GUIAS SELLADAS MARZO 2026",                   "GUIAS MARZO 2026",   "MARZO"),
    ("GUIAS ABRIL 2026/GUIAS SELLADAS ABRIL 2026",                   "GUIAS ABRIL 2026",   "ABRIL"),
    ("GUIAS MAYO 2026/GUIAS SELLADAS MAYO 2026",                     "GUIAS MAYO 2026",    "MAYO"),
]

NUMERO_RE = re.compile(r"T001-(\d+)", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def extraer_numero(nombre: str) -> str | None:
    m = NUMERO_RE.search(nombre)
    return f"T001-{m.group(1)}" if m else None

def subir_pdf(ruta: Path, bucket: str, storage_path: str) -> bool:
    try:
        with open(ruta, "rb") as f:
            data = f.read()
        supabase.storage.from_(bucket).upload(
            path=storage_path,
            file=data,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        return True
    except Exception as e:
        print(f"  ERROR subiendo {ruta.name}: {e}")
        return False

def registrar_archivo(nombre, bucket, storage_path, mes, guia_numero=None):
    supabase.table("archivos").upsert({
        "nombre":       nombre,
        "bucket":       bucket,
        "storage_path": storage_path,
        "tipo":         "PDF",
        "mes":          mes,
        "anio":         2026,
        "guia_numero":  guia_numero,
        "subido_por":   "migrate_to_supabase.py",
    }, on_conflict="storage_path").execute()

# ---------------------------------------------------------------------------
# 1. Subir PDFs
# ---------------------------------------------------------------------------
def migrar_pdfs():
    base = _base()
    total_ok = 0
    total_err = 0

    for sub_selladas, sub_digitales, mes in GUIAS_FOLDERS:
        carpeta_selladas  = base / sub_selladas
        carpeta_digitales = base / sub_digitales

        for carpeta, bucket, tipo in [
            (carpeta_selladas,  "guias-selladas",  "sellada"),
            (carpeta_digitales, "guias-digitales", "digital"),
        ]:
            if not carpeta.exists():
                print(f"  — Carpeta no encontrada, se omite: {carpeta}")
                continue

            pdfs = [p for p in carpeta.iterdir() if p.suffix.lower() == ".pdf"]
            print(f"\n{mes} [{tipo}] — {len(pdfs)} PDFs en {carpeta.name}")

            for pdf in sorted(pdfs):
                numero = extraer_numero(pdf.name)
                storage_path = f"{mes}/{tipo}/{pdf.name}"

                ok = subir_pdf(pdf, bucket, storage_path)
                if ok:
                    registrar_archivo(pdf.name, bucket, storage_path, mes, numero)
                    print(f"  OK {pdf.name}")
                    total_ok += 1
                else:
                    total_err += 1

    print(f"\n=== PDFs: {total_ok} subidos, {total_err} errores ===")

# ---------------------------------------------------------------------------
# 2. Migrar Excel de Nélida
# ---------------------------------------------------------------------------
def _nelida_path() -> Path:
    if NELIDA_PRIMARY.exists():
        return NELIDA_PRIMARY
    if NELIDA_BACKUP.exists():
        return NELIDA_BACKUP
    sys.exit("ERROR: no se encontró el archivo de Nélida")

import unicodedata

def _norm(s: str) -> str:
    """Normaliza texto: minúsculas, sin tildes ni símbolos raros."""
    return ''.join(
        c for c in unicodedata.normalize('NFD', str(s).lower())
        if unicodedata.category(c) != 'Mn'
    ).strip()

def _find_col(df, *variants):
    """Busca columna tolerando encoding, tildes y mayúsculas."""
    normed = {_norm(c): c for c in df.columns}
    for v in variants:
        nv = _norm(v)
        if nv in normed:
            return normed[nv]
        for nc, orig in normed.items():
            if nv in nc:
                return orig
    return None

def limpiar_texto(val) -> str | None:
    if pd.isna(val) or str(val).strip() in ("", "nan", "None"):
        return None
    return str(val).strip()

def limpiar_numero(val) -> float | None:
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def limpiar_fecha(val) -> str | None:
    if pd.isna(val):
        return None
    try:
        return pd.to_datetime(val, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None

def migrar_facturas(path: Path):
    df = pd.read_excel(path, sheet_name="FACTURAS", header=0)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"  Columnas FACTURAS: {list(df.columns)}")

    c_num  = _find_col(df, "FACTURA N°", "FACTURA N", "FACTURA")
    c_fec  = _find_col(df, "FECHA EMISION", "FECHA EMISIÓN", "FECHA")
    c_cli  = _find_col(df, "CLIENTE")
    c_vs   = _find_col(df, "VALOR SIN IGV SOL", "VALOR SIN IGV SOLES", "V/VENTA S/")
    c_is   = _find_col(df, "IGV SOLES", "IGV S/")
    c_ts   = _find_col(df, "TOTAL SOLES", "TOTAL S/")
    c_vd   = _find_col(df, "VALOR SIN IGV DÓLAR", "VALOR SIN IGV DOLAR", "V/VENTA $")
    c_id   = _find_col(df, "IGV DÓLAR", "IGV DOLAR", "IGV $")
    c_td   = _find_col(df, "TOTAL DÓLAR", "TOTAL DOLAR", "TOTAL $")
    c_pag  = _find_col(df, "PAGADO")
    c_ret  = _find_col(df, "RETENCION ENTREGADA", "RETENCIÓN ENTREGADA", "RETENCION")
    c_det  = _find_col(df, "DETRACCION ENTREGADA", "DETRACCIÓN ENTREGADA", "DETRACCION")
    c_gui  = _find_col(df, "GUIA REMISION", "GUIA REMISION", "GUIA")
    c_oc   = _find_col(df, "ORDEN DE COMPRA", "OC")
    c_obs  = _find_col(df, "OBSERVACIONES", "OBS")

    rows = []
    for _, row in df.iterrows():
        numero = limpiar_texto(row[c_num]) if c_num else None
        if not numero or not str(numero).startswith("F"):
            continue
        rows.append({
            "numero":               numero,
            "fecha_emision":        limpiar_fecha(row[c_fec])  if c_fec else None,
            "cliente":              limpiar_texto(row[c_cli])   if c_cli else None,
            "valor_sin_igv_sol":    limpiar_numero(row[c_vs])   if c_vs  else None,
            "igv_soles":            limpiar_numero(row[c_is])   if c_is  else None,
            "total_soles":          limpiar_numero(row[c_ts])   if c_ts  else None,
            "valor_sin_igv_dolar":  limpiar_numero(row[c_vd])   if c_vd  else None,
            "igv_dolar":            limpiar_numero(row[c_id])   if c_id  else None,
            "total_dolar":          limpiar_numero(row[c_td])   if c_td  else None,
            "pagado":               limpiar_texto(row[c_pag])   if c_pag else None,
            "retencion_entregada":  limpiar_texto(row[c_ret])   if c_ret else None,
            "detraccion_entregada": limpiar_texto(row[c_det])   if c_det else None,
            "guia_remision":        limpiar_texto(row[c_gui])   if c_gui else None,
            "orden_de_compra":      limpiar_texto(row[c_oc])    if c_oc  else None,
            "observaciones":        limpiar_texto(row[c_obs])   if c_obs else None,
        })

    if rows:
        supabase.table("facturas").upsert(rows, on_conflict="numero").execute()
    print(f"  OK Facturas insertadas: {len(rows)}")

def migrar_guias_excel(path: Path):
    df = pd.read_excel(path, sheet_name="GUIAS", header=0)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"  Columnas GUIAS: {list(df.columns)}")

    # Columnas conocidas del Excel de Nélida:
    # GUIA N° | FECHA | ORDEN DE COMPRA | ESTATUS | FACTURA | CLIENTE/MOTIVO
    c_num = _find_col(df, "GUIA N°", "GUIA N", "GUIA")
    c_fec = _find_col(df, "FECHA", "FECHA EMISION")
    c_oc  = _find_col(df, "ORDEN DE COMPRA", "OC")
    c_est = _find_col(df, "ESTATUS", "ESTADO")
    c_fac = _find_col(df, "FACTURA")
    c_mes = _find_col(df, "MES")

    seen = set()
    rows = []
    for _, row in df.iterrows():
        raw = limpiar_texto(row[c_num]) if c_num else None
        if not raw:
            continue
        # normalizar a T001-NNN
        m = re.search(r"T001-(\d+)", str(raw), re.IGNORECASE)
        numero = f"T001-{m.group(1)}" if m else raw.upper()

        if numero in seen:
            continue
        seen.add(numero)

        oc_val = limpiar_texto(row[c_oc]) if c_oc else None
        rows.append({
            "numero":         numero,
            "fecha_emision":  limpiar_fecha(row[c_fec])  if c_fec else None,
            "oc":             oc_val,
            "estatus":        limpiar_texto(row[c_est])   if c_est else None,
            "mes":            limpiar_texto(row[c_mes])   if c_mes else None,
            "anio":           2026,
        })

    if rows:
        supabase.table("guias").upsert(rows, on_conflict="numero").execute()
    print(f"  OK Guias (Excel) insertadas: {len(rows)}")

def migrar_proyectos(path: Path):
    # El Excel tiene una fila de título antes del encabezado real — detectar header dinámicamente
    df_raw = pd.read_excel(path, sheet_name="PROY-2026", header=None)
    header_row = 0
    for i, row in df_raw.iterrows():
        vals = [str(v).upper() for v in row if pd.notna(v)]
        if any("OC" in v or "PROYECTO" in v or "FACTURA" in v for v in vals):
            header_row = i
            break
    df = pd.read_excel(path, sheet_name="PROY-2026", header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"  Columnas PROY-2026: {list(df.columns)}")

    rows = []
    for _, row in df.iterrows():
        fila = {c: limpiar_texto(row[c]) for c in df.columns}
        if all(v is None for v in fila.values()):
            continue
        rows.append({
            "codigo_oc":      next((fila[c] for c in df.columns if "OC" in c.upper() and fila.get(c)), None),
            "factura_venta":  next((fila[c] for c in df.columns if "VENTA" in c.upper() and fila.get(c)), None),
            "guia":           next((fila[c] for c in df.columns if "GUIA" in c.upper() and fila.get(c)), None),
            "factura_compra": next((fila[c] for c in df.columns if "COMPRA" in c.upper() and fila.get(c)), None),
            "estado":         next((fila[c] for c in df.columns if "ESTADO" in c.upper() and fila.get(c)), None),
            "anio":           2026,
        })

    if rows:
        supabase.table("proyectos").insert(rows).execute()
    print(f"  OK Proyectos insertados: {len(rows)}")

def migrar_coupa(path: Path):
    df_raw = pd.read_excel(path, sheet_name="COUPA2026", header=None)
    header_row = 0
    for i, row in df_raw.iterrows():
        vals = [str(v).upper() for v in row if pd.notna(v)]
        if any("FACTURA" in v or "ESTADO" in v or "OC" in v for v in vals):
            header_row = i
            break
    df = pd.read_excel(path, sheet_name="COUPA2026", header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"  Columnas COUPA2026: {list(df.columns)}")

    rows = []
    for _, row in df.iterrows():
        fila = {c: limpiar_texto(row[c]) for c in df.columns}
        if all(v is None for v in fila.values()):
            continue
        rows.append({
            "numero_factura": next((fila[c] for c in df.columns if "FACTURA" in c.upper() and fila.get(c)), None),
            "estado_pago":    next((fila[c] for c in df.columns if "ESTADO" in c.upper() and fila.get(c)), None),
            "codigo_oc":      next((fila[c] for c in df.columns if "OC" in c.upper() and fila.get(c)), None),
            "anio":           2026,
        })

    if rows:
        supabase.table("coupa").insert(rows).execute()
    print(f"  OK COUPA insertados: {len(rows)}")

def migrar_excel_nelida():
    path = _nelida_path()
    print(f"\nLeyendo archivo de Nélida: {path}")
    xl = pd.ExcelFile(path)
    print(f"Hojas encontradas: {xl.sheet_names}")

    if "FACTURAS" in xl.sheet_names:
        print("\n--- FACTURAS ---")
        migrar_facturas(path)

    if "GUIAS" in xl.sheet_names:
        print("\n--- GUIAS ---")
        migrar_guias_excel(path)

    if "PROY-2026" in xl.sheet_names:
        print("\n--- PROYECTOS 2026 ---")
        migrar_proyectos(path)

    if "COUPA2026" in xl.sheet_names:
        print("\n--- COUPA 2026 ---")
        migrar_coupa(path)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("NETSAT — Migración inicial a Supabase")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Base de guías: {'Z: (red)' if Z_BASE.exists() else 'local'}")
    print("=" * 60)

    print("\n[1/2] Subiendo PDFs a Storage...")
    migrar_pdfs()

    print("\n[2/2] Migrando Excel de Nélida...")
    migrar_excel_nelida()

    print("\n" + "=" * 60)
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Verifica en el dashboard de Supabase: Storage y Table Editor.")
    print("=" * 60)
