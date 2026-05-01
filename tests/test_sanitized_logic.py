import os

os.environ.setdefault("TELEGRAM_TOKEN", "test-telegram-token")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("GOOGLE_SPREADSHEET_ID", "test-spreadsheet-id")
os.environ.setdefault("GOOGLE_CREDENTIALS_JSON", "credentials.example.json")
os.environ.setdefault("ALLOWED_USER_ID", "123456789")

from expense_parser import _group_items_to_categories
from parser import normalize_client


def test_normalize_client_uses_demo_aliases():
    assert normalize_client("первый клиент") == "Demo Client A"
    assert normalize_client("client b") == "Demo Client B"


def test_receipt_items_are_grouped_by_fixed_category():
    items = [
        {"name": "Terea Amber", "amount": 500, "category": "Прочее"},
        {"name": "Zajecarsko pivo", "amount": 300, "category": "Напитки"},
        {"name": "Jabuka", "amount": 120, "category": "Продукты"},
    ]

    grouped = {row["category"]: row["amount"] for row in _group_items_to_categories(items)}

    assert grouped["Табак"] == 500
    assert grouped["Алкоголь"] == 300
    assert grouped["Овощи и фрукты"] == 120
