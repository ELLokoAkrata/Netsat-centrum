"""
sync_guias.py
Detecta PDFs nuevos en las carpetas de guias y los sube a Supabase.
Corre manualmente cuando se quiere sincronizar.

Uso:
    python sync_guias.py            # sincroniza
    python sync_guias.py --dry-run  # solo muestra que subiria, sin subir
"""

import os
import sys
import re
import io
import argparse
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from supabase import create_client, Client
import pdfplumber

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
Z_BASE = Path(r"Z:\NETSAT\NETSAT 2026\FACTURAS GUIAS NETSAT SRL 2026\GUIAS 2026")
LOCAL_BASE = Path(r"C:\Dev\Netsat-Centrum")

def _base() -> Path:
    if Z_BASE.exists():
        print("  Red Z: disponible — leyendo desde red")
        return Z_BASE
    print("  Red Z: no disponible — leyendo desde local")
    return LOCAL_BASE

# (subcarpeta_selladas, subcarpeta_digitales, mes)
GUIAS_FOLDERS = [
    ("GUIAS ENERO 2026/GUIAS SELLADAS 2026/GUIAS SELLADAS ENERO 26", "GUIAS ENERO 2026",   "ENERO"),
    ("GUIAS FEBRERO 2026/GUIAS SELLADAS FEBRERO 2026",               "GUIAS FEBRERO 2026", "FEBRERO"),
    ("GUIAS MARZO 2026/GUIAS SELLADAS MARZO 2026",                   "GUIAS MARZO 2026",   "MARZO"),
    ("GUIAS ABRIL 2026/GUIAS SELLADAS ABRIL 2026",                   "GUIAS ABRIL 2026",   "ABRIL"),
    ("GUIAS MAYO 2026/GUIAS SELLADAS MAYO 2026",                     "GUIAS MAYO 2026",    "MAYO"),
    ("GUIAS JUNIO 2026/GUIAS SELLADAS JUNIO 2026",                   "GUIAS JUNIO 2026",   "JUNIO"),
]

NUMERO_RE         = re.compile(r"T001-(\d+)", re.IGNORECASE)
RE_FECHA_EMISION  = re.compile(r"Fecha\s+de\s+Emisi[oó]n[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
RE_FECHA_TRASLADO = re.compile(r"Fecha\s+del?\s+Traslado[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
RE_OC_TEXTO       = re.compile(r"(?:Orden de Compra|N[°º]\s*O\.?C\.?)[^:]*[:\s]+(C\d{7,})", re.IGNORECASE)
RE_OC_NOMBRE      = re.compile(r"OC_(C\d+)", re.IGNORECASE)
RE_OC_SELLADA     = re.compile(r"(?:OC|CO)_(C\d+)", re.IGNORECASE)

def extraer_numero(nombre: str) -> str | None:
    m = NUMERO_RE.search(nombre)
    return f"T001-{m.group(1)}" if m else None

def _parsear_fecha(texto: str, patron: re.Pattern) -> str | None:
    m = patron.search(texto)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None

def extraer_metadata_pdf(data: bytes, nombre: str) -> dict:
    """Extrae fecha_emision, fecha_traslado y oc_extraida de un PDF digital."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
    except Exception:
        return {}

    oc = None
    m_oc = RE_OC_TEXTO.search(texto)
    if m_oc:
        oc = m_oc.group(1)
    else:
        m_oc2 = RE_OC_NOMBRE.search(nombre)
        if m_oc2:
            oc = m_oc2.group(1)

    return {
        "fecha_emision":  _parsear_fecha(texto, RE_FECHA_EMISION),
        "fecha_traslado": _parsear_fecha(texto, RE_FECHA_TRASLADO),
        "oc_extraida":    oc,
    }

# ---------------------------------------------------------------------------
# Paso 1: leer lo que ya esta en Supabase
# ---------------------------------------------------------------------------
def cargar_conocidos() -> set[str]:
    print("\n[1/3] Consultando Supabase...")
    r = supabase.table("archivos").select("storage_path").execute()
    conocidos = {row["storage_path"] for row in r.data}
    print(f"  {len(conocidos)} archivos ya registrados en Supabase")
    return conocidos

# ---------------------------------------------------------------------------
# Paso 2: escanear carpetas locales/red
# ---------------------------------------------------------------------------
def escanear_local(base: Path) -> list[dict]:
    print("\n[2/3] Escaneando carpetas de guias...")
    encontrados = []

    for sub_selladas, sub_digitales, mes in GUIAS_FOLDERS:
        for sub, bucket, tipo in [
            (sub_selladas,  "guias-selladas",  "sellada"),
            (sub_digitales, "guias-digitales", "digital"),
        ]:
            carpeta = base / sub
            if not carpeta.exists():
                print(f"  -- {mes} [{tipo}]: carpeta no encontrada, se omite")
                continue

            pdfs = sorted(p for p in carpeta.iterdir() if p.suffix.lower() == ".pdf")
            if pdfs:
                print(f"  {mes} [{tipo}]: {len(pdfs)} PDFs")
            for pdf in pdfs:
                storage_path = f"{mes}/{tipo}/{pdf.name}"
                encontrados.append({
                    "ruta":         pdf,
                    "nombre":       pdf.name,
                    "bucket":       bucket,
                    "storage_path": storage_path,
                    "mes":          mes,
                    "tipo":         tipo,
                    "guia_numero":  extraer_numero(pdf.name),
                })

    print(f"\n  Total PDFs encontrados localmente: {len(encontrados)}")
    return encontrados

# ---------------------------------------------------------------------------
# Paso 3: subir los nuevos
# ---------------------------------------------------------------------------
def subir_nuevo(item: dict) -> bool:
    try:
        with open(item["ruta"], "rb") as f:
            data = f.read()

        supabase.storage.from_(item["bucket"]).upload(
            path=item["storage_path"],
            file=data,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )

        registro = {
            "nombre":       item["nombre"],
            "bucket":       item["bucket"],
            "storage_path": item["storage_path"],
            "tipo":         "PDF",
            "mes":          item["mes"],
            "anio":         2026,
            "guia_numero":  item["guia_numero"],
            "subido_por":   "sync_guias.py",
        }

        if item["tipo"] == "digital":
            registro.update(extraer_metadata_pdf(data, item["nombre"]))
        else:
            m_s = RE_OC_SELLADA.search(item["nombre"])
            if m_s:
                registro["oc_extraida"] = m_s.group(1)

        supabase.table("archivos").upsert(registro, on_conflict="storage_path").execute()
        return True

    except Exception as e:
        print(f"    ERROR al subir {item['nombre']}: {e}")
        return False

def sincronizar(conocidos: set[str], encontrados: list[dict], dry_run: bool = False):
    nuevos = [item for item in encontrados if item["storage_path"] not in conocidos]

    label = "[3/3] Revisando (dry-run)" if dry_run else "[3/3] Sincronizando..."
    print(f"\n{label}")
    print(f"  Ya en Supabase:  {len(conocidos)}")
    print(f"  Encontrados:     {len(encontrados)}")
    print(f"  Nuevos a subir:  {len(nuevos)}")

    if not nuevos:
        print("\n  Todo al dia — no hay PDFs nuevos.")
        return

    print()
    if dry_run:
        for item in nuevos:
            print(f"  [DRY-RUN] {item['mes']} [{item['tipo']}] {item['nombre']}")
        print(f"\n  Nada subido (dry-run). Corre sin --dry-run para sincronizar.")
        return

    ok = 0
    err = 0
    for item in nuevos:
        print(f"  Subiendo {item['mes']} [{item['tipo']}] {item['nombre']} ...", end=" ")
        if subir_nuevo(item):
            print("OK")
            ok += 1
        else:
            err += 1

    print(f"\n  Resultado: {ok} subidos, {err} errores")

    if ok > 0:
        try:
            supabase.rpc("actualizar_estado_ocs").execute()
            print("  Estado de OCs actualizado.")
        except Exception as e:
            print(f"  AVISO: no se pudo actualizar estado de OCs: {e}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra que subiria, sin subir")
    args = parser.parse_args()

    print("=" * 55)
    print("NETSAT - Sincronizacion de guias a Supabase")
    if args.dry_run:
        print("  MODO: dry-run (solo revision, sin cambios)")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    base = _base()
    conocidos   = cargar_conocidos()
    encontrados = escanear_local(base)
    sincronizar(conocidos, encontrados, dry_run=args.dry_run)

    print()
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)
