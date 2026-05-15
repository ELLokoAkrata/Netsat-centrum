# NETSAT — Contexto del proyecto

## Protocolo de sesión (OBLIGATORIO)

- **Al iniciar:** leer `HISTORIAL.md` antes de cualquier tarea. Confirmar explícitamente que se leyó y resumir el estado actual del proyecto.
- **Al cerrar:** escribir en `HISTORIAL.md` un resumen de todo lo que se hizo en la sesión — cambios en el código, decisiones de diseño, bugs resueltos, estado del cruce, etc.

## Agentes del proyecto

El proyecto opera con 4 agentes especializados. Claude debe identificar qué agente corresponde según el tipo de tarea y adoptarlo sin que el usuario tenga que pedirlo explícitamente. El usuario también puede invocarlos directamente con `@pm`, `@engineer`, `@analyst`, `@ux`.

| Agente | Alias | Cuándo activarlo |
|--------|-------|-----------------|
| **Product Manager** | `@pm` | Definir features, escribir specs, priorizar roadmap, traducir necesidades de Nélida/padre/Héctor en requisitos concretos, evaluar si una idea tiene sentido antes de construirla |
| **Software Engineer** | `@engineer` | Escribir código Python/Streamlit/SQL, arquitectura técnica, integración Supabase, auth, deploy, sync daemon, bugs, revisión de código |
| **Data Analyst** | `@analyst` | Diseñar lógica de cruces (facturas↔guías↔OCs), definir estructura de tablas en Supabase, calcular utilidades, decidir qué métricas mostrar y cómo agregarlas |
| **UX Designer** | `@ux` | Diseñar flujos de usuario, estructura de tabs, usabilidad para usuarios no técnicos (Nélida, padre), qué mostrar primero, cómo organizar la información |

### Reglas de activación

- Una misma tarea puede requerir varios agentes en secuencia — por ejemplo: `@pm` define el feature → `@analyst` diseña el modelo de datos → `@engineer` lo implementa.
- Si la tarea es ambigua, `@pm` siempre va primero para clarificar el alcance antes de tocar código.
- `@ux` se activa siempre que se diseñe una pantalla nueva o se reorganice una existente, incluso si la solicitud parece puramente técnica.
- No hay agente de seguridad dedicado: las consideraciones de seguridad (auth, URLs firmadas, secrets) son responsabilidad de `@engineer` en cada tarea.
- No hay agente de marketing: el proyecto es una herramienta interna para 4 usuarios.

---

## Red interna y usuarios

**Red doméstica/empresarial pequeña — 4 usuarios:**

| Usuario | Equipo | Rol |
|---------|--------|-----|
| Ricardo Junio (herru) | Laptop propia — accede al servidor vía **Google Remote Desktop** | Desarrollo, administración del proyecto |
| Héctor (tío) | `\\Pc-netsat` | Sube guías y documentos operativos |
| Ricardo (padre) | Laptop | Consulta, necesita descargar guías y reportes |
| Nélida (tía) | PC propia (o servidor) | Control manual en Excel — logística/administración |

**Problema central:** la información está **desperdigada** entre los 4 equipos. No hay base de datos — todo es Excel. El objetivo del proyecto es centralizar progresivamente en el servidor para que cualquiera pueda consultar y descargar lo que necesita desde la app Streamlit.

**Estado actual de los archivos:**
- Red montada como **Z:** en el servidor → `Z:\NETSAT\NETSAT 2026\` (340 carpetas, 2.875 archivos)
- Guías PDF: en `Z:\NETSAT\NETSAT 2026\FACTURAS GUIAS NETSAT SRL 2026\GUIAS 2026\` — Enero a Abril 2026
- OCs del padre: `Z:\NETSAT\NETSAT 2026\ORDENES DE COMPRA 2026\OC Antapaccay pendientes de atencion.xlsx` (creado por Ricardo, último guardado por Héctor — snapshot desactualizado)
- **Archivo clave de Nélida:** `C:\Users\herru\OneDrive\Escritorio\Drive-Compartido\CONTROL DE FACTURAS EMITIDAS NETSAT 2026-2025.xlsx` — el más completo del sistema, vincula facturas → guías → OCs → proyectos. Modificado diariamente.
- Control de despachos de Ricardo Junior (Hagemsa): `Z:\NETSAT\NETSAT 2026\ORDENES DE COMPRA 2026\DETALLES MERCADERIAS DESPACHADAS ADRIAN\` (18 archivos)

---

## La empresa

**NETSAT SRL** es una empresa peruana fundada en 2002, con sede en Callao, Lima.
Se especializa en diseño, comercialización e integración de sistemas de telecomunicaciones a nivel nacional.

**Servicios principales:**
- Radioenlaces RF (punto a punto y punto a multipunto) — Cambium, CommScope, Cisco, Juniper
- Radiocomunicaciones — Radios analógicas/digitales HF/VHF/UHF, Motorola Solutions
- Fibra óptica y redes — FTTH/GPON/EPON, cableado estructurado CAT 5E/6/6A
- Sistemas de energía — UPS, paneles solares, sistemas off-grid
- Suministros — Conectores, cables Heliax/LMR, importación directa desde Miami

**Marcas socias:** Motorola, Cisco, Cambium Networks, CommScope, Axis, Juniper y 20+ fabricantes.

**Contacto:** ventas@netsat.com.pe · +51 324 6463 · netsat.com.pe

---

## Este proyecto

Herramientas internas de gestión para NETSAT, construidas en Python + Streamlit.
El objetivo es unificar la información operativa de la empresa en una sola plataforma.

**Stack:** Python · Streamlit · pandas · openpyxl · pdfplumber · Supabase (Storage + PostgreSQL + Auth) · Streamlit Community Cloud

**Repositorio:** https://github.com/ELLokoAkrata/Netsat-centrum

---

## Estructura del repositorio

```
Netsat-centrum/
├── oc_antapaccay.py                        # Módulo 1: gestión de OC pendientes
├── guias_despacho.py                       # Módulo 2: control de despachos por guía
├── OC_Antapaccay.xlsx                      # Datos OC internas (compras, precios)
├── OrdenesActivacion 13-04-2026-editado.xlsx  # Órdenes oficiales del cliente Antapaccay
├── Orden de compra transito ALEXIM.xlsx    # OC en tránsito (proveedor ALEXIM)
├── OC_Antapaccay_BACKUP.xlsx              # Backup del Excel antes de limpieza
├── GUIAS MARZO 2026/                       # PDFs de guías de remisión — marzo
│   ├── 20505504781-09-T001-587.pdf ... T001-615.pdf
│   └── GUIAS SELLADAS MARZO 2026/          # Versiones selladas/firmadas
├── GUIAS ABRIL 2026/                       # PDFs de guías de remisión — abril
│   ├── 20505504781-09-T001-616.pdf ... T001-625.pdf
│   └── GUIAS SELLADAS ABRIL 2026/
└── CLAUDE.md
```

**Convención de nombres PDF:** `20505504781-09-T001-NNN.pdf`
El número `NNN` es el número correlativo de la guía de remisión electrónica (T001-587, T001-588, ...).

---

## Módulo 1: OC Antapaccay (`oc_antapaccay.py`)

**Datos:** `OC_Antapaccay.xlsx` — hoja `Hoja1`
**Correr:** `streamlit run oc_antapaccay.py`

Gestiona las órdenes de compra internas de NETSAT para el cliente Antapaccay.
Cada fila es un ítem de OC con producto, cantidades, precios y observaciones de compra.

### Estructura del Excel (después de limpieza)
- Fila 1: encabezados — `OC`, `Item`, `Descripción`, `Cant`, `Fob`, `Desaduanaje`, `Impuestos`, `Venta Unit US $`, `Venta Total US $`, `Observaciones`
- Filas 2–32: datos (31 ítems de OC activos)

> El Excel fue limpiado: originalmente tenía 116 filas con ~84 filas vacías o con solo fórmulas.
> El backup original se conserva en `OC_Antapaccay_BACKUP.xlsx`.

### Funcionalidades
- **Ver & Editar:** tabla editable con filtros por OC y descripción/observaciones
- **Agregar OC:** formulario para insertar nuevas filas al Excel
- **Resumen por OC:** agrupado por número de OC con total USD

### Decisiones de diseño importantes

**Sin columna Estado:** se eliminó la inferencia automática de estado desde Observaciones.
Las Observaciones son texto libre y se respetan tal cual desde el Excel.

**Lectura dinámica del encabezado:** el código busca la fila que contiene la celda `"OC"`
en lugar de asumir fila fija. Tolerante a cambios de estructura.

**Mapeo flexible de columnas:** cada columna canónica tiene una lista de variantes de nombre
para tolerar inconsistencias entre versiones del Excel.

### Hack crítico: columna "Fila"

`st.data_editor` muestra su propio contador 0-based que desorienta al usuario.
Se agrega una columna `Fila` que muestra el número de fila Excel real:

```python
# CRÍTICO: no hacer reset_index antes de calcular Fila
df = df.iloc[header_row + 1:]          # conserva índices originales pandas
df = df[df["OC"].notna() | df["Descripción"].notna()]
df.insert(0, "Fila", df.index + 1)    # índice pandas 0-based + 1 = fila Excel 1-based
df = df.reset_index(drop=True)         # recién aquí se resetea
```

En `guardar_excel()` se usa `row_data["Fila"]` como número de fila real para openpyxl.
Nuevas OCs tienen `Fila=None` y se appendean en `ws.max_row + 1`.

En la UI: `st.data_editor(..., hide_index=True)` y `"Fila"` con `disabled=True`.

---

## Módulo 2: Guías de Despacho (`guias_despacho.py`)

**Datos:** `OrdenesActivacion 13-04-2026-editado.xlsx` + PDFs en `GUIAS MARZO/ABRIL 2026/`
**Correr:** `streamlit run guias_despacho.py`
**Dependencia extra:** `pdfplumber` (`pip install pdfplumber`)

Cruza las órdenes oficiales del cliente Antapaccay con las guías de remisión PDF emitidas
por NETSAT para mostrar qué órdenes ya fueron despachadas y cuáles están pendientes.

### Fuentes de datos

**OrdenesActivacion** (`Sheet1`, 24 filas):
Órdenes del sistema de Antapaccay. Columnas renombradas por posición (el Excel tiene problemas
de encoding en los encabezados):

| Pos | Nombre interno   | Descripción                          |
|-----|-----------------|--------------------------------------|
| 0   | Proveedor        | Siempre "NETSAT SRL"                 |
| 1   | Codigo_OC        | Ej: `C003962782-1` (con sufijo item) |
| 2   | Estado           | Largo plazo / Por vencer / Vencido   |
| 3   | Comprador        | Kriss Huertas, Fernanda Llanos, etc. |
| 4   | Fecha_Entrega    | Fecha pactada de entrega             |
| 5   | Fecha_Registro   | Fecha de registro de la OC           |
| 6   | Codigo_Item      | Código interno del ítem              |
| 7   | Item             | Descripción completa del producto    |
| 8   | Criticidad       | Siempre "S/D"                        |
| 9   | Cant_Comprado    | Cantidad total ordenada              |
| 10  | Cant_Entregado   | Siempre 0 (no actualizado en origen) |
| 11  | Cant_Restante    | Igual a Cant_Comprado                |
| 12  | Activador        | Siempre "S/D"                        |
| 13  | Comentarios      | Texto libre — a veces menciona guías |

Se genera columna `OC_base` quitando el sufijo: `C003962782-1` → `C003962782`.

**PDFs de guías:**
Cada PDF es una Guía de Remisión Electrónica emitida por NETSAT.
Se parsean con `pdfplumber` extrayendo:
- Número de guía: del nombre de archivo `T001-NNN`
- OC referenciada: regex `Orden de compra[:.]\s*(C\d+)` — ojo: algunos PDFs usan punto en lugar de dos puntos
- Fecha de traslado: regex `Fecha del Traslado:\s*(\d{2}/\d{2}/\d{4})`

### Lógica de cruce

Una orden se marca **Despachado** si su `OC_base` aparece como OC en algún PDF.
Una OC puede tener múltiples guías (entregas parciales) — se concatenan en la columna `Guías`.

```python
# OC_base de ordenes: "C003962782"
# OC de PDF:          "C003962782"   ← coinciden directamente
```

### Estado actual (al 24/04/2026)
- Guías emitidas: T001-587 a T001-625 (39 guías en total)
- Órdenes totales: 24
- Despachadas: 14 · Pendientes: 10

### Tabs de la UI
1. **Órdenes y estado** — tabla filtrable por estado y comprador
2. **Guías emitidas** — lista de todos los PDFs con OC y fecha
3. **Buscar por OC** — búsqueda libre que muestra órdenes + guías coincidentes

---

## Convenciones de entorno

- **Emojis en terminal Windows:** NO usar emojis ni caracteres Unicode especiales (✔, ✗, →, etc.) en `print()` de scripts Python que corran en terminal Windows — la codificación cp1252 los rompe. Usar texto plano (`OK`, `ERROR`, etc.).
- **Emojis en la UI Streamlit:** sí se pueden usar con normalidad — Streamlit renderiza en el navegador, sin limitaciones de encoding.
- **Claude no lee `.env`:** hay un hook `PreToolUse` en `.claude/settings.json` que bloquea la lectura de archivos `.env`. El `.env.example` sí es legible.

---

## Convenciones del proyecto

- **Un archivo `.py` por módulo/cliente**
- **Excel como fuente de datos** (al menos por ahora)
- **Columna `Fila`** siempre que se necesite referenciar filas Excel en la UI
- **Sin columnas de estado inferidas automáticamente** — el usuario las gestiona manualmente
- **`width="stretch"`** en `st.dataframe` y `st.data_editor` (no `use_container_width=True`, está deprecado)
- **`@st.cache_data(ttl=0)`** en todas las funciones de carga — se invalida manualmente con `st.cache_data.clear()`

---

## Historial de cambios

Consultar **`HISTORIAL.md`** al inicio de cada sesión para entender qué se hizo, por qué, y qué decisiones se tomaron. Incluye correcciones de datos, bugs resueltos y estado del cruce por fecha.

---

## Instalación en servidor

```bash
git clone https://github.com/ELLokoAkrata/Netsat-centrum.git
cd Netsat-centrum
pip install streamlit pandas openpyxl pdfplumber
streamlit run oc_antapaccay.py      # módulo OC
streamlit run guias_despacho.py     # módulo guías
```

---

## Guía para escalar

Próximos módulos probables: otras cuentas/clientes, inventario, cotizaciones, seguimiento de envíos.

Al agregar un mes nuevo (ej. Mayo), añadir una tupla a `_guias_folders()` en `guias_despacho.py`
siguiendo el patrón de Febrero/Marzo/Abril. Enero fue excepción con subcarpeta extra.

Estructura real en Z: (confirmada 29/04/2026):
- Enero:  `GUIAS ENERO 2026/GUIAS SELLADAS 2026/GUIAS SELLADAS ENERO 26/` — 39 PDFs
- Febrero: `GUIAS FEBRERO 2026/GUIAS SELLADAS FEBRERO 2026/` — 22 PDFs
- Marzo:  `GUIAS MARZO 2026/GUIAS SELLADAS MARZO 2026/` — 29 PDFs
- Abril:  `GUIAS ABRIL 2026/GUIAS SELLADAS ABRIL 2026/` — 14 PDFs (crece)
