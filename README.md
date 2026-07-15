# Sistema de Expedientes Digitales — RRHH

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

1. **`.env` de producción**:
   - `DJANGO_DEBUG=0`
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

3. **Base de datos**: para varios usuarios simultáneos, migrá de SQLite a
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
  ├─ permisos.py  Filtrado por zona (corazón de la seguridad)
  ├─ storage.py   Cifrado de archivos en reposo
  └─ auditoria.py Registro de acciones
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

## Administración avanzada

Panel de Django en `/gestion-django/` (solo superusuarios/staff): alta de
usuarios, asignación de rol y zona, catálogo de **tipos de documento**
(marcar cuáles son obligatorios y cuáles vencen), zonas y sedes.

## Ideas para próximas versiones

- 2FA (django-otp) para el rol Administrador.
- Notificaciones por email de vencimientos próximos.
- Firma/hash de integridad por documento.
- Exportación del expediente completo a un PDF/ZIP.
