"""
sync_ocs.py
Detecta carpetas de OC nuevas en Z:.../ANTAPACCAY 2026/ y las sube a Supabase.
Por cada carpeta nueva: registra en tabla `ocs`, sube el PDF a Storage y lo registra en `archivos`.

Uso:
    python sync_ocs.py            # sincroniza
    python sync_ocs.py --dry-run  # solo muestra que subiria, sin subir
"""

import os
import re
import sys
import argparse
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
OC_DIR = Path(r"Z:\NETSAT\NETSAT 2026\ORDENES DE COMPRA 2026\OC CLIENTES 2026\ANTAPACCAY 2026")
BUCKET  = "documentos"

OC_RE = re.compile(r"OC_(C\d+)", re.IGNORECASE)

MESES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL",
    5: "MAYO",  6: "JUNIO",   7: "JULIO", 8: "AGOSTO",
    9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE"
}

def _codigo_oc(nombre_carpeta: str) -> str | None:
    m = OC_RE.search(nombre_carpeta)
    return m.group(1) if m else None

def _descripcion(nombre_carpeta: str) -> str | None:
    """Extrae la descripcion que viene despues del codigo OC en el nombre de carpeta."""
    m = OC_RE.search(nombre_carpeta)
    if not m:
        return None
    resto = nombre_carpeta[m.end():].strip(" -_")
    return resto if resto else None

# ---------------------------------------------------------------------------
# Paso 1: leer PDFs de OC ya subidos a Storage (via tabla archivos)
# ---------------------------------------------------------------------------
def cargar_conocidos() -> set[str]:
    print("\n[1/3] Consultando Supabase...")
    r = supabase.table("archivos").select("storage_path").eq("tipo", "OC").execute()
    # Extraer codigo_oc del storage_path: "ocs/antapaccay/C004248376/..."
    conocidos = set()
    for row in r.data:
        partes = row["storage_path"].split("/")
        if len(partes) >= 3:
            conocidos.add(partes[2])  # el codigo_oc esta en la tercera parte
    print(f"  {len(conocidos)} OCs con PDF ya subido en Supabase")
    return conocidos

# ---------------------------------------------------------------------------
# Paso 2: escanear carpetas en Z:
# ---------------------------------------------------------------------------
def escanear_local() -> list[dict]:
    print("\n[2/3] Escaneando carpetas de OC en Z:...")

    if not OC_DIR.exists():
        print(f"  ERROR: directorio no encontrado: {OC_DIR}")
        sys.exit(1)

    encontrados = []
    for carpeta in sorted(OC_DIR.iterdir()):
        if not carpeta.is_dir():
            continue

        codigo = _codigo_oc(carpeta.name)
        if not codigo:
            print(f"  AVISO: no se pudo extraer OC de '{carpeta.name}' — se omite")
            continue

        # Buscar el PDF dentro de la carpeta (mismo nombre que la carpeta)
        pdf = carpeta / f"{carpeta.name}.pdf"
        if not pdf.exists():
            # Buscar cualquier PDF dentro como fallback
            pdfs = list(carpeta.glob("*.pdf"))
            pdf = pdfs[0] if pdfs else None

        mes_nombre = MESES.get(datetime.fromtimestamp(carpeta.stat().st_mtime).month, "DESCONOCIDO")

        encontrados.append({
            "codigo_oc":    codigo,
            "descripcion":  _descripcion(carpeta.name),
            "carpeta":      carpeta,
            "carpeta_nombre": carpeta.name,
            "pdf":          pdf,
            "storage_path": f"ocs/antapaccay/{codigo}/{pdf.name}" if pdf else None,
            "mes":          mes_nombre,
        })

    print(f"  {len(encontrados)} carpetas de OC encontradas en Z:")
    return encontrados

# ---------------------------------------------------------------------------
# Paso 3: subir las nuevas
# ---------------------------------------------------------------------------
def subir_oc(item: dict) -> bool:
    try:
        if not item["pdf"] or not item["storage_path"]:
            print(f"    AVISO: {item['codigo_oc']} no tiene PDF — se omite")
            return False

        with open(item["pdf"], "rb") as f:
            data = f.read()

        supabase.storage.from_(BUCKET).upload(
            path=item["storage_path"],
            file=data,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )
        supabase.table("archivos").upsert({
            "nombre":       item["pdf"].name,
            "bucket":       BUCKET,
            "storage_path": item["storage_path"],
            "tipo":         "OC",
            "mes":          item["mes"],
            "anio":         2026,
            "subido_por":   "sync_ocs.py",
        }, on_conflict="storage_path").execute()

        return True

    except Exception as e:
        print(f"    ERROR: {e}")
        return False

def actualizar_mes(encontrados: list[dict]):
    """Upserta el campo mes para todos los items encontrados (incluyendo los ya conocidos)."""
    print("\n[+] Actualizando campo 'mes' en registros existentes...")
    ok = 0
    for item in encontrados:
        if not item["storage_path"]:
            continue
        try:
            supabase.table("archivos").upsert({
                "storage_path": item["storage_path"],
                "mes":          item["mes"],
                "nombre":       item["pdf"].name,
                "bucket":       BUCKET,
                "tipo":         "OC",
                "anio":         2026,
                "subido_por":   "sync_ocs.py",
            }, on_conflict="storage_path").execute()
            ok += 1
        except Exception as e:
            print(f"    ERROR actualizando {item['codigo_oc']}: {e}")
    print(f"  {ok} registros actualizados con campo 'mes'")


def sincronizar(conocidos: set[str], encontrados: list[dict], dry_run: bool = False):
    nuevos = [i for i in encontrados if i["codigo_oc"] not in conocidos]

    label = "[3/3] Revisando (dry-run)" if dry_run else "[3/3] Sincronizando..."
    print(f"\n{label}")
    print(f"  Ya en Supabase:  {len(conocidos)}")
    print(f"  En Z::           {len(encontrados)}")
    print(f"  Nuevas a subir:  {len(nuevos)}")

    if not nuevos:
        print("\n  Todo al dia — no hay OCs nuevas.")
        return

    print()
    if dry_run:
        for i in nuevos:
            pdf_info = i["pdf"].name if i["pdf"] else "SIN PDF"
            print(f"  [DRY-RUN] {i['codigo_oc']}  {i['descripcion'] or ''}  ({pdf_info})")
        print(f"\n  Nada subido (dry-run). Corre sin --dry-run para sincronizar.")
        return

    ok = 0
    err = 0
    for i in nuevos:
        pdf_info = i["pdf"].name if i["pdf"] else "sin PDF"
        print(f"  {i['codigo_oc']}  ({pdf_info}) ...", end=" ")
        if subir_oc(i):
            print("OK")
            ok += 1
        else:
            err += 1

    print(f"\n  Resultado: {ok} subidas, {err} errores")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra que subiria, sin subir")
    args = parser.parse_args()

    print("=" * 55)
    print("NETSAT - Sincronizacion de OCs Antapaccay a Supabase")
    if args.dry_run:
        print("  MODO: dry-run (solo revision, sin cambios)")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    conocidos   = cargar_conocidos()
    encontrados = escanear_local()
    if not args.dry_run:
        actualizar_mes(encontrados)
    sincronizar(conocidos, encontrados, dry_run=args.dry_run)

    print()
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)
