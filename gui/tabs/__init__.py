"""タブ実装"""
from .base import BaseTab
from .settings_tab import SettingsTab
from .inquiry_tab import InquiryTab
from .schema_edit_tab import SchemaEditTab
from .data_load_tab import DataLoadTab
from .tagging_tab import TaggingTab
from .ranking_tab import RankingTab
from .export_tab import ExportTab

__all__ = [
    "BaseTab",
    "SettingsTab",
    "InquiryTab",
    "SchemaEditTab",
    "DataLoadTab",
    "TaggingTab",
    "RankingTab",
    "ExportTab",
]
