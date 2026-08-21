# GDE — Gestión Digital de Expedientes

Gestión de expedientes del personal para la sede central y las sucursales del
interior. Construido en **Django + HTMX**, pensado para correr en un **servidor
físico interno** con los documentos **cifrados en disco**.

## Qué resuelve

| Requisito de RRHH | Cómo lo cubre el sistema |
|---|---|
| Escanear y cargar documentos | Subida de PDF/imágenes por trabajador y por tipo de documento, con versionado. |
| Acceso remoto sin demoras | App web: el interior entra por navegador (red interna / VPN). |
| Roles y permisos por zona | 3 roles con alcance geográfico (ver abajo). |
| Información confidencial | Cifrado de archivos en reposo, auditoría de accesos, HTTPS, borrado lógico. |

### Roles

- **Administrador (Sede Central):** acceso total nacional — crear, editar, ver,
  descargar, enviar a papelera y restaurar. Único que ve la **auditoría** y la
  **papelera**.
- **RRHH Interior:** restringido a **su zona**. Solo ve y carga expedientes de
  las sucursales de su zona; no ve la nómina de otras zonas.
- **Solo lectura:** consulta dentro de su zona, sin modificar nada.

El aislamiento por zona se aplica en **todas** las consultas (no solo en la
interfaz): un usuario del interior recibe *403* si intenta abrir por URL un
expediente de otra zona.

## Extras incluidos (más allá de lo pedido)

- **Auditoría**: bitácora inmutable de logins, consultas, descargas, cargas y
  borrados, con usuario, IP y fecha.
- **Cifrado en reposo** de los documentos (Fernet/AES). En disco no se leen sin
  la clave; nunca se sirven directo, siempre pasan por una vista que valida permisos.
- **Borrado lógico** (papelera) en lugar de borrado real.
- **Versionado** de documentos por tipo.
- **Alertas de vencimiento** (carnet de salud, certificados) en el panel.
- **Checklist de completitud** del expediente según tipos obligatorios.
- **Remuneración por expediente** en varias monedas (ver abajo).

---

## Puesta en marcha (desarrollo)

```bash
# 1. Entorno virtual
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # Linux/Mac

# 2. Dependencias
pip install -r requirements.txt

# 3. Variables de entorno
copy .env.example .env            # Windows  (cp en Linux/Mac)
#    Generá las claves y pegálas en .env:
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
python -c "import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"

# 4. Base de datos y datos de ejemplo
python manage.py migrate
python manage.py seed_demo        # opcional: crea zonas, sedes y usuarios demo
python manage.py createsuperuser  # tu usuario administrador real

# 5. Levantar
python manage.py runserver
```

Abrir http://127.0.0.1:8000/

### Usuarios de demostración (tras `seed_demo`)

Contraseña de todos: **`Demo1234`**

| Usuario | Rol | Alcance |
|---|---|---|
| `admin_nacional` | Administrador | Nacional |
| `rrhh_norte` | RRHH Interior | Zona Norte |
| `lectura_sur` | Solo lectura | Zona Sur |

> ⚠️ Los usuarios demo son solo para probar. **Borralos o cambiales la
> contraseña antes de producción.**

---

## Despliegue en el servidor físico interno

1. **`.env` de producción**. Lo más simple es dejar que lo arme el script:

   ```
   crear_env.bat servidor
   ```

   Ese modo escribe `DJANGO_DEBUG=0` y `DJANGO_SECURE_COOKIES=1` solos, y nunca
   pisa un `.env` que ya exista. Si lo hacés a mano, lo que tiene que quedar es:

   - `DJANGO_DEBUG=0` — **lo más importante de esta lista**. Con `1` en una
     dirección pública, cualquier error muestra la traza completa: rutas del
     servidor, fragmentos de configuración y consultas. Si la variable no está,
     vale `0`: el sistema falla hacia el lado seguro.
   - `DJANGO_ALLOWED_HOSTS=rrhh.empresa.local,192.168.x.x` (el nombre/IP del servidor)
   - `DJANGO_SECURE_COOKIES=1` (si servís por HTTPS, recomendado)
   - `DJANGO_CSRF_TRUSTED_ORIGINS=https://rrhh.empresa.local`
   - `DOCUMENTOS_ENCRYPTION_KEY`: **guardá esta clave a resguardo**. Si se pierde,
     los documentos ya cifrados NO se pueden recuperar.

2. **Servidor de aplicación** (no usar `runserver` en producción):
   ```bash
   pip install waitress
   python -m waitress --listen=0.0.0.0:8000 config.wsgi:application
   ```
   Poné delante **Nginx o IIS** como proxy inverso con HTTPS (certificado
   interno). Serví los estáticos con `python manage.py collectstatic`.

3. **Base de datos**: SQLite deja escribir a una persona por vez. Está
   configurado para esperar el turno hasta 20 segundos en vez de fallar con
   *database is locked*, que alcanza para el uso actual. Si con el tiempo se
   nota lentitud al guardar con varias personas a la vez, el paso siguiente es
   **PostgreSQL** (cambiar `DATABASES` en `config/settings.py`).

4. **Copias de seguridad** (crítico): respaldá periódicamente
   - la base de datos (`db.sqlite3` o el dump de PostgreSQL),
   - la carpeta `media/` (documentos cifrados),
   - y la `DOCUMENTOS_ENCRYPTION_KEY` (por separado y a resguardo).

---

## Estructura del proyecto

```
config/           Configuración Django (settings, urls, wsgi)
cuentas/          Usuarios, roles, Zona y Sede + login/logout con auditoría
expedientes/      Trabajador, TipoDocumento, Documento, Auditoría
                  + Moneda, ConceptoPago, AsignacionPago (remuneración)
  ├─ permisos.py  Filtrado por zona (corazón de la seguridad)
  ├─ storage.py   Cifrado de archivos en reposo
  ├─ auditoria.py Registro de acciones
  └─ tests.py     Tests de remuneración y aislamiento por rol/zona
templates/        Plantillas HTML (HTMX para búsqueda en vivo)
static/           CSS y HTMX (servido localmente, sin CDN)
```

## Registro por links tokenizados (invitaciones)

En vez de crear cada usuario a mano, el administrador genera un **link de
invitación por rol** y se lo envía a la persona, que se registra sola:

1. En `/gestion-django/` → **Invitaciones de registro** → **Agregar**.
2. Elegí el **rol** (y la **zona** si es RRHH Interior o Solo lectura), opcional
   email/nota y fecha de expiración. Al guardar se genera el link.
3. La columna **Link de registro** muestra la URL lista para copiar y enviar.
4. La persona abre el link, completa usuario y contraseña, y queda con el rol y
   la zona ya asignados (no puede elegirse un rol de mayor privilegio).

Características de seguridad de los links:
- **Un solo uso**: al registrarse, el link se marca como usado.
- **Caducan** (7 días por defecto) y se pueden **anular** en cualquier momento.
- El listado del admin se **filtra por rol** (menú lateral), estado y zona.
- Cada registro queda en la **auditoría**.

> El link usa la base `DJANGO_SITE_URL` del `.env`. En producción ponéla con el
> nombre/IP real del servidor (ej. `http://192.168.1.50:8000`) para que los
> links apunten bien.

## Remuneración por expediente

Cada expediente tiene una sección **Remuneración** con los montos vigentes del
trabajador. Refleja lo que la persona cobra hoy: cuando algo cambia, se edita
y se guarda.

### La grilla de conceptos

Los conceptos que cargás en Configuración **bajan solos al expediente como
ítems**, cada uno con su casillero de monto. No hay que ir agregándolos de a
uno: se completan los que la persona cobra y se dejan vacíos los demás.

```
CONCEPTO           MONEDA     MONTO
Sueldo base        Bs (VES)   [ 180,00 ]
Bono producción    $  (USD)   [ 400,00 ]
Bono transporte    €  (EUR)   [        ]   <- vacío = no lo cobra
Cesta ticket       Bs (VES)   [  50,00 ]
                                          [ Guardar remuneración ]
```

- Un concepto nuevo en Configuración aparece **automáticamente** en todos los
  expedientes, listo para completar.
- Un concepto que desactivás deja de aparecer.
- **Vaciar un monto da de baja ese concepto** para esa persona (baja lógica).
- La **moneda la define el concepto**, no se elige por trabajador.

### Cómo se registran los montos

Cada monto se guarda tal cual en la moneda de su concepto, **sin conversión**:

| Concepto | Monto | Se guarda como |
|---|---|---|
| Sueldo base | 180,00 Bs | 180 en VES |
| Bono producción | 400,00 $ | 400 en USD |
| Bono transporte | 50,00 € | 50 en EUR |

> El sistema **no guarda tasas de cambio**. Si pagás 400 $ y los entregás en
> bolívares al cambio, el registro sigue diciendo *400 $*: lo que importa es la
> cantidad de divisa. Por eso los totales se muestran **separados por moneda**
> (`180,00 Bs · 400,00 $ · 50,00 €`) y nunca se suman entre sí.

### Bonos extras

Para un pago puntual que no vale la pena poner en el catálogo, abajo de la
grilla hay **Bonos extras**: se escribe el nombre a mano, el monto y la moneda.
Solo estos se editan y se quitan de a uno; los del catálogo se manejan siempre
desde la grilla.

### Configuración

En `/configuracion/` (solo administradores):

- **Monedas** — vienen cargadas Bs (nacional), $ y €. Se pueden editar,
  desactivar o agregar otras. Solo una puede estar marcada como nacional.
- **Conceptos de pago** — el catálogo de conceptos, cada uno con su **moneda**,
  su clase (sueldo o bono) y su orden de aparición.

| Concepto | Clase | Moneda |
|---|---|---|
| Sueldo base | Sueldo / salario | Bs (VES) |
| Bono producción | Bono | $ (USD) |
| Bono transporte | Bono | € (EUR) |

### Quién ve los montos

Los sueldos son dato sensible, así que la sección tiene su propio permiso:

| Rol | Acceso a la remuneración |
|---|---|
| Administrador | Ve y edita, alcance nacional |
| RRHH Interior | Ve y edita, **solo en su zona** |
| Solo lectura | **No ve la sección** |

Un usuario de otra zona recibe *403* si intenta abrir el monto por URL. Quitar
un monto es **baja lógica** (no se pierde el dato) y todo alta, cambio o baja
queda en la **auditoría**.

### Exportación de la nómina a Excel

`Nómina → Exportar` genera un `.xlsx` con los filtros aplicados. Incluye la
**fecha de ingreso** y, para quien tenga permiso, la remuneración:

| C.I. | Apellidos | Nombres | Cargo | Departamento | Tienda | Fecha de ingreso | Total Bs | Total $ | Detalle de pagos |
|---|---|---|---|---|---|---|---|---|---|
| V-1 | Norte | Ana | Cajera | Ventas | Salta | 15/03/2020 | 180,00 | 400,00 | Sueldo base: 180,00 Bs · Bono producción: 400,00 $ |
| V-2 | Sur | Beto | Vendedor | Ventas | Neuquén | 01/11/2022 | 250,00 | | Sueldo base: 250,00 Bs |

- Hay **una columna de total por cada moneda** que aparezca en el listado. Si
  alguien no cobra en esa moneda, la celda queda **vacía** (no un `0`).
- Los montos se escriben como **número**, así que Excel puede sumarlos y
  filtrarlos; el símbolo va en el encabezado.
- **Detalle de pagos** desglosa concepto por concepto.
- **Solo lectura** recibe el mismo Excel pero **sin ninguna columna salarial**:
  el permiso de la sección Remuneración también se aplica acá.
- Cada exportación queda registrada en la auditoría, indicando si incluyó montos.

## Documentos corporativos automáticos

Con los datos que ya están cargados en el expediente, el sistema completa y
descarga en Word estos 5 documentos:

| Documento | Plantilla original |
|---|---|
| Contrato de trabajo | `CONTRATOS.docx` |
| Acuerdo de confidencialidad | `Formato de Contrato de Confidencialidad.docx` |
| Acta de convenio de beneficios no salariales | `17. ACTA CONVENIO BENEFICIOS NO SALARIALES.docx` |
| Acta de emisión de recibos de pago | `18. ACTAS EMISION DE RECIBO.rtf` |
| Carta de aceptación de personal en tienda | `Formato de Carta de Autorización.docx` |

Funciona como la **correspondencia de Word**: las plantillas ya traían campos
`MERGEFIELD` y el sistema los reemplaza por los datos de la persona. El archivo
que sale es un Word normal y editable, sin vínculo a ningún origen de datos.

### Puesta en marcha

```bash
python manage.py preparar_plantillas
```

Copia los Word a la carpeta `plantillas/` y deja listos los dos que no tenían
campos de combinación. Hay que volver a correrlo **cada vez que se cambie una
plantilla**. Si se guardan en otra carpeta:

```bash
python manage.py preparar_plantillas --origen "D:\formatos"
```

### De dónde sale cada dato

| Campo de la plantilla | Origen |
|---|---|
| `APELLIDO_Y_NOMBRE`, `Nombres_y_apellidos`, `Columna2` | Ficha del trabajador |
| `Cédula`, `Columna1` | Ficha del trabajador |
| `Cargo` | Ficha del trabajador |
| `Tienda`, `Dirección_de_tienda` | Tienda asignada (Configuración) |
| `Día/mes/año_de_nacimiento`, `Edad` | Fecha de nacimiento |
| `Día/mes/año_de_ingreso` | Fecha de ingreso |
| `Día/mes/año_de_culminación` | Datos de contratación |
| `Estado_civil`, `Dirección`, `Ciudad_de_nacimiento` | Datos de contratación |
| `Horario`, `Motivo_de_contratación`, `Ciudad_de_firma` | Datos de contratación |
| Salario del contrato (en números y en letras) | **Remuneración** del expediente |

Los nombres se comparan **sin tildes y sin distinguir mayúsculas**, así que las
variantes de las plantillas (`Mes_de_ingreso` y `mes_de_ingreso`) resuelven al
mismo dato.

### Una sola carga de datos

El alta del expediente (**Expedientes → Nuevo**) pide, en una sola pantalla,
todo lo que hace falta para la nómina y para los 5 documentos. Está dividida en
cuatro secciones:

| Sección | Campos |
|---|---|
| Datos personales | Cédula, nombres, apellidos, fecha de nacimiento, teléfono, email, ciudad de nacimiento, estado civil, dirección de habitación |
| Puesto y contrato | Tienda, departamento, cargo, fecha de ingreso, duración o fecha de fin, motivo, horario, ciudad de firma |
| Datos bancarios | Banco, prefijo, número de cuenta |
| Seguimiento | Observaciones, responsable |

**Lo que se calcula solo no se pide:**

| No se pide | Sale de |
|---|---|
| Día / mes / año de nacimiento, Edad | Fecha de nacimiento |
| Día / mes / año de ingreso | Fecha de ingreso |
| Día / mes / año de culminación | Fecha de fin de contrato |
| Dirección de la tienda | La tienda asignada |
| Cuenta bancaria completa | Prefijo + número |
| Salario | Sección Remuneración |

**Duración y fecha de fin:** se carga cualquiera de las dos y el sistema
completa la otra (`fecha de ingreso + días`). Si se cargan ambas, manda la
fecha, porque es la que se imprime en el contrato. Se valida que la fecha de
fin no sea anterior a la de ingreso.

Si al momento de generar falta algún dato, el expediente lo avisa e indica en
qué pantalla se completa cada uno.

> Los datos **bancarios, la duración, las observaciones y el responsable** se
> guardan para la nómina, pero **no los usa ninguna de las 5 plantillas**: no
> son campos de combinación en ningún Word. Si hacen falta en algún documento,
> hay que agregar el campo a la plantilla.

### Salario

La cláusula de salario del contrato sale de la sección **Remuneración**: se
suman los conceptos de clase *Sueldo* vigentes (priorizando la moneda nacional)
y se escriben en números y en letras.

> `180,00 Bs` → *"CIENTO OCHENTA BOLÍVARES CON 00/100 CÉNTIMOS (Bs.180,00)"*

### Quién puede generarlos

El contrato lleva el sueldo, así que rige el mismo permiso que la sección
Remuneración: **Administrador** (nacional) y **RRHH Interior** (solo su zona).
Solo lectura no ve la sección. Cada generación queda en la auditoría.

### Detalles a tener en cuenta

- El **bloque de firma y fecha** del acta de emisión de recibos se deja en
  blanco a propósito, para completarlo a mano al firmar.
- En el contrato, el año de culminación usa el mismo campo que el año de
  ingreso (`Año_de_ingreso`), tal como venía la plantilla. Mientras el contrato
  empiece y termine en el mismo año no se nota; **si cruza de año, conviene
  corregir ese campo en el Word** y volver a correr `preparar_plantillas`.

## Administración avanzada

Panel de Django en `/gestion-django/` (solo superusuarios/staff): alta de
usuarios, asignación de rol y zona, catálogo de **tipos de documento**
(marcar cuáles son obligatorios y cuáles vencen), zonas y sedes.

## Ideas para próximas versiones

- 2FA (django-otp) para el rol Administrador.
- Notificaciones por email de vencimientos próximos.
- Firma/hash de integridad por documento.
- Exportación del expediente completo a un PDF/ZIP.
