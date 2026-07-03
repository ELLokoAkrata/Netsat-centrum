"""
revisar_estado.py
Revision de estado sin modificar nada — compara fuentes locales vs Supabase
y muestra el delta (que falta sincronizar).

Uso:
    python revisar_estado.py
"""

import os
import re
import sys
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
# Rutas (mismas que los scripts de sync)
# ---------------------------------------------------------------------------
Z_BASE = Path(r"Z:\NETSAT\NETSAT 2026\FACTURAS GUIAS NETSAT SRL 2026\GUIAS 2026")
LOCAL_BASE = Path(r"C:\Dev\Netsat-Centrum")

NELIDA_PRIMARY = Path(r"C:\Users\herru\OneDrive\Escritorio\Drive-Compartido\CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx")
NELIDA_BACKUP  = Path(r"C:\Dev\Netsat-Centrum\CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx")

OC_DIR = Path(r"Z:\NETSAT\NETSAT 2026\ORDENES DE COMPRA 2026\OC CLIENTES 2026\ANTAPACCAY 2026")
OC_RE  = re.compile(r"OC_(C\d+)", re.IGNORECASE)
SUFIJO_RE = re.compile(r'\s*-\s*\d*\s*DIG\b.*$', re.IGNORECASE)

GUIAS_FOLDERS = [
    ("GUIAS ENERO 2026/GUIAS SELLADAS 2026/GUIAS SELLADAS ENERO 26", "GUIAS ENERO 2026",   "ENERO"),
    ("GUIAS FEBRERO 2026/GUIAS SELLADAS FEBRERO 2026",               "GUIAS FEBRERO 2026", "FEBRERO"),
    ("GUIAS MARZO 2026/GUIAS SELLADAS MARZO 2026",                   "GUIAS MARZO 2026",   "MARZO"),
    ("GUIAS ABRIL 2026/GUIAS SELLADAS ABRIL 2026",                   "GUIAS ABRIL 2026",   "ABRIL"),
    ("GUIAS MAYO 2026/GUIAS SELLADAS MAYO 2026",                     "GUIAS MAYO 2026",    "MAYO"),
    ("GUIAS JUNIO 2026/GUIAS SELLADAS JUNIO 2026",                   "GUIAS JUNIO 2026",   "JUNIO"),
]

NUMERO_RE = re.compile(r"T001-(\d+)", re.IGNORECASE)

SEP  = "=" * 60
SEP2 = "-" * 60

def _base() -> tuple[Path, str]:
    if Z_BASE.exists():
        return Z_BASE, "red Z:"
    return LOCAL_BASE, "local"

def _nelida_path() -> Path | None:
    try:
        if NELIDA_PRIMARY.exists():
            return NELIDA_PRIMARY
    except PermissionError:
        pass
    if NELIDA_BACKUP.exists():
        return NELIDA_BACKUP
    return None

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

# ---------------------------------------------------------------------------
# Revisar PDFs (guias_despacho)
# ---------------------------------------------------------------------------
def revisar_pdfs():
    print(f"\n{'PDFs / GUIAS DE DESPACHO':^60}")
    print(SEP2)

    base, fuente = _base()
    print(f"  Fuente local: {fuente} ({base})")

    # Supabase — solo guias (excluir OCs que viven en otro directorio)
    r = supabase.table("archivos").select("storage_path").neq("tipo", "OC").execute()
    en_supabase = {row["storage_path"] for row in r.data}

    # Local
    encontrados: list[dict] = []
    for sub_selladas, sub_digitales, mes in GUIAS_FOLDERS:
        for sub, bucket, tipo in [
            (sub_selladas,  "guias-selladas",  "sellada"),
            (sub_digitales, "guias-digitales", "digital"),
        ]:
            carpeta = base / sub
            if not carpeta.exists():
                continue
            for pdf in carpeta.iterdir():
                if pdf.suffix.lower() != ".pdf":
                    continue
                storage_path = f"{mes}/{tipo}/{pdf.name}"
                encontrados.append({
                    "storage_path": storage_path,
                    "nombre":       pdf.name,
                    "mes":          mes,
                    "tipo":         tipo,
                })

    nuevos = [i for i in encontrados if i["storage_path"] not in en_supabase]
    solo_supabase = en_supabase - {i["storage_path"] for i in encontrados}

    print(f"  En Supabase:       {len(en_supabase):>4}")
    print(f"  En fuente local:   {len(encontrados):>4}")

    if not nuevos:
        print(f"  Delta nuevos:         0  [OK — todo sincronizado]")
    else:
        print(f"  Delta nuevos:      {len(nuevos):>4}  [PENDIENTES DE SUBIR]")
        for i in nuevos:
            print(f"    + {i['mes']} [{i['tipo']}] {i['nombre']}")

    if solo_supabase:
        print(f"  Solo en Supabase:  {len(solo_supabase):>4}  (ya no estan en disco)")

# ---------------------------------------------------------------------------
# Revisar OCs de Antapaccay
# ---------------------------------------------------------------------------
def revisar_ocs():
    print(f"\n{'OCs ANTAPACCAY':^60}")
    print(SEP2)

    if not OC_DIR.exists():
        print(f"  Z: no disponible — se omite revision de OCs")
        return

    # Supabase — OCs con PDF subido
    r = supabase.table("archivos").select("storage_path").eq("tipo", "OC").execute()
    conocidos = set()
    for row in r.data:
        partes = row["storage_path"].split("/")
        if len(partes) >= 3:
            conocidos.add(partes[2])

    # Local
    OC_RE_local = re.compile(r"OC_(C\d+)", re.IGNORECASE)
    en_local = set()
    for carpeta in OC_DIR.iterdir():
        if carpeta.is_dir():
            m = OC_RE_local.search(carpeta.name)
            if m:
                en_local.add(m.group(1))

    nuevos = en_local - conocidos
    print(f"  En Supabase (con PDF):  {len(conocidos):>4}")
    print(f"  En Z: (carpetas):       {len(en_local):>4}")
    if not nuevos:
        print(f"  Delta:                     0  [OK]")
    else:
        print(f"  Delta:                {len(nuevos):>4}  [PENDIENTES]")
        for v in sorted(nuevos):
            print(f"    + {v}")

# ---------------------------------------------------------------------------
# Revisar tablas del Excel de Nelida
# ---------------------------------------------------------------------------
def _revisar_tabla(tabla: str, local_ids: set, clave_label: str):
    r = supabase.table(tabla).select("*").execute()
    en_supabase = {str(row.get(list(row.keys())[1])) for row in r.data} if r.data else set()

    # Buscar la clave correcta segun la tabla
    if r.data:
        primera_fila = r.data[0]
        claves_candidatas = [k for k in primera_fila if k != "id" and k != "created_at"]
        clave = claves_candidatas[0] if claves_candidatas else None
        en_supabase = {str(row.get(clave)) for row in r.data if row.get(clave)}

    nuevos = local_ids - en_supabase
    print(f"\n  {tabla}:")
    print(f"    En Excel:        {len(local_ids):>4}")
    print(f"    En Supabase:     {len(en_supabase):>4}")
    if not nuevos:
        print(f"    Delta:              0  [OK]")
    else:
        print(f"    Delta:         {len(nuevos):>4}  [PENDIENTES]")
        for v in sorted(nuevos)[:10]:
            print(f"      + {v}")
        if len(nuevos) > 10:
            print(f"      ... y {len(nuevos) - 10} mas")

def revisar_nelida():
    print(f"\n{'EXCEL DE NELIDA':^60}")
    print(SEP2)

    path = _nelida_path()
    if not path:
        print("  ERROR: no se encontro el archivo de Nelida")
        return
    print(f"  Archivo: {path}")

    xl = pd.ExcelFile(path)

    # FACTURAS
    if "FACTURAS" in xl.sheet_names:
        df = pd.read_excel(path, sheet_name="FACTURAS", header=0)
        df.columns = [str(c).strip() for c in df.columns]
        c_num = _find_col(df, "FACTURA N", "FACTURA")
        ids = set()
        if c_num:
            for v in df[c_num]:
                s = str(v).strip()
                if s.startswith("F"):
                    ids.add(s)
        _revisar_tabla_simple("facturas", ids, "numero")

    # GUIAS
    if "GUIAS" in xl.sheet_names:
        df = pd.read_excel(path, sheet_name="GUIAS", header=0)
        df.columns = [str(c).strip() for c in df.columns]
        c_num = _find_col(df, "GUIA N", "GUIA")
        ids = set()
        if c_num:
            for v in df[c_num]:
                m = re.search(r"T001-(\d+)", str(v), re.IGNORECASE)
                if m:
                    ids.add(f"T001-{m.group(1)}")
        _revisar_tabla_simple("guias", ids, "numero")

    # PROYECTOS
    if "PROY-2026" in xl.sheet_names:
        df_raw = pd.read_excel(path, sheet_name="PROY-2026", header=None)
        header_row = 0
        for i, row in df_raw.iterrows():
            vals = [str(v) for v in row if pd.notna(v)]
            if len(vals) >= 4 and any("O/C" in v or "#Proyecto" in v for v in vals):
                header_row = i
                break
        df = pd.read_excel(path, sheet_name="PROY-2026", header=header_row)
        df.columns = [str(c).strip() for c in df.columns]
        c_oc = _find_col(df, "O/C", "OC")
        ids = set()
        if c_oc:
            for v in df[c_oc]:
                s = str(v).strip()
                if s and s not in ("nan", "None", ""):
                    s = SUFIJO_RE.sub("", s).strip()
                    ids.add(s)
        _revisar_tabla_simple("proyectos", ids, "codigo_oc")

    # COUPA
    if "COUPA2026" in xl.sheet_names:
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
        ids = set()
        if c_fac:
            for v in df[c_fac]:
                s = str(v).strip()
                if s.startswith("F"):
                    ids.add(s)
        _revisar_tabla_simple("coupa", ids, "numero_factura")

def _revisar_tabla_simple(tabla: str, local_ids: set, clave: str):
    r = supabase.table(tabla).select(clave).execute()
    en_supabase = {str(row[clave]) for row in r.data if row.get(clave)}

    nuevos = local_ids - en_supabase
    print(f"\n  {tabla}:")
    print(f"    En Excel:        {len(local_ids):>4}")
    print(f"    En Supabase:     {len(en_supabase):>4}")
    if not nuevos:
        print(f"    Delta:              0  [OK]")
    else:
        print(f"    Delta:         {len(nuevos):>4}  [PENDIENTES]")
        for v in sorted(nuevos)[:10]:
            print(f"      + {v}")
        if len(nuevos) > 10:
            print(f"      ... y {len(nuevos) - 10} mas")

# ---------------------------------------------------------------------------
# Resumen de Supabase
# ---------------------------------------------------------------------------
def resumen_supabase():
    print(f"\n{'ESTADO SUPABASE':^60}")
    print(SEP2)

    tablas = {
        "archivos":  ("storage_path", "PDFs (total)"),
        "facturas":  ("numero",       "Facturas"),
        "guias":     ("numero",       "Guias"),
        "proyectos": ("codigo_oc",    "Proyectos"),
        "coupa":     ("numero_factura","COUPA"),
        "ocs":       ("codigo_oc",    "OC items (padre)"),
    }

    for tabla, (clave, label) in tablas.items():
        try:
            r = supabase.table(tabla).select(clave, count="exact").execute()
            n = r.count if r.count is not None else len(r.data)
            print(f"  {label:<15} {n:>4}")
        except Exception as e:
            print(f"  {label:<15} ERROR: {e}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(SEP)
    print(f"{'NETSAT — REVISION DE ESTADO':^60}")
    print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S'):^60}")
    print(SEP)

    resumen_supabase()
    revisar_pdfs()
    revisar_ocs()
    revisar_nelida()

    print(f"\n{SEP}")
    print("Protocolo de sincronizacion:")
    print("  Si hay deltas en PDFs:    python sync_guias.py --dry-run")
    print("                            python sync_guias.py")
    print("  Si hay deltas en tablas:  python sync_nelida.py --dry-run")
    print("                            python sync_nelida.py")
    print("  Verificar al final:       python revisar_estado.py")
    print(SEP)
