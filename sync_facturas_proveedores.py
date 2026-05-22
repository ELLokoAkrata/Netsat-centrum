"""
sync_facturas_proveedores.py
Parsea los XMLs de facturas de proveedores desde Z: y los sube a Supabase.
Luego intenta matching automático con ítems de OCs de Antapaccay.

Uso:
    python sync_facturas_proveedores.py              # sincroniza + matchea
    python sync_facturas_proveedores.py --dry-run    # solo muestra, sin cambios
    python sync_facturas_proveedores.py --solo-match # re-corre solo el matching
"""

import os
import re
import sys
import argparse
import xml.etree.ElementTree as ET
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
# Rutas y constantes
# ---------------------------------------------------------------------------
BASE_DIR = Path(r"Z:\NETSAT\NETSAT 2026\FACTURAS DE PROVEEDORES 2026")

MESES_CARPETAS = {
    "ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4,
    "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
    "SEPTIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12,
}

# Namespaces UBL (SUNAT)
NS = {
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
}

# ---------------------------------------------------------------------------
# Parser XML
# ---------------------------------------------------------------------------
def _texto(elem, path):
    """Devuelve el texto de un subelemento o None si no existe."""
    node = elem.find(path, NS)
    return node.text.strip() if node is not None and node.text else None


def parsear_xml(filepath: Path, mes: str) -> dict | None:
    """
    Parsea un XML de factura electrónica SUNAT (formato UBL 2.1).
    Devuelve dict con cabecera + lista de ítems, o None si falla.
    """
    try:
        tree = ET.parse(filepath)
        root = tree.getroot()

        # Solo procesar facturas (Invoice), no notas de crédito u otros
        tag_local = root.tag.split("}")[-1] if "}" in root.tag else root.tag
        if tag_local not in ("Invoice",):
            return None

        # RUC y nombre del proveedor
        ruc = _texto(root, ".//cac:AccountingSupplierParty/cac:Party/cac:PartyIdentification/cbc:ID")
        nombre = (
            _texto(root, ".//cac:AccountingSupplierParty/cac:Party/cac:PartyLegalEntity/cbc:RegistrationName")
            or _texto(root, ".//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name")
        )
        if not ruc:
            return None

        nro_factura = _texto(root, ".//cbc:ID")
        fecha_str   = _texto(root, ".//cbc:IssueDate")
        moneda      = _texto(root, ".//cbc:DocumentCurrencyCode")
        total_str   = _texto(root, ".//cac:LegalMonetaryTotal/cbc:PayableAmount")
        oc_ref      = _texto(root, ".//cac:OrderReference/cbc:ID")

        fecha = None
        if fecha_str:
            try:
                fecha = datetime.strptime(fecha_str, "%Y-%m-%d").date().isoformat()
            except ValueError:
                pass

        total = None
        if total_str:
            try:
                total = float(total_str)
            except ValueError:
                pass

        # Ítems
        items = []
        for i, line in enumerate(root.findall(".//cac:InvoiceLine", NS), start=1):
            desc        = _texto(line, ".//cac:Item/cbc:Description")
            seller_code = _texto(line, ".//cac:Item/cac:SellersItemIdentification/cbc:ID")
            qty_str     = _texto(line, "cbc:InvoicedQuantity")
            price_str   = _texto(line, ".//cac:Price/cbc:PriceAmount")
            total_l_str = _texto(line, "cbc:LineExtensionAmount")

            qty     = float(qty_str)     if qty_str     else None
            price   = float(price_str)   if price_str   else None
            total_l = float(total_l_str) if total_l_str else None

            items.append({
                "linea":           i,
                "descripcion":     desc,
                "cantidad":        qty,
                "precio_unitario": price,
                "total_linea":     total_l,
                "seller_code":     seller_code,
            })

        # Determinar mes desde carpeta
        mes_num = MESES_CARPETAS.get(mes.upper(), 0)

        return {
            "ruc_proveedor":    ruc,
            "nombre_proveedor": nombre,
            "nro_factura":      nro_factura,
            "fecha":            fecha,
            "moneda":           moneda,
            "total":            total,
            "oc_ref_interna":   oc_ref,
            "mes":              mes,
            "anio":             2026,
            "archivo_xml":      filepath.name,
            "items":            items,
        }

    except Exception as e:
        print(f"    AVISO: no se pudo parsear {filepath.name}: {e}")
        return None


# ---------------------------------------------------------------------------
# Escaneo del sistema de archivos
# ---------------------------------------------------------------------------
def escanear_xmls() -> list[dict]:
    print("\n[1/3] Escaneando XMLs en Z:...")

    if not BASE_DIR.exists():
        print(f"  ERROR: directorio no encontrado: {BASE_DIR}")
        sys.exit(1)

    facturas = []
    for carpeta in sorted(BASE_DIR.iterdir()):
        if not carpeta.is_dir():
            continue

        # Detectar mes desde nombre de carpeta (ej. "PROVEEDORES ENERO 2026")
        mes = None
        for nombre_mes in MESES_CARPETAS:
            if nombre_mes in carpeta.name.upper():
                mes = nombre_mes
                break
        if not mes:
            continue

        xmls = [f for f in carpeta.iterdir()
                if f.suffix.lower() == ".xml" and not f.name.startswith("CDR")]

        for xml_path in sorted(xmls):
            parsed = parsear_xml(xml_path, mes)
            if parsed:
                facturas.append(parsed)

    print(f"  {len(facturas)} facturas parseadas de XMLs")
    return facturas


# ---------------------------------------------------------------------------
# Carga a Supabase
# ---------------------------------------------------------------------------
def cargar_conocidos() -> set[str]:
    """Devuelve set de archivo_xml ya en Supabase."""
    r = supabase.table("facturas_proveedores").select("archivo_xml").execute()
    return {row["archivo_xml"] for row in r.data}


def subir_facturas(facturas: list[dict], conocidos: set[str], dry_run: bool):
    nuevas = [f for f in facturas if f["archivo_xml"] not in conocidos]

    print(f"\n[2/3] Sincronizando facturas...")
    print(f"  Ya en Supabase: {len(conocidos)}")
    print(f"  Parseadas:      {len(facturas)}")
    print(f"  Nuevas a subir: {len(nuevas)}")

    if not nuevas:
        print("  Todo al día — no hay facturas nuevas.")
        return

    if dry_run:
        for f in nuevas:
            print(f"  [DRY-RUN] {f['nombre_proveedor'] or f['ruc_proveedor']:35s} | "
                  f"{f['nro_factura']:15s} | {f['fecha'] or '?':10s} | "
                  f"{f['moneda'] or '?'} {f['total'] or 0:>10.2f} | "
                  f"items={len(f['items'])} | oc_ref={f['oc_ref_interna'] or '-'}")
        print(f"\n  Nada subido (dry-run).")
        return

    ok = err = 0
    for f in nuevas:
        try:
            cabecera = {k: v for k, v in f.items() if k != "items"}
            res = supabase.table("facturas_proveedores").upsert(
                cabecera, on_conflict="archivo_xml"
            ).execute()
            factura_id = res.data[0]["id"]

            for item in f["items"]:
                supabase.table("facturas_proveedores_items").insert({
                    **item, "factura_id": factura_id
                }).execute()

            print(f"  OK  {f['nombre_proveedor'] or f['ruc_proveedor']:35s} | {f['nro_factura']}")
            ok += 1
        except Exception as e:
            print(f"  ERR {f['nro_factura']}: {e}")
            err += 1

    print(f"\n  Resultado: {ok} subidas, {err} errores")


# ---------------------------------------------------------------------------
# Matching automático OC ↔ Factura proveedor
# ---------------------------------------------------------------------------

# Extrae tokens candidatos de una descripción para matching
_TOKEN_RE = re.compile(r'[A-Z0-9][A-Z0-9\-]{3,}', re.IGNORECASE)
_PTNO_RE  = re.compile(r'PTNO:\s*([A-Z0-9][A-Z0-9\-]{3,})', re.IGNORECASE)


def _tokens(texto: str) -> set[str]:
    """Extrae códigos de modelo/part number de una descripción."""
    if not texto:
        return set()
    tokens = set()
    # Prioridad 1: PTNO: explícito en OC de Antapaccay
    for m in _PTNO_RE.finditer(texto):
        tokens.add(m.group(1).upper())
    # Prioridad 2: secuencias alfanuméricas largas (part numbers)
    for tok in _TOKEN_RE.findall(texto):
        if len(tok) >= 5:
            tokens.add(tok.upper())
    return tokens


def _confianza_match(oc_tokens: set, item_tokens: set) -> str | None:
    """
    Devuelve 'AUTO_ALTA' si hay intersección en tokens clave,
    'AUTO_BAJA' si solo hay coincidencia parcial, None si no hay match.
    """
    if not oc_tokens or not item_tokens:
        return None
    interseccion = oc_tokens & item_tokens
    if not interseccion:
        return None
    # Alta confianza: token ≥7 chars Y contiene al menos un dígito
    # (part numbers reales siempre tienen dígito; palabras genéricas como BATERIA no)
    if any(len(t) >= 7 and any(c.isdigit() for c in t) for t in interseccion):
        return "AUTO_ALTA"
    return "AUTO_BAJA"


def ejecutar_matching(dry_run: bool):
    print("\n[3/3] Matching automatico OC <-> Facturas proveedores...")

    # Cargar ítems de OC desde Supabase
    oc_items = supabase.table("ocs").select(
        "codigo_oc, item, descripcion, codigo_material"
    ).execute().data
    print(f"  OC ítems cargados: {len(oc_items)}")

    # Cargar ítems de facturas proveedores
    fp_items = supabase.table("facturas_proveedores_items").select(
        "id, factura_id, descripcion, seller_code"
    ).execute().data
    print(f"  Factura ítems cargados: {len(fp_items)}")

    # Cargar matches ya existentes para no duplicar
    existentes = supabase.table("oc_compras_link").select(
        "codigo_oc, item, factura_id"
    ).execute().data
    existentes_set = {(r["codigo_oc"], r["item"], r["factura_id"]) for r in existentes}

    # Precalcular tokens de factura ítems
    fp_tokens = []
    for fi in fp_items:
        desc = (fi["descripcion"] or "") + " " + (fi["seller_code"] or "")
        fp_tokens.append((fi, _tokens(desc)))

    matches_alta = 0
    matches_baja = 0
    nuevos_links = []

    for oc in oc_items:
        oc_tok = _tokens(oc["descripcion"] or "")
        if not oc_tok:
            continue

        for fi, fi_tok in fp_tokens:
            confianza = _confianza_match(oc_tok, fi_tok)
            if not confianza:
                continue

            key = (oc["codigo_oc"], oc["item"], fi["factura_id"])
            if key in existentes_set:
                continue

            nuevos_links.append({
                "codigo_oc":       oc["codigo_oc"],
                "item":            oc["item"],
                "factura_id":      fi["factura_id"],
                "factura_item_id": fi["id"],
                "confianza":       confianza,
                "notas":           None,
            })
            existentes_set.add(key)

            if confianza == "AUTO_ALTA":
                matches_alta += 1
            else:
                matches_baja += 1

    print(f"  Matches nuevos: {matches_alta} alta confianza, {matches_baja} baja confianza")

    if not nuevos_links:
        print("  Sin nuevos matches.")
        return

    if dry_run:
        # Mostrar solo los de alta confianza
        altos = [l for l in nuevos_links if l["confianza"] == "AUTO_ALTA"]
        print(f"\n  [DRY-RUN] Matches alta confianza ({len(altos)}):")
        for link in altos:
            fi_desc = next(
                (fi["descripcion"] for fi, _ in fp_tokens if fi["id"] == link["factura_item_id"]),
                "?"
            )
            oc_desc = next(
                (o["descripcion"] for o in oc_items
                 if o["codigo_oc"] == link["codigo_oc"] and o["item"] == link["item"]),
                "?"
            )
            print(f"    {link['codigo_oc']} item {link['item']:2d}  <->  factura_item {link['factura_item_id']}")
            print(f"      OC:  {(oc_desc or '')[:70]}")
            print(f"      FAC: {(fi_desc or '')[:70]}")
        print(f"\n  Nada guardado (dry-run).")
        return

    # Guardar en Supabase (en lotes de 50)
    guardados = err = 0
    for i in range(0, len(nuevos_links), 50):
        lote = nuevos_links[i:i+50]
        try:
            supabase.table("oc_compras_link").upsert(
                lote, on_conflict="codigo_oc,item,factura_id"
            ).execute()
            guardados += len(lote)
        except Exception as e:
            print(f"  ERR lote {i}: {e}")
            err += len(lote)

    print(f"  Links guardados: {guardados}, errores: {err}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",     action="store_true", help="Solo muestra, sin cambios")
    parser.add_argument("--solo-match",  action="store_true", help="Solo re-corre el matching, sin subir XMLs")
    args = parser.parse_args()

    print("=" * 60)
    print("NETSAT - Sync Facturas Proveedores + Matching OCs")
    if args.dry_run:
        print("  MODO: dry-run (solo revisión, sin cambios)")
    print(f"Inicio: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if not args.solo_match:
        facturas  = escanear_xmls()
        conocidos = cargar_conocidos()
        subir_facturas(facturas, conocidos, dry_run=args.dry_run)

    ejecutar_matching(dry_run=args.dry_run)

    print()
    print(f"Fin: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)
