from contextlib import contextmanager
import sqlite3
from pathlib import Path
from typing import Iterator

from .config import settings


ROLES = {
    "admin": "Administrador",
    "gerente_general": "Gerente general",
    "gerente_ventas": "Gerente de ventas",
    "gerente_franquicias": "Gerente de franquicias",
    "jefe_comercial_ventas": "Jefe comercial de ventas",
    "jefe_comercial_franquicias": "Jefe comercial de franquicias",
    "supervisor": "Supervisor",
    "gerencia": "Gerencia",
    "viewer": "Visualizador",
}

PLAN_STATUSES = {"abierto", "en_proceso", "concluido"}


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
                    'jefe_comercial_franquicias', 'supervisor', 'gerencia', 'viewer'
                ))
            );

            CREATE TABLE IF NOT EXISTS action_plans (
                attention_id TEXT PRIMARY KEY,
                status TEXT NOT NULL CHECK (status IN ('abierto', 'en_proceso', 'concluido')),
                plan_text TEXT NOT NULL CHECK (length(trim(plan_text)) > 0),
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
            );

            CREATE INDEX IF NOT EXISTS ix_action_plans_status
                ON action_plans(status);

            CREATE INDEX IF NOT EXISTS ix_action_transactions_attention_date
                ON action_plan_transactions(attention_id, performed_at DESC, id DESC);

            CREATE INDEX IF NOT EXISTS ix_action_transactions_actor_date
                ON action_plan_transactions(actor_username, performed_at DESC);

            INSERT OR IGNORE INTO schema_migrations (version) VALUES (1), (2);
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


def save_plan(attention_id, status, plan_text, username):
    with db_session() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT status, plan_text, deleted_at FROM action_plans WHERE attention_id = ?",
            (attention_id,),
        ).fetchone()

        if current:
            previous_status = current["status"]
            previous_text = current["plan_text"]
            was_deleted = current["deleted_at"] is not None
            status_changed = previous_status != status
            text_changed = previous_text != plan_text
            if was_deleted:
                event_type = "plan_restaurado"
            elif status_changed and text_changed:
                event_type = "plan_y_estado_actualizados"
            elif status_changed:
                event_type = "estado_actualizado"
            elif text_changed:
                event_type = "accion_actualizada"
            else:
                event_type = "registro_confirmado"

            connection.execute(
                """UPDATE action_plans
                   SET status = ?, plan_text = ?, updated_by = ?,
                       updated_at = CURRENT_TIMESTAMP,
                       deleted_at = NULL, deleted_by = NULL,
                       completed_at = CASE WHEN ? = 'concluido'
                                           THEN COALESCE(completed_at, CURRENT_TIMESTAMP)
                                           ELSE NULL END
                   WHERE attention_id = ?""",
                (status, plan_text, username, status, attention_id),
            )
        else:
            previous_status = None
            previous_text = None
            event_type = "plan_creado"
            connection.execute(
                """INSERT INTO action_plans
                   (attention_id, status, plan_text, created_by, updated_by, completed_at)
                   VALUES (?, ?, ?, ?, ?,
                       CASE WHEN ? = 'concluido' THEN CURRENT_TIMESTAMP ELSE NULL END)""",
                (attention_id, status, plan_text, username, username, status),
            )

        connection.execute(
            """INSERT INTO action_plan_transactions
               (attention_id, event_type, previous_status, new_status,
                previous_text, action_text, actor_username)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                attention_id, event_type, previous_status, status,
                previous_text, plan_text, username,
            ),
        )


def delete_plan(attention_id, username):
    with db_session() as connection:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            """SELECT status, plan_text FROM action_plans
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
                previous_text, action_text, actor_username)
               VALUES (?, 'plan_eliminado', ?, ?, ?, ?, ?)""",
            (
                attention_id,
                current["status"],
                current["status"],
                current["plan_text"],
                current["plan_text"],
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
                      previous_text, action_text, actor_username, performed_at
               FROM action_plan_transactions
               WHERE attention_id = ?
               ORDER BY id DESC""",
            (attention_id,),
        ).fetchall()
    return [dict(row) for row in rows]
