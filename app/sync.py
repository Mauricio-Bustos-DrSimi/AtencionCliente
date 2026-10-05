import argparse
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .db import db_session, initialize
from .sources import get_attention_rows


logger = logging.getLogger("atencion_cliente.sync")
try:
    SANTIAGO = ZoneInfo("America/Santiago")
except ZoneInfoNotFoundError:
    SANTIAGO = None


def previous_completed_week(reference: date) -> tuple[date, date]:
    period_end = reference - timedelta(days=reference.weekday() + 1)
    return period_end - timedelta(days=6), period_end


def evaluation_date(row: dict) -> date | None:
    try:
        return date.fromisoformat(str(row.get("Fecha") or "")[:10])
    except ValueError:
        return None


def serialized_row(row: dict) -> tuple[str, str]:
    payload = json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_run(trigger: str, week_start: date, week_end: date, started_at: str) -> int:
    with db_session() as connection:
        cursor = connection.execute(
            """INSERT INTO evaluation_sync_runs
               (trigger_type, status, week_start, week_end, started_at)
               VALUES (?, 'running', ?, ?, ?)""",
            (trigger, week_start.isoformat(), week_end.isoformat(), started_at),
        )
        return int(cursor.lastrowid)


def mark_failed(run_id: int, error: Exception) -> None:
    message = f"{type(error).__name__}: {error}"[:2000]
    with db_session() as connection:
        connection.execute(
            """UPDATE evaluation_sync_runs
               SET status = 'failed', completed_at = ?, error_message = ?
               WHERE id = ?""",
            (datetime.now(timezone.utc).isoformat(), message, run_id),
        )


def run_sync(
    trigger: str = "manual",
    reference_date: date | None = None,
    source_loader=get_attention_rows,
) -> dict:
    """Consulta las fuentes y persiste el histórico y el último corte semanal."""
    initialize()
    if reference_date:
        local_today = reference_date
    elif SANTIAGO:
        local_today = datetime.now(SANTIAGO).date()
    else:
        logger.warning(
            "No está instalada la base horaria IANA; se usará la fecha local del sistema."
        )
        local_today = datetime.now().astimezone().date()
    week_start, week_end = previous_completed_week(local_today)
    started_at = datetime.now(timezone.utc).isoformat()
    run_id = create_run(trigger, week_start, week_end, started_at)
    logger.info(
        "[sincronización %s] Inicio. Corte semanal: %s al %s.",
        run_id,
        week_start,
        week_end,
    )

    try:
        source_rows = source_loader()
        unique_rows: dict[str, dict] = {}
        for row in source_rows:
            attention_id = str(row.get("ID") or "").strip()
            if not attention_id:
                raise ValueError("La consulta devolvió una evaluación sin ID.")
            normalized = dict(row)
            normalized["ID"] = attention_id
            unique_rows[attention_id] = normalized
        if len(unique_rows) != len(source_rows):
            logger.warning(
                "[sincronización %s] Se consolidaron %s IDs duplicados de la fuente.",
                run_id,
                len(source_rows) - len(unique_rows),
            )

        dated_rows = [
            (row, row_date)
            for row in unique_rows.values()
            if (row_date := evaluation_date(row)) and row_date <= week_end
        ]
        snapshot_start = week_start
        snapshot_end = week_end
        target_has_rows = any(
            week_start <= row_date <= week_end for _, row_date in dated_rows
        )
        if dated_rows and not target_has_rows:
            latest_available_date = max(row_date for _, row_date in dated_rows)
            snapshot_start = latest_available_date - timedelta(
                days=latest_available_date.weekday()
            )
            snapshot_end = snapshot_start + timedelta(days=6)
            logger.warning(
                "[sincronización %s] El corte calendario no tiene registros; "
                "se usarán los datos de la última semana disponible (%s al %s) "
                "sin cambiar el período oficial del corte.",
                run_id,
                snapshot_start,
                snapshot_end,
            )

        inserted = updated = unchanged = 0
        weekly_rows: list[tuple[str, dict, str, str, str | None]] = []
        completed_at = datetime.now(timezone.utc).isoformat()
        with db_session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for attention_id, row in unique_rows.items():
                payload, payload_hash = serialized_row(row)
                row_date = evaluation_date(row)
                row_date_text = row_date.isoformat() if row_date else None
                current = connection.execute(
                    "SELECT payload_hash FROM evaluation_history WHERE attention_id = ?",
                    (attention_id,),
                ).fetchone()
                if current is None:
                    operation = "inserted"
                    inserted += 1
                    connection.execute(
                        """INSERT INTO evaluation_history
                           (attention_id, evaluation_date, payload_json, payload_hash,
                            first_seen_run_id, last_seen_run_id, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            attention_id, row_date_text, payload, payload_hash,
                            run_id, run_id, completed_at, completed_at,
                        ),
                    )
                elif current["payload_hash"] != payload_hash:
                    operation = "updated"
                    updated += 1
                    connection.execute(
                        """UPDATE evaluation_history
                           SET evaluation_date = ?, payload_json = ?, payload_hash = ?,
                               last_seen_run_id = ?, updated_at = ?
                           WHERE attention_id = ?""",
                        (
                            row_date_text, payload, payload_hash, run_id,
                            completed_at, attention_id,
                        ),
                    )
                else:
                    operation = "unchanged"
                    unchanged += 1
                    connection.execute(
                        """UPDATE evaluation_history
                           SET last_seen_run_id = ? WHERE attention_id = ?""",
                        (run_id, attention_id),
                    )
                connection.execute(
                    """INSERT INTO evaluation_sync_operations
                       (sync_run_id, attention_id, target_table, operation_type, performed_at)
                       VALUES (?, ?, 'evaluation_history', ?, ?)""",
                    (run_id, attention_id, operation, completed_at),
                )
                if row_date and snapshot_start <= row_date <= snapshot_end:
                    weekly_rows.append(
                        (attention_id, row, payload, payload_hash, row_date_text)
                    )

            connection.execute(
                "DELETE FROM weekly_evaluations WHERE week_start = ?",
                (week_start.isoformat(),),
            )
            for attention_id, _, payload, payload_hash, row_date_text in weekly_rows:
                connection.execute(
                    """INSERT INTO weekly_evaluations
                       (week_start, week_end, attention_id, evaluation_date,
                        payload_json, payload_hash, sync_run_id, captured_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        week_start.isoformat(), week_end.isoformat(), attention_id,
                        row_date_text, payload, payload_hash, run_id, completed_at,
                    ),
                )
                connection.execute(
                    """INSERT INTO evaluation_sync_operations
                       (sync_run_id, attention_id, target_table, operation_type, performed_at)
                       VALUES (?, ?, 'weekly_evaluations', 'snapshot', ?)""",
                    (run_id, attention_id, completed_at),
                )

            connection.execute(
                """UPDATE evaluation_sync_runs
                   SET status = 'success', week_start = ?, week_end = ?,
                       completed_at = ?, source_rows = ?,
                       weekly_rows = ?, historical_inserted = ?, historical_updated = ?,
                       historical_unchanged = ?, error_message = NULL
                   WHERE id = ?""",
                (
                    week_start.isoformat(), week_end.isoformat(), completed_at,
                    len(unique_rows), len(weekly_rows), inserted, updated, unchanged,
                    run_id,
                ),
            )
        result = {
            "run_id": run_id,
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "source_rows": len(unique_rows),
            "weekly_rows": len(weekly_rows),
            "historical_inserted": inserted,
            "historical_updated": updated,
            "historical_unchanged": unchanged,
        }
        logger.info("[sincronización %s] Finalizada correctamente: %s", run_id, result)
        return result
    except Exception as error:
        mark_failed(run_id, error)
        logger.exception("[sincronización %s] Falló la carga.", run_id)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Sincroniza las evaluaciones de atención.")
    parser.add_argument("--trigger", default="manual")
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_sync(trigger=arguments.trigger)


if __name__ == "__main__":
    main()
