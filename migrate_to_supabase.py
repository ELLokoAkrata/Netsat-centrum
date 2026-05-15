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
    try:
        if NELIDA_PRIMARY.exists():
            return NELIDA_PRIMARY
    except PermissionError:
        pass  # archivo abierto en Excel — usar backup
    if NELIDA_BACKUP.exists():
        return NELIDA_BACKUP
    sys.exit("ERROR: no se encontro el archivo de Nelida")  # print-safe: sin tildes

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
    c_fec  = _find_col(df, "FECHA EMISION", "FECHA EMISION", "FECHA")
    c_cli  = _find_col(df, "CLIENTE")
    c_vs   = _find_col(df, "VALOR SIN IGV SOL", "VALOR SIN IGV SOLES", "V/VENTA S/")
    c_is   = _find_col(df, "IGV SOLES", "IGV S/")
    c_ts   = _find_col(df, "TOTAL SOLES", "TOTAL S/")
    c_vd   = _find_col(df, "VALOR SIN IGV DOLAR", "VALOR SIN IGV DOLAR", "V/VENTA $")
    c_id   = _find_col(df, "IGV DOLAR", "IGV DOLAR", "IGV $")
    c_td   = _find_col(df, "TOTAL DOLAR", "TOTAL DOLAR", "TOTAL $")
    c_pag  = _find_col(df, "PAGADO")
    c_ret  = _find_col(df, "RETENCION ENTREGADA", "RETENCION ENTREGADA", "RETENCION")
    c_det  = _find_col(df, "DETRACCION ENTREGADA", "DETRACCION ENTREGADA", "DETRACCION")
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
    # Fila 0 tiene título con "PROYECTO" que engaña la detección simple.
    # Buscar la fila que tenga O/C y al menos 4 celdas no vacías.
    df_raw = pd.read_excel(path, sheet_name="PROY-2026", header=None)
    header_row = 0
    for i, row in df_raw.iterrows():
        vals = [str(v) for v in row if pd.notna(v)]
        if len(vals) >= 4 and any("O/C" in v or "#Proyecto" in v for v in vals):
            header_row = i
            break
    df = pd.read_excel(path, sheet_name="PROY-2026", header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"  Columnas PROY-2026: {list(df.columns)}")

    c_oc    = _find_col(df, "O/C", "OC")
    c_fvta  = _find_col(df, "Fac. Ventas", "Factura Venta", "FAC VENTA")
    c_guia  = _find_col(df, "Guia Ventas", "Guia Ventas", "GUIA")
    c_fcmp  = _find_col(df, "Fac. Compras", "Factura Compra", "FAC COMPRA")
    c_est   = _find_col(df, "Estado", "ESTADO")

    rows = []
    for _, row in df.iterrows():
        oc = limpiar_texto(row[c_oc]) if c_oc else None
        if not oc:
            continue
        rows.append({
            "codigo_oc":      oc,
            "factura_venta":  limpiar_texto(row[c_fvta])  if c_fvta else None,
            "guia":           limpiar_texto(row[c_guia])  if c_guia else None,
            "factura_compra": limpiar_texto(row[c_fcmp])  if c_fcmp else None,
            "estado":         limpiar_texto(row[c_est])   if c_est  else None,
            "anio":           2026,
        })

    if rows:
        supabase.table("proyectos").insert(rows).execute()
    print(f"  OK Proyectos insertados: {len(rows)}")

def migrar_coupa(path: Path):
    # Filas 0-2 tienen leyenda/notas. Header real esta en la fila con O/C y 5+ celdas.
    df_raw = pd.read_excel(path, sheet_name="COUPA2026", header=None)
    header_row = 0
    for i, row in df_raw.iterrows():
        vals = [str(v) for v in row if pd.notna(v)]
        if len(vals) >= 5 and any("O/C" in v for v in vals):
            header_row = i
            break
    df = pd.read_excel(path, sheet_name="COUPA2026", header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"  Columnas COUPA2026: {list(df.columns)}")

    c_fac  = _find_col(df, "Factura", "FACTURA")
    c_fec  = _find_col(df, "Fecha", "FECHA")
    c_mon  = _find_col(df, "Monto", "MONTO")
    c_oc   = _find_col(df, "O/C", "OC")
    c_est  = _find_col(df, "COUPA", "Estado", "ESTADO")

    rows = []
    for _, row in df.iterrows():
        fac = limpiar_texto(row[c_fac]) if c_fac else None
        if not fac or not str(fac).startswith("F"):
            continue
        rows.append({
            "numero_factura": fac,
            "fecha":          limpiar_fecha(row[c_fec])   if c_fec else None,
            "monto":          limpiar_numero(row[c_mon])  if c_mon else None,
            "codigo_oc":      limpiar_texto(row[c_oc])    if c_oc  else None,
            "estado_pago":    limpiar_texto(row[c_est])   if c_est else None,
            "anio":           2026,
        })

    if rows:
        supabase.table("coupa").insert(rows).execute()
    print(f"  OK COUPA insertados: {len(rows)}")

def migrar_ocs():
    path = LOCAL_BASE / "OC_Antapaccay.xlsx"
    if not path.exists():
        print("  SKIP: OC_Antapaccay.xlsx no encontrado")
        return

    df_raw = pd.read_excel(path, sheet_name="Hoja1", header=None)
    header_row = 0
    for i, row in df_raw.iterrows():
        vals = [str(v).upper() for v in row if pd.notna(v)]
        if "OC" in vals or any("OC" == v.strip() for v in vals):
            header_row = i
            break
    df = pd.read_excel(path, sheet_name="Hoja1", header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"  Columnas OC: {list(df.columns)}")

    c_oc   = _find_col(df, "OC")
    c_item = _find_col(df, "Item", "ITEM")
    c_desc = _find_col(df, "Descripcion", "Descripcion", "DESCRIPCION")
    c_cant = _find_col(df, "Cant", "CANTIDAD")
    c_vuu  = _find_col(df, "Venta Unit US $", "Venta Unit", "VENTA UNIT")
    c_vtu  = _find_col(df, "Venta Total US $", "Venta Total", "VENTA TOTAL")
    c_obs  = _find_col(df, "Observaciones", "OBS")

    rows = []
    for _, row in df.iterrows():
        oc = limpiar_texto(row[c_oc]) if c_oc else None
        if not oc:
            continue
        rows.append({
            "codigo_oc":      oc,
            "item":           limpiar_texto(row[c_item])   if c_item else None,
            "descripcion":    limpiar_texto(row[c_desc])   if c_desc else None,
            "cantidad":       limpiar_numero(row[c_cant])  if c_cant else None,
            "venta_unit_usd": limpiar_numero(row[c_vuu])   if c_vuu  else None,
            "venta_total_usd":limpiar_numero(row[c_vtu])   if c_vtu  else None,
            "observaciones":  limpiar_texto(row[c_obs])    if c_obs  else None,
        })

    if rows:
        supabase.table("ocs").upsert(rows, on_conflict="codigo_oc,item").execute()
    print(f"  OK OCs insertadas: {len(rows)}")

def migrar_excel_nelida():
    path = _nelida_path()
    print(f"\nLeyendo archivo de Nelida: {path}")
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
    print("NETSAT - Migracion a Supabase")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Base de guias: {'Z: (red)' if Z_BASE.exists() else 'local'}")
    print("=" * 60)

    print("\n[1/3] Subiendo PDFs a Storage...")
    migrar_pdfs()

    print("\n[2/3] Migrando OCs (OC_Antapaccay.xlsx)...")
    migrar_ocs()

    print("\n[3/3] Migrando Excel de Nelida...")
    migrar_excel_nelida()

    print("\n" + "=" * 60)
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("Verifica en el dashboard de Supabase: Storage y Table Editor.")
    print("=" * 60)
