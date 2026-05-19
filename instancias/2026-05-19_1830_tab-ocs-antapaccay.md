# Instrucciones para instancia — Tab OCs Antapaccay
**Fecha:** 2026-05-19 18:30  
**Preparado por:** Claude (instancia principal)  
**Directorio de trabajo:** `C:\Dev\Netsat-Centrum\`

---

## Contexto del proyecto

Netsat Centrum es una aplicación Streamlit desplegada en Streamlit Community Cloud.  
Stack: Python + Streamlit + Supabase (PostgreSQL + Storage).

**Archivos principales:**
- `app.py` — aplicación unificada con 5 pestañas. **Único archivo de la app que se debe modificar.**
- `sync_ocs.py` — script de sincronización de OCs. También se debe modificar.
- `.env` — credenciales locales (clave de servicio de Supabase). No leer ni mostrar su contenido.

**Supabase:**
- URL: `https://knkuyxjimwpquhzgxsro.supabase.co`
- Tablas relevantes: `archivos`, `ocs`
- Bucket relevante: `documentos`

---

## Estado actual — lo que ya existe

### Pestaña OCs actual (a reemplazar)

El bloque `with tab_ocs:` en `app.py` (aproximadamente líneas 272–307) muestra un simple
dataframe de la tabla `ocs` con dos campos de búsqueda (código y descripción).
**Este bloque debe eliminarse por completo y sustituirse** por la implementación descrita
en la Tarea 2. No se conserva ninguna parte del código actual del tab.

### Tabla `archivos` (96 filas de tipo OC)

Cada OC tiene un PDF subido al bucket `documentos`. Columnas relevantes:

| columna | valor de ejemplo |
|---------|-----------------|
| `storage_path` | `ocs/antapaccay/C004248376/ANTAPACCAY OC_C004248376.pdf` |
| `nombre` | `ANTAPACCAY OC_C004248376.pdf` |
| `bucket` | `documentos` |
| `tipo` | `OC` |
| `anio` | `2026` |
| `mes` | `null` ← **falta; la Tarea 1 lo poblará** |

### Tabla `ocs` (31 filas — datos del Excel del padre)

Contiene el detalle de ítems por OC. Solo 31 de las 96 OCs tienen datos aquí.

| columna | descripción |
|---------|-------------|
| `codigo_oc` | `C004248376` |
| `item` | número de ítem dentro de la OC |
| `descripcion` | descripción del producto |
| `cantidad` | cantidad |
| `venta_unit_usd` | precio unitario en USD |
| `venta_total_usd` | total en USD |
| `observaciones` | texto libre |

---

## Tareas — ejecutar en este orden

---

### TAREA 1 — Agregar campo `mes` a `sync_ocs.py`

Actualmente `sync_ocs.py` no captura el mes de cada carpeta de OC. Se debe derivar
de la fecha de modificación de la carpeta en Z:.

**Modificación en `sync_ocs.py`:**

Al inicio del archivo, agregar el mapeo de meses:

```python
MESES = {
    1: "ENERO", 2: "FEBRERO", 3: "MARZO", 4: "ABRIL",
    5: "MAYO",  6: "JUNIO",   7: "JULIO", 8: "AGOSTO",
    9: "SEPTIEMBRE", 10: "OCTUBRE", 11: "NOVIEMBRE", 12: "DICIEMBRE"
}
```

En la función `escanear_local()`, dentro del loop que construye el dict de cada carpeta,
agregar la derivación del mes:

```python
from datetime import datetime
mes_nombre = MESES.get(datetime.fromtimestamp(carpeta.stat().st_mtime).month, "DESCONOCIDO")
```

Y agregar `"mes": mes_nombre` al dict del ítem encontrado.

En la función `subir_oc()`, agregar `"mes": item["mes"]` al dict del upsert en `archivos`:

```python
supabase.table("archivos").upsert({
    "nombre":       item["pdf"].name,
    "bucket":       BUCKET,
    "storage_path": item["storage_path"],
    "tipo":         "OC",
    "mes":          item["mes"],   # ← línea nueva
    "anio":         2026,
    "subido_por":   "sync_ocs.py",
}, on_conflict="storage_path").execute()
```

**Ejecutar para actualizar los 96 registros existentes:**
```
py sync_ocs.py
```
El upsert sobre `storage_path` actualizará el campo `mes` sin duplicar registros.

**Verificar:**
```
py revisar_estado.py
```
Las OCs deben seguir en delta 0.

---

### TAREA 2 — Reconstruir la pestaña OCs en `app.py`

Localizar el bloque `with tab_ocs:` (aproximadamente líneas 272–307) y **eliminarlo por
completo**. En su lugar, insertar el siguiente bloque:

#### Diseño de la pestaña

**Sección superior — filtros y descarga de PDFs:**
- Filtro **Mes** (selectbox) — valores únicos del campo `mes` en `archivos` donde `tipo='OC'`
- Filtro **Buscar** (text_input) — busca en nombre del archivo o código OC
- Botón **"Descargar mes como ZIP"** — mismo patrón de dos pasos que la pestaña Guías
- Expander **"Ver archivos individuales (N)"** — lista con botón de descarga por fila

**Sección inferior — ítems del producto:**
- Separador (`st.divider()`)
- Subheader: "Ítems de la OC"
- Selectbox para elegir una OC del mes filtrado
- Si tiene datos en tabla `ocs`: tabla con columnas `item, descripcion, cantidad, venta_unit_usd, venta_total_usd, observaciones`
- Si no tiene datos: mensaje informativo (ver código)

#### Código completo del bloque

```python
# ============================================================
# TAB 3: OCs Antapaccay
# ============================================================
with tab_ocs:
    st.header("OCs Antapaccay 2026")

    @st.cache_data(ttl=300)
    def cargar_ocs_archivos():
        r = (supabase.table("archivos")
             .select("*")
             .eq("tipo", "OC")
             .order("nombre")
             .execute())
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()

    @st.cache_data(ttl=300)
    def cargar_ocs_items():
        r = (supabase.table("ocs")
             .select("*")
             .order("codigo_oc")
             .order("item")
             .execute())
        return pd.DataFrame(r.data) if r.data else pd.DataFrame()

    if st.button("Recargar datos", key="reload_ocs"):
        cargar_ocs_archivos.clear()
        cargar_ocs_items.clear()
        st.rerun()

    df_arch_oc = cargar_ocs_archivos()

    if df_arch_oc.empty:
        st.info("No hay OCs cargadas. Ejecutar sync_ocs.py.")
    else:
        # ── Filtros ──────────────────────────────────────────
        col1, col2 = st.columns([1, 2])
        with col1:
            meses_oc = sorted(df_arch_oc["mes"].dropna().unique().tolist())
            f_mes = st.selectbox("Mes", meses_oc, index=len(meses_oc) - 1, key="oc_mes")
        with col2:
            f_buscar = st.text_input("Buscar (código OC o nombre de archivo)", key="oc_buscar")

        df_f = df_arch_oc[df_arch_oc["mes"] == f_mes].copy()
        if f_buscar:
            df_f = df_f[df_f["nombre"].str.contains(f_buscar, case=False, na=False)]

        # Extraer código OC del storage_path: "ocs/antapaccay/C004248376/..."
        def _codigo_de_path(path: str) -> str:
            partes = str(path).split("/")
            return partes[2] if len(partes) >= 3 else ""

        df_f["codigo_oc"] = df_f["storage_path"].apply(_codigo_de_path)

        st.caption(f"{len(df_f)} OCs en {f_mes}")

        # ── Descarga ZIP ──────────────────────────────────────
        zip_key = f"zip_ocs_{f_mes}"
        if zip_key in st.session_state:
            def _limpiar_zip_oc():
                st.session_state.pop(zip_key, None)
            st.download_button(
                label="💾 Guardar ZIP",
                data=st.session_state[zip_key],
                file_name=f"OCs_Antapaccay_{f_mes}.zip",
                mime="application/zip",
                key=f"dl_{zip_key}",
                on_click=_limpiar_zip_oc,
                use_container_width=True,
            )
        else:
            if st.button("📦 Descargar mes como ZIP", key=f"fetch_{zip_key}",
                         use_container_width=True, disabled=df_f.empty):
                buf = io.BytesIO()
                with st.spinner(f"Preparando {len(df_f)} archivos..."):
                    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                        for _, row in df_f.iterrows():
                            try:
                                data = supabase.storage.from_(row["bucket"]).download(row["storage_path"])
                                zf.writestr(row["nombre"], data)
                            except Exception:
                                pass
                buf.seek(0)
                st.session_state[zip_key] = buf.read()
                st.rerun()

        # ── Archivos individuales ─────────────────────────────
        with st.expander(f"Ver archivos individuales ({len(df_f)})"):
            h1, h2, h3 = st.columns([5, 2, 1])
            h1.markdown("**Archivo**")
            h2.markdown("**Código OC**")
            h3.markdown("**Acción**")
            st.divider()

            for _, row in df_f.iterrows():
                uid = str(row["id"])
                c1, c2, c3 = st.columns([5, 2, 1])
                with c1:
                    st.write(row["nombre"])
                with c2:
                    st.write(row["codigo_oc"])
                with c3:
                    boton_descarga(row["bucket"], row["storage_path"], row["nombre"], uid)

        # ── Ítems de la OC seleccionada ───────────────────────
        st.divider()
        st.subheader("Ítems de la OC")

        df_items = cargar_ocs_items()
        codigos_con_items = (df_items["codigo_oc"].unique().tolist()
                             if not df_items.empty else [])
        codigos_del_mes = sorted(df_f["codigo_oc"].tolist())

        if not codigos_del_mes:
            st.info("No hay OCs en el mes seleccionado.")
        else:
            oc_sel = st.selectbox(
                "Seleccionar OC para ver sus ítems",
                options=codigos_del_mes,
                key="oc_sel_items",
            )

            if oc_sel in codigos_con_items:
                df_det = df_items[df_items["codigo_oc"] == oc_sel]
                cols = [c for c in [
                    "item", "descripcion", "cantidad",
                    "venta_unit_usd", "venta_total_usd", "observaciones"
                ] if c in df_det.columns]
                total = pd.to_numeric(df_det["venta_total_usd"], errors="coerce").sum()
                st.caption(f"{len(df_det)} ítems · Total: ${total:,.2f} USD")
                st.dataframe(df_det[cols], width="stretch", hide_index=True)
            else:
                st.info(
                    f"La OC **{oc_sel}** no tiene ítems registrados. "
                    "Los datos de ítems provienen del Excel del padre "
                    "y están disponibles para 31 de las 96 OCs."
                )
```

---

### TAREA 3 — Verificación local

Ejecutar la aplicación localmente:

```
streamlit run app.py
```

**Lista de verificación:**

- [ ] La pestaña "OCs" muestra el selector de meses con los valores correctos (ENERO a MAYO)
- [ ] Al cambiar de mes, el contador de OCs se actualiza
- [ ] El botón "Descargar mes como ZIP" funciona en dos pasos: preparar → guardar
- [ ] El expander lista los archivos individuales con su botón de descarga
- [ ] Al seleccionar una OC con ítems (por ejemplo: C004078040), se muestra la tabla de productos
- [ ] Al seleccionar una OC sin ítems, se muestra el mensaje informativo
- [ ] El botón "Recargar datos" limpia la caché correctamente
- [ ] El resto de pestañas (Guías, Facturas, Control Nélida) no presenta regresiones

---

## Restricciones

- No modificar `sync_guias.py`, `sync_nelida.py` ni `revisar_estado.py`
- No modificar el Excel de Nélida (`CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx`)
- No leer el archivo `.env` ni `.streamlit/secrets.toml`
- `io` y `zipfile` ya están importados en `app.py` (líneas 9–10); no importarlos de nuevo
- La función `boton_descarga()` ya está definida en `app.py`; no duplicarla

---

## Resolución de problemas

| Síntoma | Causa probable | Solución |
|---------|---------------|----------|
| El selector de meses aparece vacío | Tarea 1 no completada | Ejecutar `py sync_ocs.py` tras modificarlo |
| Error al importar `io` o `zipfile` | Importación duplicada | Eliminar la importación duplicada |
| Las OCs no aparecen en el selector de ítems | Esperado — solo 31 de 96 tienen datos | No es un error |
| Duda sobre el estado del sistema | — | Ejecutar `py revisar_estado.py` |

---

## Referencias de estilo

El tab Guías (líneas 145–267 de `app.py`) es el modelo de referencia visual y funcional.
La pestaña OCs debe tener el mismo aspecto y comportamiento:
- Filtros en la parte superior en columnas
- ZIP primero, individuales en expander colapsado
- Tabla de datos debajo de un separador
- `width="stretch"` en todos los `st.dataframe()`
- `use_container_width=True` en botones de ancho completo
