"""
extraer_pdf_ocs.py
Descarga PDFs de OCs desde Supabase Storage, extrae ítems con pdfplumber
y los guarda en la tabla ocs.

Uso:
    python extraer_pdf_ocs.py                    # procesa OCs sin ítems
    python extraer_pdf_ocs.py --oc C004199390    # procesa solo esa OC
    python extraer_pdf_ocs.py --mes MAYO         # procesa un mes completo
    python extraer_pdf_ocs.py --todos            # reprocesa aunque ya tenga ítems
"""

import os
import sys
import re
import io
import argparse
from datetime import datetime
from collections import defaultdict

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

BUCKET = "documentos"

# Formato estándar COUPA: 18 dígitos de código de material pegados a la fecha
RE_ITEM_CORE = re.compile(
    r'(\d{18})'
    r'(\d{2}/\d{2}/\d{4})\s*'
    r'(\d+)\s*'
    r'(Unidad(?:es)?)\s*'
    r'([\d.]+,\d{2})\s*'
    r'([\d.]+,\d{2})',
    re.IGNORECASE
)

# Formato libre (OCs manuales sin código de material): descripción → fecha → cantidad
RE_ITEM_FALLBACK = re.compile(
    r'^(\d+)\s+'
    r'(.+?)\s*'
    r'(\d{2}/\d{2}/\d{4})\s*'
    r'(\d+)\s*'
    r'(Unidad(?:es)?)\s*'
    r'([\d.]+,\d{2})\s*'
    r'([\d.]+,\d{2})',
    re.IGNORECASE
)

RE_OC_HEADER   = re.compile(r'Orden de\s+(\w+)\s*Compra', re.IGNORECASE)
RE_FECHA_OC    = re.compile(r'Fecha de\s+(\d{2}\.\d{2}\.\d{4})\s+emisi', re.IGNORECASE)
RE_TOTAL       = re.compile(r'Valor Total\s+[\d.,]+\s+\w+\s+([\d.,]+)\s+USD', re.IGNORECASE)
RE_CU_FRAGMENT = re.compile(r'\s*\(CU-[\d]*\)?\s*', re.IGNORECASE)


def _parse_monto(s: str) -> float | None:
    try:
        return float(s.replace('.', '').replace(',', '.'))
    except (ValueError, AttributeError):
        return None


def _parse_fecha(s: str, fmt: str) -> str | None:
    try:
        return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def extraer_lineas_por_y(page) -> dict[int, str]:
    """Agrupa palabras por posición Y (redondeada a 5px) y devuelve líneas de texto."""
    words = page.extract_words()
    buckets = defaultdict(list)
    for w in words:
        y = round(w['top'] / 5) * 5
        buckets[y].append(w['text'])
    return {y: " ".join(words) for y, words in sorted(buckets.items())}


def parsear_pdf_oc(data: bytes) -> dict:
    """Extrae cabecera e ítems de un PDF de OC de Antapaccay/COUPA."""
    resultado = {"codigo_oc": None, "fecha_oc": None, "monto_total": None, "items": []}

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        texto_completo = []
        for page in pdf.pages:
            lineas = extraer_lineas_por_y(page)
            texto_completo.append(lineas)

    # Cabecera desde primera página
    primer_bloque = " ".join(texto_completo[0].values())
    m = RE_OC_HEADER.search(primer_bloque)
    if m:
        resultado["codigo_oc"] = m.group(1)
    m = RE_FECHA_OC.search(primer_bloque)
    if m:
        resultado["fecha_oc"] = _parse_fecha(m.group(1), "%d.%m.%Y")
    m = RE_TOTAL.search(primer_bloque)
    if m:
        resultado["monto_total"] = _parse_monto(m.group(1))

    # Ítems desde todas las páginas
    for lineas in texto_completo:
        for y, linea in lineas.items():
            m_start = re.match(r'^(\d+)\s+', linea)
            if not m_start:
                continue

            # Intentar formato estándar (con código de material 18 dígitos)
            m = RE_ITEM_CORE.search(linea)
            if m:
                cod_mat, fecha_ent, cantidad, unidad, precio_u, precio_t = m.groups()
                desc_raw = linea[len(m_start.group(0)):m.start()].strip()
                cod_material = cod_mat
            else:
                # Fallback: OCs manuales sin código de material
                m = RE_ITEM_FALLBACK.match(linea)
                if not m:
                    continue
                _, desc_raw, fecha_ent, cantidad, unidad, precio_u, precio_t = m.groups()
                cod_material = None

            desc = RE_CU_FRAGMENT.sub(" ", desc_raw).strip()
            resultado["items"].append({
                "item":             int(m_start.group(1)),
                "descripcion":      desc,
                "codigo_material":  cod_material,
                "fecha_entrega":    _parse_fecha(fecha_ent, "%d/%m/%Y"),
                "cantidad":         _parse_monto(cantidad),
                "unidad":           unidad,
                "venta_unit_usd":   _parse_monto(precio_u),
                "venta_total_usd":  _parse_monto(precio_t),
                "fuente":           "pdf",
            })

    return resultado


def procesar_oc(codigo_oc: str, storage_path: str) -> int:
    try:
        data = supabase.storage.from_(BUCKET).download(storage_path)
    except Exception as e:
        print(f"  {codigo_oc}: ERROR al descargar — {e}")
        return 0

    resultado = parsear_pdf_oc(data)

    if not resultado["items"]:
        print(f"  {codigo_oc}: sin ítems detectados")
        return 0

    # Actualizar cabecera si tenemos fecha o monto
    update_cab = {}
    if resultado["fecha_oc"]:
        update_cab["fecha_oc"] = resultado["fecha_oc"]
    if resultado["monto_total"]:
        update_cab["monto_total_usd"] = resultado["monto_total"]
    if update_cab:
        supabase.table("ocs_cabecera").update(update_cab).eq("codigo_oc", codigo_oc).execute()

    # Upsert ítems
    for item in resultado["items"]:
        supabase.table("ocs").upsert({
            "codigo_oc": codigo_oc,
            **item,
        }, on_conflict="codigo_oc,item").execute()

    n = len(resultado["items"])
    print(f"  {codigo_oc}: {n} ítem(s) — entrega {resultado['items'][0]['fecha_entrega'] or '?'}")
    return n


def cargar_ocs_pendientes(oc: str | None, mes: str | None, todos: bool) -> list[dict]:
    q = supabase.table("archivos").select("storage_path, nombre").eq("tipo", "OC")

    if oc:
        q = q.ilike("nombre", f"%{oc}%")
    elif mes:
        q = q.eq("mes", mes.upper())

    r = q.order("nombre").execute()
    archivos = r.data

    if not todos and not oc:
        # Solo OCs sin ítems en la tabla ocs
        r2 = supabase.table("ocs").select("codigo_oc").execute()
        con_items = {row["codigo_oc"] for row in r2.data}
        archivos = [a for a in archivos if _codigo_de_nombre(a["nombre"]) not in con_items]

    return archivos


def _codigo_de_nombre(nombre: str) -> str | None:
    m = re.search(r"(C\d{7,})", nombre)
    return m.group(1) if m else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--oc",    help="Procesar solo esta OC (ej: C004199390)")
    parser.add_argument("--mes",   help="Procesar solo este mes (ej: MAYO)")
    parser.add_argument("--todos", action="store_true", help="Reprocesar aunque ya tenga ítems")
    args = parser.parse_args()

    print("=" * 55)
    print("NETSAT - Extracción de ítems de PDFs de OCs")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)

    archivos = cargar_ocs_pendientes(args.oc, args.mes, args.todos)
    print(f"\n  {len(archivos)} OC(s) a procesar\n")

    if not archivos:
        print("  Nada que procesar.")
        return

    total_items = 0
    for a in archivos:
        codigo = _codigo_de_nombre(a["nombre"])
        if not codigo:
            print(f"  {a['nombre']}: no se pudo extraer código OC, se omite")
            continue
        total_items += procesar_oc(codigo, a["storage_path"])

    print(f"\n  Resultado: {total_items} ítems extraídos de {len(archivos)} OC(s)")
    print(f"\nFin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 55)


if __name__ == "__main__":
    main()
