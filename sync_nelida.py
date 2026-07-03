"""
sync_nelida.py
Detecta filas nuevas o modificadas en el Excel de Nelida y las sube a Supabase.
Corre manualmente cuando se quiere sincronizar.

Uso:
    python sync_nelida.py            # sincroniza
    python sync_nelida.py --dry-run  # solo muestra que subiria, sin subir
"""

import os
import re
import sys
import argparse
import unicodedata
from pathlib import Path
from datetime import datetime

import pandas as pd
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://knkuyxjimwpquhzgxsro.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_KEY:
    print("ERROR: define SUPABASE_SERVICE_KEY en el archivo .env")
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
NELIDA_PRIMARY = Path(r"C:\Users\herru\OneDrive\Escritorio\Drive-Compartido\CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx")
NELIDA_BACKUP  = Path(r"C:\Dev\Netsat-Centrum\CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx")

def _nelida_path() -> Path:
    try:
        if NELIDA_PRIMARY.exists():
            return NELIDA_PRIMARY
    except PermissionError:
        pass
    if NELIDA_BACKUP.exists():
        print("  AVISO: usando backup (archivo principal abierto o no disponible)")
        return NELIDA_BACKUP
    print("ERROR: no se encontro el archivo de Nelida")
    sys.exit(1)

# Sufijos sucios en proyectos.codigo_oc: -DIG, -2 DIG, -1 DIG, etc.
SUFIJO_RE = re.compile(r'\s*-\s*\d*\s*DIG\b.*$', re.IGNORECASE)

# ---------------------------------------------------------------------------
# Helpers de limpieza
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    return ''.join(
        c for c in unicodedata.normalize('NFD', str(s).lower())
        if unicodedata.category(c) != 'Mn'
    ).strip()

def _find_col(df, *variants):
    normed = {_norm(c): c for c in df.columns}
    for v in variants:
        nv = _norm(v)
        if nv in normed:
            return normed[nv]
        for nc, orig in normed.items():
            if nv in nc:
                return orig
    return None

def txt(val) -> str | None:
    if pd.isna(val) or str(val).strip() in ("", "nan", "None"):
        return None
    return str(val).strip()

def num(val) -> float | None:
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def fecha(val) -> str | None:
    if pd.isna(val):
        return None
    try:
        return pd.to_datetime(val, dayfirst=True).strftime("%Y-%m-%d")
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Sincronizar tabla genérica
# ---------------------------------------------------------------------------
def _sync(tabla: str, rows: list[dict], clave: str, on_conflict: str, dry_run: bool = False):
    if not rows:
        print(f"  {tabla}: sin filas validas en el Excel")
        return

    r = supabase.table(tabla).select(clave).execute()
    conocidos = {row[clave] for row in r.data}

    nuevos     = [r for r in rows if r.get(clave) not in conocidos]
    existentes = len(rows) - len(nuevos)

    print(f"  {tabla}: {len(rows)} en Excel | {existentes} ya en Supabase | {len(nuevos)} nuevos")

    if dry_run:
        if nuevos:
            for r in nuevos:
                print(f"    [DRY-RUN] + {r.get(clave)}")
        else:
            print(f"    Todo al dia")
        return

    if rows:
        supabase.table(tabla).upsert(rows, on_conflict=on_conflict).execute()
        if nuevos:
            for r in nuevos:
                print(f"    + {r.get(clave)}")
        else:
            print(f"    Todo al dia")

# ---------------------------------------------------------------------------
# Hojas del Excel
# ---------------------------------------------------------------------------
def sync_facturas(path: Path, dry_run: bool = False):
    df = pd.read_excel(path, sheet_name="FACTURAS", header=0)
    df.columns = [str(c).strip() for c in df.columns]

    c_num = _find_col(df, "FACTURA N", "FACTURA")
    c_fec = _find_col(df, "FECHA EMISION", "FECHA")
    c_cli = _find_col(df, "CLIENTE")
    c_vs  = _find_col(df, "VALOR SIN IGV SOL", "V/VENTA S/")
    c_is  = _find_col(df, "IGV SOLES", "IGV S/")
    c_ts  = _find_col(df, "TOTAL SOLES", "TOTAL S/")
    c_vd  = _find_col(df, "VALOR SIN IGV DOLAR", "V/VENTA $")
    c_id  = _find_col(df, "IGV DOLAR", "IGV $")
    c_td  = _find_col(df, "TOTAL DOLAR", "TOTAL $")
    c_pag = _find_col(df, "PAGADO")
    c_ret = _find_col(df, "RETENCION ENTREGADA", "RETENCION")
    c_det = _find_col(df, "DETRACCION ENTREGADA", "DETRACCION")
    c_gui = _find_col(df, "GUIA REMISION", "GUIA")
    c_oc  = _find_col(df, "ORDEN DE COMPRA", "OC")
    c_obs = _find_col(df, "OBSERVACIONES", "OBS")

    rows = []
    for _, row in df.iterrows():
        numero = txt(row[c_num]) if c_num else None
        if not numero or not str(numero).startswith("F"):
            continue
        rows.append({
            "numero":               numero,
            "fecha_emision":        fecha(row[c_fec])  if c_fec else None,
            "cliente":              txt(row[c_cli])    if c_cli else None,
            "valor_sin_igv_sol":    num(row[c_vs])     if c_vs  else None,
            "igv_soles":            num(row[c_is])     if c_is  else None,
            "total_soles":          num(row[c_ts])     if c_ts  else None,
            "valor_sin_igv_dolar":  num(row[c_vd])     if c_vd  else None,
            "igv_dolar":            num(row[c_id])     if c_id  else None,
            "total_dolar":          num(row[c_td])     if c_td  else None,
            "pagado":               txt(row[c_pag])    if c_pag else None,
            "retencion_entregada":  txt(row[c_ret])    if c_ret else None,
            "detraccion_entregada": txt(row[c_det])    if c_det else None,
            "guia_remision":        txt(row[c_gui])    if c_gui else None,
            "orden_de_compra":      txt(row[c_oc])     if c_oc  else None,
            "observaciones":        txt(row[c_obs])    if c_obs else None,
        })

    _sync("facturas", rows, "numero", "numero", dry_run=dry_run)

def sync_guias(path: Path, dry_run: bool = False):
    df = pd.read_excel(path, sheet_name="GUIAS", header=0)
    df.columns = [str(c).strip() for c in df.columns]

    c_num = _find_col(df, "GUIA N", "GUIA")
    c_fec = _find_col(df, "FECHA", "FECHA EMISION")
    c_oc  = _find_col(df, "ORDEN DE COMPRA", "OC")
    c_est = _find_col(df, "ESTATUS", "ESTADO")
    c_fac = _find_col(df, "FACTURA")
    c_mes = _find_col(df, "MES")

    seen = set()
    rows = []
    for _, row in df.iterrows():
        raw = txt(row[c_num]) if c_num else None
        if not raw:
            continue
        m = re.search(r"T001-(\d+)", str(raw), re.IGNORECASE)
        numero = f"T001-{m.group(1)}" if m else raw.upper()
        if numero in seen:
            continue
        seen.add(numero)
        rows.append({
            "numero":        numero,
            "fecha_emision": fecha(row[c_fec]) if c_fec else None,
            "oc":            txt(row[c_oc])    if c_oc  else None,
            "estatus":       txt(row[c_est])   if c_est else None,
            "mes":           txt(row[c_mes])   if c_mes else None,
            "anio":          2026,
        })

    _sync("guias", rows, "numero", "numero", dry_run=dry_run)

def sync_proyectos(path: Path, dry_run: bool = False):
    df_raw = pd.read_excel(path, sheet_name="PROY-2026", header=None)
    header_row = 0
    for i, row in df_raw.iterrows():
        vals = [str(v) for v in row if pd.notna(v)]
        if len(vals) >= 4 and any("O/C" in v or "#Proyecto" in v for v in vals):
            header_row = i
            break
    df = pd.read_excel(path, sheet_name="PROY-2026", header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    c_oc   = _find_col(df, "O/C", "OC")
    c_fvta = _find_col(df, "Fac. Ventas", "FAC VENTA")
    c_guia = _find_col(df, "Guia Ventas", "GUIA")
    c_fcmp = _find_col(df, "Fac. Compras", "FAC COMPRA")
    c_est  = _find_col(df, "Estado", "ESTADO")

    rows = []
    for _, row in df.iterrows():
        oc = txt(row[c_oc]) if c_oc else None
        if not oc:
            continue
        oc = SUFIJO_RE.sub("", oc).strip()
        rows.append({
            "codigo_oc":      oc,
            "factura_venta":  txt(row[c_fvta]) if c_fvta else None,
            "guia":           txt(row[c_guia]) if c_guia else None,
            "factura_compra": txt(row[c_fcmp]) if c_fcmp else None,
            "estado":         txt(row[c_est])  if c_est  else None,
            "anio":           2026,
        })

    _sync("proyectos", rows, "codigo_oc", "codigo_oc", dry_run=dry_run)

def sync_coupa(path: Path, dry_run: bool = False):
    df_raw = pd.read_excel(path, sheet_name="COUPA2026", header=None)
    header_row = 0
    for i, row in df_raw.iterrows():
        vals = [str(v) for v in row if pd.notna(v)]
        if len(vals) >= 5 and any("O/C" in v for v in vals):
            header_row = i
            break
    df = pd.read_excel(path, sheet_name="COUPA2026", header=header_row)
    df.columns = [str(c).strip() for c in df.columns]

    c_fac = _find_col(df, "Factura", "FACTURA")
    c_fec = _find_col(df, "Fecha", "FECHA")
    c_mon = _find_col(df, "Monto", "MONTO")
    c_oc  = _find_col(df, "O/C", "OC")
    c_est = _find_col(df, "COUPA", "Estado", "ESTADO")

    rows = []
    for _, row in df.iterrows():
        fac = txt(row[c_fac]) if c_fac else None
        if not fac or not str(fac).startswith("F"):
            continue
        rows.append({
            "numero_factura": fac,
            "fecha":          fecha(row[c_fec])  if c_fec else None,
            "monto":          num(row[c_mon])    if c_mon else None,
            "codigo_oc":      txt(row[c_oc])     if c_oc  else None,
            "estado_pago":    txt(row[c_est])    if c_est else None,
            "anio":           2026,
        })

    _sync("coupa", rows, "numero_factura", "numero_factura", dry_run=dry_run)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra que subiria, sin subir")
    args = parser.parse_args()

    print("=" * 55)
    print("NETSAT - Sync Excel Nelida a Supabase")
    if args.dry_run:
        print("  MODO: dry-run (solo revision, sin cambios)")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    path = _nelida_path()
    print(f"\nArchivo: {path}")

    xl = pd.ExcelFile(path)
    print(f"Hojas: {xl.sheet_names}\n")

    if "FACTURAS" in xl.sheet_names:
        print("[1/4] FACTURAS")
        sync_facturas(path, dry_run=args.dry_run)

    if "GUIAS" in xl.sheet_names:
        print("\n[2/4] GUIAS")
        sync_guias(path, dry_run=args.dry_run)

    if "PROY-2026" in xl.sheet_names:
        print("\n[3/4] PROYECTOS 2026")
        sync_proyectos(path, dry_run=args.dry_run)

    if "COUPA2026" in xl.sheet_names:
        print("\n[4/4] COUPA 2026")
        sync_coupa(path, dry_run=args.dry_run)

    print()
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)
