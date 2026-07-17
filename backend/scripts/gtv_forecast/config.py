"""Paths and table import specs for the GTV forecast pilot."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "_data"
PARQUET_DIR = DATA_DIR / "parquet"
REPORT_DIR = DATA_DIR / "reports"
MODEL_DIR = DATA_DIR / "models"
DB_PATH = DATA_DIR / "gtv.duckdb"

# Default dump roots (override with GTV_DATA_ROOT / GTV_MID_ROOT)
DEFAULT_DUMP_ROOT = Path("/Users/ssyb/Downloads/data/lyy_manage")
DEFAULT_MID_ROOT = Path("/Users/ssyb/Downloads/data/lyy_mid")
DEFAULT_DATA_PARENT = Path("/Users/ssyb/Downloads/data")

# Columns dropped on import (PII / bulky / credentials)
PII_OR_BULKY: dict[str, set[str]] = {
    "e_sys_user": {
        "phonenumber",
        "email",
        "password",
        "card_no",
        "id_photo",
        "privacy_number",
        "avatar",
        "qr_code",
        "xianyu_account",
        "wuba_account",
        "login_ip",
    },
    "e_sys_dept": {"phone", "email", "leader"},
    "e_clue_base": {"phone", "wechat", "email", "custom_name"},
    "e_project_sign": {
        "file",
        "confirm_file",
        "rent_agreement_file",
        "custom_name",
        "custom_tax",
        "custom_number",
        "kingdee_number",
    },
    "e_plant_base": {"vr_link", "remark", "address"},
    "e_warehouse_base": {"vr_link", "remark", "address"},
    "e_office_base": {"vr_link", "remark", "address"},
    "e_office_room": {"vr_link", "remark"},
    "e_project_follow": {"content", "follow_content", "remark"},
    "e_plant_follow": {"content", "follow_content", "remark"},
    "e_warehouse_follow": {"content", "follow_content", "remark"},
    "e_office_room_follow": {"content", "follow_content", "remark"},
    "e_project_show": {"remark", "content"},
    "e_project_negotiation": {"content", "remark"},
    "e_clue_clueneed": {"remark", "content"},
}

# Tables required for G0/G1
REQUIRED_TABLES = [
    "e_sys_user",
    "e_sys_dept",
    "r_sys_user_sys_dept",
    "e_plant_base",
    "e_warehouse_base",
    "e_office_base",
    "e_office_room",
    "e_plant_rent",
    "e_warehouse_rent",
    "e_office_room_rent",
    "e_clue_base",
    "e_project_base",
    "e_project_follow",
    "e_project_show",
    "e_plant_follow",
    "e_warehouse_follow",
    "e_office_room_follow",
    "e_housesource_sign_record",
    "e_project_sign",
    "e_project_sign_commission",
    "e_plant_operate_record",
]

# Optional but useful (P0 + P1 for this round)
OPTIONAL_TABLES = [
    "e_warehouse_operation_record",
    "e_office_room_operation_record",
    "e_clue_dealresult",
    # P0: 意向匹配 / 回款 / mid 定价分
    "e_clue_clueneed",
    "e_clue_intentarea",
    "e_project_carrier",
    "e_project_refund",
    "e_carrier_carrier_sort_score_info",
    "e_carrier_rent_price_range",
    "e_carrier_sale_price_range",
    # P1
    "e_project_invite",
    "e_project_negotiation",
    "e_project_end",
]

# Table → dump subdirectory under Downloads/data (default lyy_manage)
TABLE_DUMP_DB: dict[str, str] = {
    "e_carrier_carrier_sort_score_info": "lyy_mid",
    "e_carrier_rent_price_range": "lyy_mid",
    "e_carrier_sale_price_range": "lyy_mid",
}

SIGN_TYPE_RENT = {1, 3}
SIGN_TYPE_SALE = {2, 4}
LISTING_TYPE = {1: "plant", 2: "office", 3: "warehouse"}

# Backtest defaults (short history dump)
HORIZON_DAYS = 60
TRAIN_LOOKBACK_DAYS = 180  # ~6 months (dump history ~1y)
NEG_POS_RATIO = 30
RANDOM_SEED = 42

# Negotiate what-if defaults (人工假设，后续可校准)
DEFAULT_NEGO_SUCCESS_RATE = 0.30
DEFAULT_NEGO_CONCESSION_PCT = 0.05
