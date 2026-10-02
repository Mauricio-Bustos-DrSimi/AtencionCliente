from datetime import date, datetime
from decimal import Decimal
from typing import Any

from .config import sql_connection_string


ATTENTION_QUERY = """
SELECT [ID], [Fuente], [CveUnidad], [Unidad], [Fecha], [Rating],
       [PuntajeMS], [TipoEvaluacion], [Cliente regresará (QR)], [Comentario],
       [NomJefeComercial], [NomSupervisor]
FROM [simicl_almacen].[dbo].[AtencionClientes]
ORDER BY [CveUnidad], [Fecha] DESC, [ID]
"""

LOCALES_QUERY = """
SELECT L.[CveUnidad], L.[Unidad], L.[Direccion],
       UPPER(C.[NomComuna]) AS NomComuna,
       UPPER(R.[NomRegion]) AS NomRegion,
       CASE WHEN L.[CveDivision] = 2 THEN 'FRANQUICIA'
            WHEN L.[CveDivision] = 4 THEN 'SUCURSAL' END AS Division,
       L.[NomJefeComercial], L.[NomSupervisor], L.[Latitud], L.[Longitud]
FROM [DW_Simi].[dbo].[FT_LocalesSimi] AS L
LEFT JOIN [DW_Simi].[dbo].[LS_ComunasChile] AS C ON L.[CUT_COM] = C.[CUT]
LEFT JOIN [DW_Simi].[dbo].[LS_RegionesChile] AS R ON L.[CUT_REG] = R.[CUTRegion]
LEFT JOIN [DW_Simi].[dbo].[LS_Tipologia] AS T ON L.[CveTipologia] = T.[CveTipologia]
WHERE L.[CveEstatusUnidad] = 1
ORDER BY L.[CveUnidad] ASC
"""


def _read_query(source: str, query: str) -> list[dict[str, Any]]:
    try:
        import pyodbc
    except ImportError as exc:
        raise RuntimeError("pyodbc is not installed; install requirements.txt") from exc

    connection = pyodbc.connect(sql_connection_string(source), timeout=12)
    try:
        cursor = connection.cursor()
        cursor.execute(query)
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
    finally:
        connection.close()


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def get_attention_rows() -> list[dict[str, Any]]:
    attention = _read_query("attention", ATTENTION_QUERY)
    local_rows = _read_query("locales", LOCALES_QUERY)
    locales = {str(row["CveUnidad"]).strip().upper(): row for row in local_rows}

    for row in attention:
        code = str(row.get("CveUnidad") or "").strip().upper()
        local = locales.get(code, {})
        for field in (
            "Unidad", "Direccion", "NomComuna", "NomRegion", "Division",
            "NomJefeComercial", "NomSupervisor", "Latitud", "Longitud",
        ):
            if row.get(field) is None:
                row[field] = local.get(field)
        if code.startswith("F"):
            row["Division"] = "FRANQUICIA"
        elif code.startswith("CL"):
            row["Division"] = "SUCURSAL"
        row["ID"] = str(row["ID"])
        for key, value in tuple(row.items()):
            row[key] = _json_value(value)

    return attention
