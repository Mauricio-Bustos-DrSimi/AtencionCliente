# App de Gestión de Atención al Cliente

Aplicación local con FastAPI para revisar evaluaciones, registrar planes de acción y darles seguimiento. Las evaluaciones y el maestro de locales se leen desde SQL Server. Usuarios, sesiones de trabajo y planes se guardan en una base SQLite local dentro de `data/`; la aplicación no escribe en las tablas corporativas.

## Preparación en Windows

1. Instala Python 3.11 o posterior y un Microsoft ODBC Driver para SQL Server.
2. Abre PowerShell en esta carpeta y crea un entorno virtual:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

3. Copia `.env.example` a `.env`, establece `APP_SECRET_KEY` y configura usuarios y contraseñas SQL para ambas fuentes. La primera consulta usa `172.23.1.128 / simicl_almacen`; el maestro de locales usa `172.23.1.30 / DW_Simi`.
4. La aplicación crea y mantiene automáticamente el administrador fijo `admin`, con contraseña fija `admin123`. El usuario, rol, estado y contraseña se restauran al iniciar.

5. Inicia el servicio local:

   ```powershell
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

6. Abre <http://127.0.0.1:8000>.

## Crear usuarios

El administrador puede crear cuentas desde **Usuarios**. Para Jefes Comerciales y Supervisores, el alcance debe coincidir con el nombre correspondiente en `NomJefeComercial` o `NomSupervisor`.

También puede cargar lotes desde un archivo **CSV** o **TXT** delimitado por coma, punto y coma, tabulación o `|`. Las columnas requeridas son `usuario`, `rol` y `contraseña`; `nombre` y `alcance` son opcionales. Los usuarios que ya existen se omiten y nunca se reemplazan.

```text
usuario;rol;contraseña;nombre;alcance
jperez;viewer;ClaveSegura2026!;Juan Pérez;
msoto;supervisor_ventas;ClaveSegura2026!;María Soto;María Soto
crojas;supervisor_franquicias;ClaveSegura2026!;Carlos Rojas;Carlos Rojas
```

También se pueden crear desde PowerShell; `--role` acepta `gerente_general`, `gerente_ventas`, `gerente_franquicias`, `jefe_comercial_ventas`, `jefe_comercial_franquicias`, `supervisor_ventas`, `supervisor_franquicias`, `gerencia` o `viewer`:

```powershell
python -m app.cli create-user --username usuario --name "Nombre Apellido" --role supervisor_ventas --scope-name "Nombre Supervisor"
```

Para cambiar una contraseña local desde PowerShell:

```powershell
python -m app.cli set-password --username admin
```

Desde **Usuarios**, `admin` puede editar nombre, rol, alcance y contraseña de las cuentas, además de eliminar cuentas que no sean `admin`. Las contraseñas se guardan con hash y no se pueden recuperar ni mostrar después de ser guardadas; se pueden restablecer desde la edición de cada usuario.

## Roles y alcance

- **Gerente general:** ve todos los locales.
- **Gerente de ventas:** solo códigos `CL` (sucursales propias).
- **Gerente de franquicias:** solo códigos `F`.
- **Jefe comercial de ventas/franquicias:** ve locales de su división asignados a su nombre; se agrupan por supervisor.
- **Supervisor de ventas:** ve solamente sucursales cuyo `NomSupervisor` coincide con su alcance.
- **Supervisor de franquicias:** ve solamente franquicias cuyo `NomSupervisor` coincide con su alcance.
- **Gerencia:** ve todos los locales; el campo de alcance guarda como texto la gerencia a la que pertenece la cuenta.
- **Visualizador:** ve todos los locales e indicadores; puede abrir cualquier evaluación para consultar su plan y el historial completo en modo de solo lectura, pero no puede crear, editar ni eliminar planes de acción.
- **Administrador:** ve todos los locales y administra cuentas.

Los planes funcionan como fichas CRM y se guardan como una actualización completa al presionar `Listo`; `Cancelar`, la X y la tecla Escape descartan la edición local. La API vuelve a comprobar el alcance del usuario antes de cada modificación. Los estados disponibles son pendiente, en subsanación y concluido; el paso a concluido exige una confirmación explícita dentro de la aplicación. La fecha de plazo, los compromisos y cada cambio de estado quedan registrados en el historial con usuario y fecha.

## Configuración de SQL

Edita `.env` localmente. No guardes credenciales reales en el repositorio. Variables disponibles: `ATENCION_SQL_SERVER`, `ATENCION_SQL_DATABASE`, `ATENCION_SQL_USER`, `ATENCION_SQL_PASSWORD`, `ATENCION_SQL_DRIVER`, y sus equivalentes `LOCALES_SQL_*`.

El servicio web puede iniciar sin conexión SQL. Las consultas se ejecutan mediante `python -m app.sync`, y el panel lee únicamente los datos persistidos por la última sincronización exitosa.


## Modelo transaccional de acciones

La base SQLite local usa estas tablas:

- `users`: cuentas, roles y alcance de cada usuario.
- `action_plans`: estado vigente, fecha de plazo y compromisos actuales, con un plan por cada ID de atención.
- `action_plan_transactions`: historial inmutable de cada guardado confirmado; registra estado, compromisos y plazo anteriores y nuevos, usuario y fecha UTC.
- `evaluation_history`: versión vigente de cada evaluación identificada por su ID.
- `weekly_evaluations`: instantáneas de las evaluaciones correspondientes a cada semana completa.
- `evaluation_sync_runs`: resultado y contadores de cada consulta a los orígenes SQL.
- `evaluation_sync_operations`: detalle de inserciones, actualizaciones, registros sin cambio e inclusiones en cada corte semanal.
- `schema_migrations`: versiones instaladas del esquema.

Cada guardado modifica `action_plans` y agrega su transacción en una sola transacción SQLite. Al iniciar, la migración conserva los planes existentes y crea un evento inicial para cada plan legado. El historial se consulta desde el detalle del plan y vuelve a validar los permisos del usuario.


La eliminación de un plan es lógica: deja de aparecer como vigente, pero conserva su registro y transacciones. Si se vuelve a guardar para la misma evaluación, queda restaurado y el historial registra esa acción.

## Sincronización de evaluaciones

La vista **Semanal** es la pestaña predeterminada y muestra la última semana completa cargada. La vista **Histórico** muestra el consolidado acumulado sin duplicar IDs. Para iniciar una carga manual:

```bash
python -m app.sync --trigger manual
```

En Ubuntu, las unidades incluidas en `deploy/` programan la carga cada lunes a las 06:00, hora de Santiago.

## Producción en Ubuntu

La guía completa, la unidad `systemd` y la configuración de Nginx están en [`deploy/README_UBUNTU.md`](deploy/README_UBUNTU.md). En producción, mantén `.env` fuera de Git, define `APP_SECRET_KEY` con un valor fuerte y habilita `APP_SESSION_HTTPS_ONLY=true` cuando el acceso público use HTTPS.
