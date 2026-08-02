"""Key-value app settings (replaces runtime_config.json)."""

from app.core.database import Base
from sqlalchemy import Column, String, Text


class AppSetting(Base):  # pylint: disable=too-few-public-methods
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=True)
