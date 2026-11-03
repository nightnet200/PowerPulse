from datetime import date

from . import archive, store
from .executor import global_targets
from .occurrences import (REPEATS, fmt_date, in_range, period_range, status_for,
                          weekdays_text)

PERIODS = {"day": "Diario", "month": "Mensual", "year": "Anual", "range": "de rango"}


def build_report(scope: str, period: str, ref: date,
                 end: date | None = None) -> tuple[str, list[str], list[list[str]]]:
    """scope: 'schedules' | 'global'; period: day|month|year|range|all (all solo para global)."""
    hist = store.history.status_map()
    assignments = {a["ip"]: a for a in store.load_assignments()}

    if scope == "global" and period == "all":
        headers = ["Nombre", "Inicio", "Hora", "Repetición", "Días", "Hasta", "Activa",
                   "Equipos afectados", "Excluidos"]
        rows = [[g["name"], fmt_date(g["start_date"]), g["time"], REPEATS[g["repeat"]],
                 weekdays_text(g), fmt_date(g.get("until")), "Sí" if g.get("enabled", True) else "No",
                 str(len(global_targets(g))), ", ".join(g.get("excluded_ips", []))]
                for g in store.globals_.all()]
        return "Informe de programaciones globales (definiciones)", headers, rows

    d0, d1 = (ref, end) if period == "range" else period_range(period, ref)
    span = fmt_date(d0) if d0 == d1 else f"{fmt_date(d0)} - {fmt_date(d1)}"
    if scope == "global":
        title = f"Informe {PERIODS[period].lower()} de programaciones globales ({span})"
        headers = ["Fecha", "Hora", "Nombre", "Repetición", "Equipos afectados", "Excluidos", "Estado"]
        rows = [[fmt_date(d), g["time"], g["name"], REPEATS[g["repeat"]], str(len(global_targets(g))),
                 ", ".join(g.get("excluded_ips", [])), status_for(g, d, hist)]
                for d, items in sorted(in_range(store.globals_.all(), d0, d1).items()) for g in items]
    else:
        title = f"Informe {PERIODS[period].lower()} de programaciones ({span})"
        headers = ["Fecha", "Hora", "Origen", "IP", "Etiqueta", "Repetición", "Notas", "Estado"]
        entries = []
        for d, items in in_range(store.schedules.all() + archive.as_schedules(), d0, d1).items():
            for s in items:
                entries.append((d, s["time"], 0, [
                    fmt_date(d), s["time"], "Calendario", s["ip"],
                    assignments.get(s["ip"], {}).get("label", s.get("label", "")),
                    REPEATS[s["repeat"]], s.get("notes", ""), status_for(s, d, hist)]))
        for d, items in in_range(store.globals_.all(), d0, d1).items():
            for g in items:
                excluded = g.get("excluded_ips", [])
                entries.append((d, g["time"], 1, [
                    fmt_date(d), g["time"], "Global", f"Todos ({len(global_targets(g))} equipos)", g["name"],
                    REPEATS[g["repeat"]], f"Excluidos: {', '.join(excluded)}" if excluded else "",
                    status_for(g, d, hist)]))
        rows = [e[3] for e in sorted(entries, key=lambda e: e[:3])]
    return title, headers, rows


def write_xlsx(path: str, title: str, headers: list[str], rows: list[list[str]]) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Informe"
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    ws.append(headers)
    for c in ws[3]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E78")
    for r in rows:
        ws.append(r)
    for i, h in enumerate(headers, 1):
        width = max([len(h)] + [len(str(r[i - 1])) for r in rows]) + 2
        ws.column_dimensions[get_column_letter(i)].width = min(width, 60)
    ws.freeze_panes = "A4"
    wb.save(path)


def write_pdf(path: str, title: str, headers: list[str], rows: list[list[str]]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    cell = styles["BodyText"]
    cell.fontSize = 8
    cell.leading = 10
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=24, rightMargin=24,
                            topMargin=24, bottomMargin=24, title=title)
    data = [headers] + [[Paragraph(str(v), cell) for v in r] for r in rows]
    if not rows:
        data.append(["Sin registros"] + [""] * (len(headers) - 1))
    width = (landscape(A4)[0] - 48) / len(headers)
    table = Table(data, colWidths=[width] * len(headers), repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#EEF3F8")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    doc.build([Paragraph(title, styles["Title"]),
               Paragraph(f"Generado: {date.today():%d/%m/%Y}", styles["Normal"]),
               Spacer(1, 10), table])
