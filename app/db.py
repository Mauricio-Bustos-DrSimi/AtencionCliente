from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path
from typing import Iterator

from .config import settings
from .security import hash_password


ROLES = {
    "admin": "Administrador",
    "gerente_general": "Gerente general",
    "gerente_ventas": "Gerente de ventas",
    "gerente_franquicias": "Gerente de franquicias",
    "jefe_comercial_ventas": "Jefe comercial de ventas",
    "jefe_comercial_franquicias": "Jefe comercial de franquicias",
    "supervisor_ventas": "Supervisor de ventas",
    "supervisor_franquicias": "Supervisor de franquicias",
    "gerencia": "Gerencia",
    "viewer": "Visualizador",
}

PLAN_STATUSES = {"pendiente", "en_subsanacion", "concluido"}
FIXED_ADMIN_USERNAME = "admin"
FIXED_ADMIN_FULL_NAME = "Administrador local"
FIXED_ADMIN_PASSWORD = "admin123"


def connect() -> sqlite3.Connection:
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(settings.database_path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize() -> None:
    with db_session() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                full_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                scope_name TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CHECK (role IN (
                    'admin', 'gerente_general', 'gerente_ventas',
                    'gerente_franquicias', 'jefe_comercial_ventas',
                    'jefe_comercial_franquicias', 'supervisor_ventas',
                    'supervisor_franquicias', 'gerencia', 'viewer'
                ))
            );

            CREATE TABLE IF NOT EXISTS action_plans (
                attention_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'pendiente'
                    CHECK (status IN ('pendiente', 'en_subsanacion', 'concluido')),
                plan_text TEXT NOT NULL DEFAULT '',
                due_date TEXT,
                created_by TEXT NOT NULL,
                updated_by TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                deleted_at TEXT,
                deleted_by TEXT
            );

            CREATE TABLE IF NOT EXISTS action_plan_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attention_id TEXT NOT NULL,
                event_type TEXT NOT NULL CHECK (event_type IN (
                    'plan_creado', 'estado_actualizado', 'accion_actualizada',
                    'plan_y_estado_actualizados', 'registro_confirmado',
                    'migracion_inicial', 'plan_eliminado', 'plan_restaurado'
                )),
                previous_status TEXT CHECK (previous_status IS NULL OR previous_status IN (
                    'pendiente', 'en_subsanacion', 'concluido'
                )),
                new_status TEXT NOT NULL CHECK (
                    new_status IN ('pendiente', 'en_subsanacion', 'concluido')
                ),
                previous_text TEXT,
                action_text TEXT NOT NULL DEFAULT '',
                previous_due_date TEXT,
                new_due_date TEXT,
                actor_username TEXT NOT NULL,
                performed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                FOREIGN KEY (attention_id) REFERENCES action_plans(attention_id)
                    ON UPDATE CASCADE ON DELETE RESTRICT
            );

            CREATE INDEX IF NOT EXISTS ix_action_plans_status
                ON action_plans(status);

            CREATE INDEX IF NOT EXISTS ix_action_transactions_attention_date
                ON action_plan_transactions(attention_id, performed_at DESC, id DESC);

            CREATE INDEX IF NOT EXISTS ix_action_transactions_actor_date
                ON action_plan_transactions(actor_username, performed_at DESC);

            CREATE TABLE IF NOT EXISTS evaluation_sync_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_type TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'success', 'failed')),
                week_start TEXT NOT NULL,
                week_end TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                source_rows INTEGER NOT NULL DEFAULT 0,
                weekly_rows INTEGER NOT NULL DEFAULT 0,
                historical_inserted INTEGER NOT NULL DEFAULT 0,
                historical_updated INTEGER NOT NULL DEFAULT 0,
                historical_unchanged INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS evaluation_history (
                attention_id TEXT PRIMARY KEY,
                evaluation_date TEXT,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                first_seen_run_id INTEGER NOT NULL,
                last_seen_run_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (first_seen_run_id) REFERENCES evaluation_sync_runs(id),
                FOREIGN KEY (last_seen_run_id) REFERENCES evaluation_sync_runs(id)
            );

            CREATE TABLE IF NOT EXISTS weekly_evaluations (
                week_start TEXT NOT NULL,
                week_end TEXT NOT NULL,
                attention_id TEXT NOT NULL,
                evaluation_date TEXT,
                payload_json TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                sync_run_id INTEGER NOT NULL,
                captured_at TEXT NOT NULL,
                PRIMARY KEY (week_start, attention_id),
                FOREIGN KEY (sync_run_id) REFERENCES evaluation_sync_runs(id)
            );

            CREATE TABLE IF NOT EXISTS evaluation_sync_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sync_run_id INTEGER NOT NULL,
                attention_id TEXT,
                target_table TEXT NOT NULL CHECK (
                    target_table IN ('evaluation_history', 'weekly_evaluations')
                ),
                operation_type TEXT NOT NULL CHECK (
                    operation_type IN ('inserted', 'updated', 'unchanged', 'snapshot')
                ),
                performed_at TEXT NOT NULL,
                FOREIGN KEY (sync_run_id) REFERENCES evaluation_sync_runs(id)
            );

            CREATE INDEX IF NOT EXISTS ix_evaluation_history_date
                ON evaluation_history(evaluation_date DESC);

            CREATE INDEX IF NOT EXISTS ix_weekly_evaluations_period
                ON weekly_evaluations(week_start DESC, evaluation_date DESC);

            CREATE INDEX IF NOT EXISTS ix_sync_operations_run
                ON evaluation_sync_operations(sync_run_id, id);

            INSERT OR IGNORE INTO schema_migrations (version) VALUES (1), (2), (5);
            """
        )
        connection.commit()

        versions = {
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        if 3 not in versions:
            connection.execute("BEGIN IMMEDIATE")
            plan_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(action_plans)")
            }
            if "deleted_at" not in plan_columns:
                connection.execute("ALTER TABLE action_plans ADD COLUMN deleted_at TEXT")
            if "deleted_by" not in plan_columns:
                connection.execute("ALTER TABLE action_plans ADD COLUMN deleted_by TEXT")

            connection.execute(
                """CREATE TABLE action_plan_transactions_v3 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attention_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK (event_type IN (
                        'plan_creado', 'estado_actualizado', 'accion_actualizada',
                        'plan_y_estado_actualizados', 'registro_confirmado',
                        'migracion_inicial', 'plan_eliminado', 'plan_restaurado'
                    )),
                    previous_status TEXT CHECK (
                        previous_status IS NULL OR previous_status IN ('abierto', 'en_proceso', 'concluido')
                    ),
                    new_status TEXT NOT NULL CHECK (new_status IN ('abierto', 'en_proceso', 'concluido')),
                    previous_text TEXT,
                    action_text TEXT NOT NULL CHECK (length(trim(action_text)) > 0),
                    actor_username TEXT NOT NULL,
                    performed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    FOREIGN KEY (attention_id) REFERENCES action_plans(attention_id)
                        ON UPDATE CASCADE ON DELETE RESTRICT
                )"""
            )
            connection.execute(
                """INSERT INTO action_plan_transactions_v3 (
                       id, attention_id, event_type, previous_status, new_status,
                       previous_text, action_text, actor_username, performed_at
                   )
                   SELECT id, attention_id, event_type, previous_status, new_status,
                          previous_text, action_text, actor_username, performed_at
                   FROM action_plan_transactions"""
            )
            connection.execute("DROP TABLE action_plan_transactions")
            connection.execute(
                "ALTER TABLE action_plan_transactions_v3 RENAME TO action_plan_transactions"
            )
            connection.execute(
                """CREATE INDEX ix_action_transactions_attention_date
                   ON action_plan_transactions(attention_id, performed_at DESC, id DESC)"""
            )
            connection.execute(
                """CREATE INDEX ix_action_transactions_actor_date
                   ON action_plan_transactions(actor_username, performed_at DESC)"""
            )
            connection.execute("INSERT INTO schema_migrations (version) VALUES (3)")
            connection.commit()

        if 4 not in versions:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE users_v4 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    full_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    scope_name TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK (role IN (
                        'admin', 'gerente_general', 'gerente_ventas',
                        'gerente_franquicias', 'jefe_comercial_ventas',
                        'jefe_comercial_franquicias', 'supervisor',
                        'gerencia', 'viewer'
                    ))
                )"""
            )
            connection.execute(
                """INSERT INTO users_v4
                   (id, username, full_name, password_hash, role, scope_name, active, created_at)
                   SELECT id, username, full_name, password_hash, role, scope_name, active, created_at
                   FROM users"""
            )
            connection.execute("DROP TABLE users")
            connection.execute("ALTER TABLE users_v4 RENAME TO users")
            connection.execute("INSERT INTO schema_migrations (version) VALUES (4)")
            connection.commit()

        if 6 not in versions:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE action_plans_v6 (
                    attention_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK (status IN ('pendiente', 'en_subsanacion', 'concluido')),
                    plan_text TEXT NOT NULL DEFAULT '',
                    due_date TEXT,
                    created_by TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    deleted_at TEXT,
                    deleted_by TEXT
                )"""
            )
            connection.execute(
                """INSERT INTO action_plans_v6 (
                       attention_id, status, plan_text, due_date, created_by,
                       updated_by, created_at, updated_at, completed_at,
                       deleted_at, deleted_by
                   )
                   SELECT attention_id,
                          CASE status
                              WHEN 'abierto' THEN 'pendiente'
                              WHEN 'en_proceso' THEN 'en_subsanacion'
                              ELSE status
                          END,
                          plan_text, NULL, created_by, updated_by, created_at,
                          updated_at, completed_at, deleted_at, deleted_by
                   FROM action_plans"""
            )
            connection.execute(
                """CREATE TABLE action_plan_transactions_v6 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    attention_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK (event_type IN (
                        'plan_creado', 'estado_actualizado', 'accion_actualizada',
                        'fecha_plazo_actualizada', 'multiples_campos_actualizados',
                        'plan_y_estado_actualizados', 'registro_confirmado',
                        'migracion_inicial', 'plan_eliminado', 'plan_restaurado'
                    )),
                    previous_status TEXT CHECK (previous_status IS NULL OR previous_status IN (
                        'pendiente', 'en_subsanacion', 'concluido'
                    )),
                    new_status TEXT NOT NULL CHECK (
                        new_status IN ('pendiente', 'en_subsanacion', 'concluido')
                    ),
                    previous_text TEXT,
                    action_text TEXT NOT NULL DEFAULT '',
                    previous_due_date TEXT,
                    new_due_date TEXT,
                    actor_username TEXT NOT NULL,
                    performed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
                    FOREIGN KEY (attention_id) REFERENCES action_plans_v6(attention_id)
                        ON UPDATE CASCADE ON DELETE RESTRICT
                )"""
            )
            connection.execute(
                """INSERT INTO action_plan_transactions_v6 (
                       id, attention_id, event_type, previous_status, new_status,
                       previous_text, action_text, previous_due_date, new_due_date,
                       actor_username, performed_at
                   )
                   SELECT id, attention_id, event_type,
                          CASE previous_status
                              WHEN 'abierto' THEN 'pendiente'
                              WHEN 'en_proceso' THEN 'en_subsanacion'
                              ELSE previous_status
                          END,
                          CASE new_status
                              WHEN 'abierto' THEN 'pendiente'
                              WHEN 'en_proceso' THEN 'en_subsanacion'
                              ELSE new_status
                          END,
                          previous_text, action_text, NULL, NULL,
                          actor_username, performed_at
                   FROM action_plan_transactions"""
            )
            connection.execute("DROP TABLE action_plan_transactions")
            connection.execute("DROP TABLE action_plans")
            connection.execute("ALTER TABLE action_plans_v6 RENAME TO action_plans")
            connection.execute(
                "ALTER TABLE action_plan_transactions_v6 RENAME TO action_plan_transactions"
            )
            connection.execute(
                "CREATE INDEX ix_action_plans_status ON action_plans(status)"
            )
            connection.execute(
                """CREATE INDEX ix_action_transactions_attention_date
                   ON action_plan_transactions(attention_id, performed_at DESC, id DESC)"""
            )
            connection.execute(
                """CREATE INDEX ix_action_transactions_actor_date
                   ON action_plan_transactions(actor_username, performed_at DESC)"""
            )
            connection.execute("INSERT INTO schema_migrations (version) VALUES (6)")
            connection.commit()

        if 7 not in versions:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """CREATE TABLE users_v7 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    full_name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    scope_name TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK (role IN (
                        'admin', 'gerente_general', 'gerente_ventas',
                        'gerente_franquicias', 'jefe_comercial_ventas',
                        'jefe_comercial_franquicias', 'supervisor_ventas',
                        'supervisor_franquicias', 'gerencia', 'viewer'
                    ))
                )"""
            )
            connection.execute(
                """INSERT INTO users_v7
                   (id, username, full_name, password_hash, role, scope_name, active, created_at)
                   SELECT id, username, full_name, password_hash,
                          CASE role
                              WHEN 'supervisor' THEN 'supervisor_ventas'
                              ELSE role
                          END,
                          scope_name, active, created_at
                   FROM users"""
            )
            connection.execute("DROP TABLE users")
            connection.execute("ALTER TABLE users_v7 RENAME TO users")
            connection.execute("INSERT INTO schema_migrations (version) VALUES (7)")
            connection.commit()

        # Migrate existing plans once, preserving their current state and text.
        connection.execute(
            """
            INSERT INTO action_plan_transactions (
                attention_id, event_type, previous_status, new_status,
                previous_text, action_text, actor_username, performed_at
            )
            SELECT p.attention_id, 'migracion_inicial', NULL, p.status,
                   NULL, p.plan_text, p.created_by,
                   COALESCE(
                       strftime('%Y-%m-%dT%H:%M:%SZ', p.created_at),
                       strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                   )
            FROM action_plans AS p
            WHERE NOT EXISTS (
                SELECT 1
                FROM action_plan_transactions AS t
                WHERE t.attention_id = p.attention_id
            )
            """
        )
        _ensure_fixed_admin(connection)


def _ensure_fixed_admin(connection: sqlite3.Connection) -> None:
    """Mantiene disponible la cuenta administrativa base de la aplicación."""
    fixed_password_hash = hash_password(FIXED_ADMIN_PASSWORD, minimum_length=8)
    existing = connection.execute(
        "SELECT username FROM users WHERE username = ? COLLATE NOCASE",
        (FIXED_ADMIN_USERNAME,),
    ).fetchone()
    if existing:
        connection.execute(
            """UPDATE users
               SET password_hash = ?, role = 'admin', scope_name = NULL, active = 1
               WHERE username = ? COLLATE NOCASE""",
            (fixed_password_hash, FIXED_ADMIN_USERNAME),
        )
        return
    connection.execute(
        """INSERT INTO users (username, full_name, password_hash, role, scope_name, active)
           VALUES (?, ?, ?, 'admin', NULL, 1)""",
        (
            FIXED_ADMIN_USERNAME,
            FIXED_ADMIN_FULL_NAME,
            fixed_password_hash,
        ),
    )


def get_user(username: str):
    with db_session() as connection:
        return connection.execute(
            "SELECT * FROM users WHERE username = ? AND active = 1",
            (username,),
        ).fetchone()


def list_users():
    with db_session() as connection:
        return connection.execute(
            """SELECT id, username, full_name, role, scope_name, active, created_at
               FROM users ORDER BY full_name, username"""
        ).fetchall()


def save_user(username, full_name, password_hash, role, scope_name):
    with db_session() as connection:
        connection.execute(
            """INSERT INTO users (username, full_name, password_hash, role, scope_name)
               VALUES (?, ?, ?, ?, ?)""",
            (username, full_name, password_hash, role, scope_name or None),
        )


def save_users_batch(users: list[dict]) -> tuple[list[str], list[dict]]:
    """Crea cuentas nuevas en una transacción, sin reemplazar las existentes."""
    created: list[str] = []
    skipped: list[dict] = []
    with db_session() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = {
            row[0].casefold()
            for row in connection.execute("SELECT username FROM users")
        }
        for user in users:
            username = user["username"]
            normalized_username = username.casefold()
            if normalized_username == FIXED_ADMIN_USERNAME:
                skipped.append({"line": user["line"], "reason": "El usuario admin es fijo."})
                continue
            if normalized_username in existing:
                skipped.append({
                    "line": user["line"],
                    "reason": f"El usuario {username!r} ya existe o está repetido.",
                })
                continue
            connection.execute(
                """INSERT INTO users (username, full_name, password_hash, role, scope_name)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    username,
                    user["full_name"],
                    user["password_hash"],
                    user["role"],
                    user.get("scope_name") or None,
                ),
            )
            existing.add(normalized_username)
            created.append(username)
    return created, skipped


def update_user_account(username, full_name, role, scope_name, password_hash=None) -> bool:
    with db_session() as connection:
        if password_hash:
            result = connection.execute(
                """UPDATE users
                   SET full_name = ?, role = ?, scope_name = ?, password_hash = ?
                   WHERE username = ? COLLATE NOCASE""",
                (full_name, role, scope_name or None, password_hash, username),
            )
        else:
            result = connection.execute(
                """UPDATE users
                   SET full_name = ?, role = ?, scope_name = ?
                   WHERE username = ? COLLATE NOCASE""",
                (full_name, role, scope_name or None, username),
            )
    return result.rowcount == 1


def delete_user_account(username) -> bool:
    with db_session() as connection:
        result = connection.execute(
            "DELETE FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        )
    return result.rowcount == 1


def save_plan(attention_id, status, plan_text, due_date, username):
    with db_session() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            """SELECT status, plan_text, due_date, deleted_at
               FROM action_plans WHERE attention_id = ?""",
            (attention_id,),
        ).fetchone()

        if current:
            previous_status = current["status"]
            previous_text = current["plan_text"]
            previous_due_date = current["due_date"]
            was_deleted = current["deleted_at"] is not None
            status_changed = previous_status != status
            text_changed = previous_text != plan_text
            due_date_changed = previous_due_date != due_date
            if was_deleted:
                event_type = "plan_restaurado"
            elif sum((status_changed, text_changed, due_date_changed)) > 1:
                event_type = "multiples_campos_actualizados"
            elif status_changed:
                event_type = "estado_actualizado"
            elif text_changed:
                event_type = "accion_actualizada"
            elif due_date_changed:
                event_type = "fecha_plazo_actualizada"
            else:
                saved = connection.execute(
                    "SELECT * FROM action_plans WHERE attention_id = ?",
                    (attention_id,),
                ).fetchone()
                return dict(saved)

            connection.execute(
                """UPDATE action_plans
                   SET status = ?, plan_text = ?, due_date = ?, updated_by = ?,
                       updated_at = CURRENT_TIMESTAMP,
                       deleted_at = NULL, deleted_by = NULL,
                       completed_at = CASE WHEN ? = 'concluido'
                                           THEN COALESCE(completed_at, CURRENT_TIMESTAMP)
                                           ELSE NULL END
                   WHERE attention_id = ?""",
                (status, plan_text, due_date, username, status, attention_id),
            )
        else:
            previous_status = None
            previous_text = None
            previous_due_date = None
            event_type = "plan_creado"
            connection.execute(
                """INSERT INTO action_plans
                   (attention_id, status, plan_text, due_date, created_by, updated_by, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?,
                       CASE WHEN ? = 'concluido' THEN CURRENT_TIMESTAMP ELSE NULL END)""",
                (attention_id, status, plan_text, due_date, username, username, status),
            )

        connection.execute(
            """INSERT INTO action_plan_transactions
               (attention_id, event_type, previous_status, new_status,
                previous_text, action_text, previous_due_date, new_due_date,
                actor_username)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                attention_id, event_type, previous_status, status,
                previous_text, plan_text, previous_due_date, due_date, username,
            ),
        )
        saved = connection.execute(
            "SELECT * FROM action_plans WHERE attention_id = ?",
            (attention_id,),
        ).fetchone()
    return dict(saved)


def delete_plan(attention_id, username):
    with db_session() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            """SELECT status, plan_text, due_date FROM action_plans
               WHERE attention_id = ? AND deleted_at IS NULL""",
            (attention_id,),
        ).fetchone()
        if not current:
            return False

        connection.execute(
            """UPDATE action_plans
               SET deleted_at = CURRENT_TIMESTAMP, deleted_by = ?,
                   updated_by = ?, updated_at = CURRENT_TIMESTAMP
               WHERE attention_id = ?""",
            (username, username, attention_id),
        )
        connection.execute(
            """INSERT INTO action_plan_transactions
               (attention_id, event_type, previous_status, new_status,
                previous_text, action_text, previous_due_date, new_due_date,
                actor_username)
               VALUES (?, 'plan_eliminado', ?, ?, ?, ?, ?, ?, ?)""",
            (
                attention_id,
                current["status"],
                current["status"],
                current["plan_text"],
                current["plan_text"],
                current["due_date"],
                current["due_date"],
                username,
            ),
        )
    return True


def get_plans():
    with db_session() as connection:
        rows = connection.execute(
            "SELECT * FROM action_plans WHERE deleted_at IS NULL"
        ).fetchall()
    return {row["attention_id"]: dict(row) for row in rows}


def get_plan_history(attention_id):
    with db_session() as connection:
        rows = connection.execute(
            """SELECT id, attention_id, event_type, previous_status, new_status,
                      previous_text, action_text, previous_due_date, new_due_date,
                      actor_username, performed_at
               FROM action_plan_transactions
               WHERE attention_id = ?
               ORDER BY id DESC""",
            (attention_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_stored_evaluations(view: str) -> list[dict]:
    """Obtiene la instantánea semanal más reciente o el histórico consolidado."""
    if view not in {"weekly", "historical"}:
        raise ValueError("La vista debe ser weekly o historical.")
    with db_session() as connection:
        if view == "weekly":
            latest_run = connection.execute(
                """SELECT week_start
                   FROM evaluation_sync_runs
                   WHERE status = 'success'
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            if not latest_run:
                return []
            rows = connection.execute(
                """SELECT payload_json
                   FROM weekly_evaluations
                   WHERE week_start = ?
                   ORDER BY evaluation_date DESC, attention_id""",
                (latest_run["week_start"],),
            ).fetchall()
        else:
            rows = connection.execute(
                """SELECT payload_json
                   FROM evaluation_history
                   ORDER BY evaluation_date DESC, attention_id"""
            ).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]


def get_latest_sync_run(successful_only: bool = False):
    with db_session() as connection:
        row = connection.execute(
            """SELECT id, trigger_type, status, week_start, week_end, started_at,
                      completed_at, source_rows, weekly_rows, historical_inserted,
                      historical_updated, historical_unchanged, error_message
               FROM evaluation_sync_runs
               WHERE (? = 0 OR status = 'success')
               ORDER BY id DESC LIMIT 1""",
            (int(successful_only),),
        ).fetchone()
    return dict(row) if row else None
