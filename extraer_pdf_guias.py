"""
extraer_pdf_guias.py
Descarga PDFs digitales de guías desde Supabase Storage, extrae metadatos
(fecha de emisión, fecha de traslado, OC) con pdfplumber y los guarda en
la tabla archivos.

Uso:
    python extraer_pdf_guias.py                  # procesa todos los pendientes
    python extraer_pdf_guias.py --guia T001-653  # procesa solo esa guía
    python extraer_pdf_guias.py --mes MAYO       # procesa un mes completo
    python extraer_pdf_guias.py --todos          # reprocesa aunque ya tenga datos
"""

import os
import sys
import re
import io
import argparse
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

BUCKET = "guias-digitales"

RE_FECHA_EMISION  = re.compile(r"Fecha\s+de\s+Emisi[oó]n[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
RE_FECHA_TRASLADO = re.compile(r"Fecha\s+del?\s+Traslado[:\s]+(\d{2}/\d{2}/\d{4})", re.IGNORECASE)
RE_OC             = re.compile(r"(?:Orden de Compra|N[°º]\s*O\.?C\.?)[^:]*[:\s]+(C\d{7,})", re.IGNORECASE)


def extraer_texto(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def parsear_fecha(texto: str, patron: re.Pattern) -> str | None:
    m = patron.search(texto)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def procesar_registro(row: dict) -> dict:
    guia  = row.get("guia_numero", "?")
    path  = row["storage_path"]

    try:
        data  = supabase.storage.from_(BUCKET).download(path)
        texto = extraer_texto(data)
    except Exception as e:
        print(f"  {guia}: ERROR al descargar — {e}")
        return {}

    fecha_emision  = parsear_fecha(texto, RE_FECHA_EMISION)
    fecha_traslado = parsear_fecha(texto, RE_FECHA_TRASLADO)
    m_oc           = RE_OC.search(texto)
    oc_extraida    = m_oc.group(1) if m_oc else None

    # Fallback: OC desde nombre del archivo (ej. "T001-630 ANTAPACCAY OC_C003948580.pdf")
    if not oc_extraida:
        m_oc2 = re.search(r"OC_(C\d+)", row.get("nombre", ""), re.IGNORECASE)
        if m_oc2:
            oc_extraida = m_oc2.group(1)

    estado = []
    if fecha_emision:  estado.append(f"emision={fecha_emision}")
    if fecha_traslado: estado.append(f"traslado={fecha_traslado}")
    if oc_extraida:    estado.append(f"oc={oc_extraida}")

    print(f"  {guia}: {', '.join(estado) if estado else 'sin datos'}")

    if not (fecha_emision or fecha_traslado or oc_extraida):
        return {}

    return {
        "storage_path":   path,
        "fecha_emision":  fecha_emision,
        "fecha_traslado": fecha_traslado,
        "oc_extraida":    oc_extraida,
    }


def cargar_pendientes(guia: str | None, mes: str | None, todos: bool) -> list[dict]:
    q = supabase.table("archivos").select("storage_path, nombre, guia_numero, mes")
    q = q.eq("bucket", BUCKET).eq("tipo", "PDF")

    if guia:
        q = q.eq("guia_numero", guia.upper())
    elif mes:
        q = q.eq("mes", mes.upper())
    elif not todos:
        q = q.is_("fecha_traslado", "null")

    r = q.order("guia_numero").execute()
    return r.data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--guia",  help="Procesar solo esta guía (ej: T001-653)")
    parser.add_argument("--mes",   help="Procesar solo este mes (ej: MAYO)")
    parser.add_argument("--todos", action="store_true", help="Reprocesar aunque ya tenga datos")
    args = parser.parse_args()

    print("=" * 55)
    print("NETSAT - Extracción de metadatos de PDFs de guías")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    registros = cargar_pendientes(args.guia, args.mes, args.todos)
    print(f"\n  {len(registros)} PDFs a procesar\n")

    if not registros:
        print("  Nada que procesar.")
        return

    actualizados = 0
    for row in registros:
        datos = procesar_registro(row)
        if datos:
            supabase.table("archivos").update({
                "fecha_emision":  datos["fecha_emision"],
                "fecha_traslado": datos["fecha_traslado"],
                "oc_extraida":    datos["oc_extraida"],
            }).eq("storage_path", datos["storage_path"]).execute()
            actualizados += 1

    print(f"\n  Resultado: {actualizados} de {len(registros)} actualizados")
    print(f"\nFin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)


if __name__ == "__main__":
    main()
