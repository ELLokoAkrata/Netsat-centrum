"""
sync_guias.py
Detecta PDFs nuevos en las carpetas de guias y los sube a Supabase.
Corre manualmente cuando se quiere sincronizar.

Uso:
    python sync_guias.py
"""

import os
import sys
import re
from pathlib import Path
from datetime import datetime

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
Z_BASE = Path(r"Z:\NETSAT\NETSAT 2026\FACTURAS GUIAS NETSAT SRL 2026\GUIAS 2026")
LOCAL_BASE = Path(r"C:\Users\herru\OneDrive\Escritorio\Netsat-Centrum")

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

NUMERO_RE = re.compile(r"T001-(\d+)", re.IGNORECASE)

def extraer_numero(nombre: str) -> str | None:
    m = NUMERO_RE.search(nombre)
    return f"T001-{m.group(1)}" if m else None

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
        supabase.table("archivos").upsert({
            "nombre":       item["nombre"],
            "bucket":       item["bucket"],
            "storage_path": item["storage_path"],
            "tipo":         "PDF",
            "mes":          item["mes"],
            "anio":         2026,
            "guia_numero":  item["guia_numero"],
            "subido_por":   "sync_guias.py",
        }, on_conflict="storage_path").execute()
        return True

    except Exception as e:
        print(f"    ERROR al subir {item['nombre']}: {e}")
        return False

def sincronizar(conocidos: set[str], encontrados: list[dict]):
    nuevos = [item for item in encontrados if item["storage_path"] not in conocidos]

    print(f"\n[3/3] Sincronizando...")
    print(f"  Ya en Supabase:  {len(conocidos)}")
    print(f"  Encontrados:     {len(encontrados)}")
    print(f"  Nuevos a subir:  {len(nuevos)}")

    if not nuevos:
        print("\n  Todo al dia — no hay PDFs nuevos.")
        return

    print()
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

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 55)
    print("NETSAT - Sincronizacion de guias a Supabase")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    base = _base()
    conocidos  = cargar_conocidos()
    encontrados = escanear_local(base)
    sincronizar(conocidos, encontrados)

    print()
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)
