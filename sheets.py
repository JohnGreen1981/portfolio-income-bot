from datetime import date, datetime
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from config import settings

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

INCOME_HEADERS = ["Дата", "Клиент", "Сумма (₽)", "Описание", "Исходный текст", "Записано в"]
EXPENSE_HEADERS = ["Дата", "Категория", "Сумма (₽)", "Валюта", "Сумма (ориг.)", "Курс к ₽", "Магазин", "Описание", "Исходный текст", "Записано в"]

# Формулы для ru_RU локали (разделитель ; вместо ,)
_WEEK_FORMULA = (
    '=СУММПРОИЗВ((A2:A>=(ГОД(СЕГОДНЯ()-ОСТАТ(СЕГОДНЯ()-2;7))&"-"&ТЕКСТ(МЕСЯЦ(СЕГОДНЯ()-ОСТАТ(СЕГОДНЯ()-2;7));"00")&"-"&ТЕКСТ(ДЕНЬ(СЕГОДНЯ()-ОСТАТ(СЕГОДНЯ()-2;7));"00")))'
    '*(A2:A<=(ГОД(СЕГОДНЯ())&"-"&ТЕКСТ(МЕСЯЦ(СЕГОДНЯ());"00")&"-"&ТЕКСТ(ДЕНЬ(СЕГОДНЯ());"00")))*(C2:C))'
)
COUNTERS = [
    ["Итого (₽)",  '=СУММ(C2:C)'],
    ["Месяц (₽)",  '=СУММПРОИЗВ((ЛЕВСИМВ(A2:A;7)=(ГОД(СЕГОДНЯ())&"-"&ТЕКСТ(МЕСЯЦ(СЕГОДНЯ());"00")))*(C2:C))'],
    ["Неделя (₽)", _WEEK_FORMULA],
    ["Год (₽)",    '=СУММПРОИЗВ((ЛЕВСИМВ(A2:A;4)=ТЕКСТ(ГОД(СЕГОДНЯ());"0000"))*(C2:C))'],
]


class SheetsClient:
    def __init__(self):
        creds = Credentials.from_service_account_file(
            settings.google_credentials_json, scopes=SCOPES
        )
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_key(settings.google_spreadsheet_id)

        self.sheet = spreadsheet.sheet1
        if self.sheet.title != "Доходы":
            self.sheet.update_title("Доходы")
        self._ensure_headers(self.sheet, INCOME_HEADERS, "H1:I4")

        self.expense_sheet = self._get_or_create_sheet(spreadsheet, "Расходы")
        self.expense_sheet.batch_clear(["I1:J5"])  # убираем старые счётчики
        self._ensure_headers(self.expense_sheet, EXPENSE_HEADERS, "L1:M4")

    def _get_or_create_sheet(self, spreadsheet, title: str):
        try:
            return spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            return spreadsheet.add_worksheet(title=title, rows=1000, cols=20)

    def _ensure_headers(self, sheet, headers: list, counter_range: str):
        first_row = sheet.row_values(1)
        if not first_row:
            sheet.insert_row(headers, 1)
        elif first_row[:len(headers)] != headers:
            # Обновляем строку 1 на месте — не вставляем новую
            col_end = chr(64 + len(headers))
            sheet.update(f"A1:{col_end}1", [headers])
        # Удаляем дублирующую строку с заголовками если есть (артефакт от insert_row)
        second_row = sheet.row_values(2)
        if second_row and second_row[0] == "Дата":
            sheet.delete_rows(2)
        sheet.format("1:1", {"textFormat": {"bold": True}})
        sheet.update(counter_range, COUNTERS, value_input_option="USER_ENTERED")

    def add_record(self, record: dict):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.sheet.append_row(
            [
                record["date"],
                record["client"],
                record["amount"],
                record["description"],
                record["raw"],
                now,
            ],
            table_range="A1",
        )

    def add_expense_record(self, record: dict) -> int:
        """Добавляет расход и возвращает номер строки в таблице."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        result = self.expense_sheet.append_row(
            [
                record["date"],
                record["category"],
                record.get("amount_rub", record["amount"]),
                record.get("currency", "RUB"),
                record["amount"],
                record.get("rate", 1.0),
                record.get("shop", ""),
                record.get("description", ""),
                record.get("raw", ""),
                now,
            ],
            table_range="A1",
        )
        try:
            # result["updates"]["updatedRange"] = "Расходы!A5:J5" → 5
            updated_range = result["updates"]["updatedRange"]
            row_num = int(updated_range.split("!")[1].split(":")[0].lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            return row_num
        except Exception:
            return -1

    def create_monthly_summaries(self, year: int, months: list[int], categories: list[str]):
        """Создаёт или обновляет сводные листы по месяцам с формулами из листа Расходы."""
        import time

        ru_months = {
            1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
            5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
            9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь",
        }
        spreadsheet = self.sheet.spreadsheet
        n = len(categories)
        итого_row = n + 2
        section2_row = n + 4        # заголовок "Активные категории"
        итого_ref_row = n + 5       # строка ИТОГО в секции 2
        query_row = n + 6           # QUERY (ненулевые, по убыванию)
        top5_title_row = query_row + n + 3
        top5_data_row = top5_title_row + 1

        for month in months:
            month_key = f"{year}-{month:02d}"
            sheet_title = f"{ru_months[month]} {year}"
            ws = self._get_or_create_sheet(spreadsheet, sheet_title)
            ws.clear()
            time.sleep(2)

            # Вспомогательные средние курсы — M1:N4 (RSD, EUR, USD, GEL)
            ws.update("M1:N4", [
                ["Курс RSD (₽/1 din)", '=СРЗНАЧЕСЛИ(Расходы!D$2:D$5000;"RSD";Расходы!F$2:F$5000)'],
                ["Курс EUR (₽/1 €)",   '=СРЗНАЧЕСЛИ(Расходы!D$2:D$5000;"EUR";Расходы!F$2:F$5000)'],
                ["Курс USD (₽/1 $)",   '=СРЗНАЧЕСЛИ(Расходы!D$2:D$5000;"USD";Расходы!F$2:F$5000)'],
                ["Курс GEL (₽/1 ₾)",   '=СРЗНАЧЕСЛИ(Расходы!D$2:D$5000;"GEL";Расходы!F$2:F$5000)'],
            ], value_input_option="USER_ENTERED")
            ws.format("M1:M4", {"textFormat": {"italic": True}})
            time.sleep(2)

            # Заголовки:
            # A-G: основная таблица (оригинальные суммы по валютам)
            # H-K: вспомогательные эквиваленты (₽ ÷ средний курс) — источник для секции 2
            ws.update("A1:G1", [["Категория", "Сумма (₽)", "Сумма (din)", "Сумма (€)", "Сумма ($)", "Сумма (₾)", "% от итого"]])
            ws.format("A1:G1", {"textFormat": {"bold": True}})
            ws.update("H1:K1", [["din (экв.)", "€ (экв.)", "$ (экв.)", "₾ (экв.)"]])
            ws.format("H1:K1", {"textFormat": {"italic": True}})
            time.sleep(1)

            # Строки категорий (A-G)
            rows = []
            for cat in categories:
                def _cur_sum(cur, c=cat, mk=month_key):
                    return (
                        f'=СУММПРОИЗВ((ЛЕВСИМВ(Расходы!A$2:A$5000;7)="{mk}")'
                        f'*(Расходы!B$2:B$5000="{c}")*(Расходы!D$2:D$5000="{cur}")'
                        f'*Расходы!E$2:E$5000)'
                    )
                rub_base = (
                    f'СУММПРОИЗВ((ЛЕВСИМВ(Расходы!A$2:A$5000;7)="{month_key}")'
                    f'*(Расходы!B$2:B$5000="{cat}")*Расходы!C$2:C$5000)'
                )
                rows.append([
                    cat,
                    f"={rub_base}",
                    _cur_sum("RSD"),
                    _cur_sum("EUR"),
                    _cur_sum("USD"),
                    _cur_sum("GEL"),
                    "",  # % заполним отдельно
                ])
            rows.append([
                "ИТОГО",
                f"=СУММ(B2:B{n+1})",
                f"=СУММ(C2:C{n+1})",
                f"=СУММ(D2:D{n+1})",
                f"=СУММ(E2:E{n+1})",
                f"=СУММ(F2:F{n+1})",
                "",
            ])
            ws.update(f"A2:G{итого_row}", rows, value_input_option="USER_ENTERED")
            time.sleep(2)

            # % от итого (колонка G)
            pct = [[f"=ЕСЛИ(B${итого_row}>0;B{i+2}/B${итого_row};0)"] for i in range(n)]
            ws.update(f"G2:G{n+1}", pct, value_input_option="USER_ENTERED")
            time.sleep(1)

            # Вспомогательные эквиваленты H-K: ₽ ÷ средний курс (для секции 2)
            equiv_rows = []
            for i in range(n + 1):  # n категорий + ИТОГО
                r = i + 2
                equiv_rows.append([
                    f"=ЕСЛИ(N$1>0;B{r}/N$1;0)",
                    f"=ЕСЛИ(N$2>0;B{r}/N$2;0)",
                    f"=ЕСЛИ(N$3>0;B{r}/N$3;0)",
                    f"=ЕСЛИ(N$4>0;B{r}/N$4;0)",
                ])
            ws.update(f"H2:K{итого_row}", equiv_rows, value_input_option="USER_ENTERED")
            time.sleep(2)

            # Форматирование основной таблицы
            ws.format(f"G2:G{n+1}", {"numberFormat": {"type": "PERCENT", "pattern": "0.0%"}})
            ws.format(f"C2:C{итого_row}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
            ws.format(f"D2:D{итого_row}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})
            ws.format(f"E2:E{итого_row}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})
            ws.format(f"F2:F{итого_row}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})
            ws.format(f"A{итого_row}:G{итого_row}", {"textFormat": {"bold": True}})
            # Форматирование H-K (эквиваленты)
            ws.format(f"H2:H{итого_row}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
            ws.format(f"I2:K{итого_row}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})
            time.sleep(2)

            # Секция 2: "Активные категории" — всё пересчитано в ₽, остальные валюты как эквиваленты
            ws.update(f"A{section2_row}", [["📊 Активные категории (по убыванию)"]])
            ws.format(f"A{section2_row}", {"textFormat": {"bold": True}})
            time.sleep(1)

            # ИТОГО секции 2: RUB + эквиваленты (ссылки на H-K ИТОГО основной таблицы)
            итого_ref = [
                "ИТОГО",
                f"=B{итого_row}",
                f"=H{итого_row}",
                f"=I{итого_row}",
                f"=J{итого_row}",
                f"=K{итого_row}",
                "",
            ]
            ws.update(f"A{итого_ref_row}:G{итого_ref_row}", [итого_ref], value_input_option="USER_ENTERED")
            ws.format(f"A{итого_ref_row}:G{итого_ref_row}", {"textFormat": {"bold": True}})
            ws.format(f"B{итого_ref_row}:B{итого_ref_row}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
            ws.format(f"C{итого_ref_row}:C{итого_ref_row}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
            ws.format(f"D{итого_ref_row}:F{итого_ref_row}", {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})
            time.sleep(1)

            # QUERY: берёт A,B из основной таблицы + H,I,J,K (эквиваленты) + G (%)
            # label задаёт заголовки столбцов в выводе
            q2 = (
                f'=QUERY(A1:K{n+1};'
                f'"SELECT A,B,H,I,J,K,G WHERE B>0 AND A<>\'ИТОГО\' ORDER BY B DESC '
                f'label A \'Категория\', B \'Сумма (₽)\', H \'Сумма (din)\', '
                f'I \'Сумма (€)\', J \'Сумма ($)\', K \'Сумма (₾)\', G \'%\'";1)'
            )
            ws.update(f"A{query_row}", [[q2]], value_input_option="USER_ENTERED")
            time.sleep(2)

            # Секция 3: Топ-5 расходов
            ws.update(f"A{top5_title_row}", [["🏆 Топ 5 расходов месяца"]])
            ws.format(f"A{top5_title_row}", {"textFormat": {"bold": True}})
            time.sleep(1)

            q5 = (
                f'=QUERY(Расходы!A1:J5000;'
                f'"SELECT A,B,C,G,H WHERE A MATCHES \'{month_key}.*\' '
                f'ORDER BY C DESC LIMIT 5";1)'
            )
            ws.update(f"A{top5_data_row}", [[q5]], value_input_option="USER_ENTERED")
            time.sleep(2)

            # Диаграмма: сначала удаляем старые, затем добавляем новую
            try:
                sp_data = spreadsheet.client.request(
                    'get',
                    f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet.id}",
                    params={'fields': 'sheets(properties/sheetId,charts/chartId)'}
                ).json()
                delete_reqs = []
                for sheet_meta in sp_data.get('sheets', []):
                    if sheet_meta['properties']['sheetId'] == ws.id:
                        for chart in sheet_meta.get('charts', []):
                            delete_reqs.append({"deleteEmbeddedObject": {"objectId": chart['chartId']}})
                if delete_reqs:
                    spreadsheet.batch_update({"requests": delete_reqs})
                    time.sleep(1)
            except Exception as e:
                print(f"    ⚠ Удаление старых диаграмм: {e}")

            try:
                src_start = query_row - 1   # 0-indexed, включает заголовок QUERY
                src_end = query_row + n      # 0-indexed exclusive
                anchor_row = section2_row - 1  # 0-indexed
                spreadsheet.batch_update({"requests": [
                    # Горизонтальный бар — суммы по категориям
                    {"addChart": {
                        "chart": {
                            "spec": {
                                "title": sheet_title,
                                "basicChart": {
                                    "chartType": "BAR",
                                    "legendPosition": "NO_LEGEND",
                                    "axis": [
                                        {"position": "BOTTOM_AXIS", "title": "₽"},
                                        {"position": "LEFT_AXIS",   "title": ""},
                                    ],
                                    "domains": [{"domain": {"sourceRange": {"sources": [{
                                        "sheetId": ws.id,
                                        "startRowIndex": src_start,
                                        "endRowIndex": src_end,
                                        "startColumnIndex": 0,
                                        "endColumnIndex": 1,
                                    }]}}}],
                                    "series": [{"series": {"sourceRange": {"sources": [{
                                        "sheetId": ws.id,
                                        "startRowIndex": src_start,
                                        "endRowIndex": src_end,
                                        "startColumnIndex": 1,
                                        "endColumnIndex": 2,
                                    }]}}, "targetAxis": "BOTTOM_AXIS"}],
                                    "headerCount": 1,
                                }
                            },
                            "position": {"overlayPosition": {
                                "anchorCell": {"sheetId": ws.id, "rowIndex": anchor_row, "columnIndex": 12},
                                "widthPixels": 480, "heightPixels": 320,
                            }}
                        }
                    }},
                    # Круговая диаграмма — доли категорий
                    {"addChart": {
                        "chart": {
                            "spec": {
                                "title": f"{sheet_title} — доли",
                                "pieChart": {
                                    "legendPosition": "RIGHT_LEGEND",
                                    "pieHole": 0,
                                    "domain": {"sourceRange": {"sources": [{
                                        "sheetId": ws.id,
                                        "startRowIndex": src_start,
                                        "endRowIndex": src_end,
                                        "startColumnIndex": 0,
                                        "endColumnIndex": 1,
                                    }]}},
                                    "series": {"sourceRange": {"sources": [{
                                        "sheetId": ws.id,
                                        "startRowIndex": src_start,
                                        "endRowIndex": src_end,
                                        "startColumnIndex": 1,
                                        "endColumnIndex": 2,
                                    }]}},
                                }
                            },
                            "position": {"overlayPosition": {
                                "anchorCell": {"sheetId": ws.id, "rowIndex": anchor_row + 16, "columnIndex": 12},
                                "widthPixels": 480, "heightPixels": 320,
                            }}
                        }
                    }},
                ]})
                time.sleep(3)
            except Exception as e:
                print(f"    ⚠ Диаграммы: {e}")

            print(f"  ✓ {sheet_title}")

    def update_expense_category(self, row: int, category: str):
        """Обновляет категорию расхода в указанной строке (колонка B)."""
        self.expense_sheet.update_cell(row, 2, category)

    def get_records_by_period(self, start: date, end: date) -> list[dict]:
        all_rows = self.sheet.get_all_records(value_render_option="UNFORMATTED_VALUE")
        result = []
        for row in all_rows:
            try:
                row_date = date.fromisoformat(str(row["Дата"]))
                if start <= row_date <= end:
                    result.append({
                        "date": str(row["Дата"]),
                        "client": row["Клиент"],
                        "amount": float(row["Сумма (₽)"]),
                        "description": row["Описание"],
                    })
            except (ValueError, KeyError):
                continue
        return sorted(result, key=lambda x: x["date"])

    def get_expenses_by_period(self, start: date, end: date) -> list[dict]:
        all_rows = self.expense_sheet.get_all_records(value_render_option="UNFORMATTED_VALUE")
        result = []
        for row in all_rows:
            try:
                row_date = date.fromisoformat(str(row["Дата"]))
                if start <= row_date <= end:
                    result.append({
                        "date": str(row["Дата"]),
                        "category": row["Категория"],
                        "amount": float(row["Сумма (₽)"]),
                        "shop": row.get("Магазин", ""),
                        "description": row.get("Описание", ""),
                    })
            except (ValueError, KeyError):
                continue
        return sorted(result, key=lambda x: x["date"])
