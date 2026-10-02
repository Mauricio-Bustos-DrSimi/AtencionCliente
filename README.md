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
4. Crea el administrador inicial. El comando solicita la contraseña sin mostrarla:

   ```powershell
   python -m app.cli create-admin --username admin --name "Administrador local"
   ```

5. Inicia el servicio local:

   ```powershell
   uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

6. Abre <http://127.0.0.1:8000>.

## Crear usuarios

El administrador puede crear cuentas desde **Usuarios**. Para Jefes Comerciales y Supervisores, el alcance debe coincidir con el nombre correspondiente en `NomJefeComercial` o `NomSupervisor`.

También se pueden crear desde PowerShell; `--role` acepta `gerente_general`, `gerente_ventas`, `gerente_franquicias`, `jefe_comercial_ventas`, `jefe_comercial_franquicias` o `supervisor`:

```powershell
python -m app.cli create-user --username usuario --name "Nombre Apellido" --role supervisor --scope-name "Nombre Supervisor"
```

Para cambiar una contraseña local desde PowerShell:

```powershell
python -m app.cli set-password --username admin
```

## Roles y alcance

- **Gerente general:** ve todos los locales.
- **Gerente de ventas:** solo códigos `CL` (sucursales propias).
- **Gerente de franquicias:** solo códigos `F`.
- **Jefe comercial de ventas/franquicias:** ve locales de su división asignados a su nombre; se agrupan por supervisor.
- **Supervisor:** ve los locales cuyo `NomSupervisor` coincide con su alcance.
- **Administrador:** ve todos los locales y administra cuentas.

Los cambios de planes se guardan en SQLite local. La API vuelve a comprobar el alcance del usuario antes de guardar cada plan. Toda evaluación clasificada como mala requiere texto de plan; los estados disponibles son abierto, en proceso y concluido.

## Configuración de SQL

Edita `.env` localmente. No guardes credenciales reales en el repositorio. Variables disponibles: `ATENCION_SQL_SERVER`, `ATENCION_SQL_DATABASE`, `ATENCION_SQL_USER`, `ATENCION_SQL_PASSWORD`, `ATENCION_SQL_DRIVER`, y sus equivalentes `LOCALES_SQL_*`.

El servicio puede iniciar sin conexión SQL para permitir la preparación local. El panel informa el problema de conexión hasta que se configuren ambos orígenes.


## Modelo transaccional de acciones

La base SQLite local usa estas tablas:

- `users`: cuentas, roles y alcance de cada usuario.
- `action_plans`: estado vigente y texto actual del plan, con un plan por cada ID de atención.
- `action_plan_transactions`: historial inmutable de cada guardado; registra evento, estado anterior y nuevo, texto anterior y actual, usuario y fecha UTC.
- `schema_migrations`: versiones instaladas del esquema.

Cada guardado modifica `action_plans` y agrega su transacción en una sola transacción SQLite. Al iniciar, la migración conserva los planes existentes y crea un evento inicial para cada plan legado. El historial se consulta desde el detalle del plan y vuelve a validar los permisos del usuario.


La eliminación de un plan es lógica: deja de aparecer como vigente, pero conserva su registro y transacciones. Si se vuelve a guardar para la misma evaluación, queda restaurado y el historial registra esa acción.
