"""Legacy native finance models kept only for migration/compatibility checks."""

import uuid
from datetime import datetime, timezone

from app.core.database import Base
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text


class FinanceWorkspace(Base):  # pylint: disable=too-few-public-methods
    __tablename__ = "finance_workspaces"

    kb_id = Column(String, primary_key=True)
    currency = Column(String, nullable=False, default="USD")  # ISO 4217
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))


class FinanceAccount(Base):  # pylint: disable=too-few-public-methods
    __tablename__ = "finance_accounts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    account_type = Column(String, nullable=False)  # asset|expense|revenue|liability
    opening_balance = Column(Float, nullable=False, default=0.0)
    archived = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))


class FinanceTransaction(Base):  # pylint: disable=too-few-public-methods
    __tablename__ = "finance_transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    kb_id = Column(String, nullable=False, index=True)
    date = Column(DateTime(timezone=True), nullable=False)
    description = Column(Text, nullable=False, default="")
    amount = Column(Float, nullable=False)
    account_id = Column(String, ForeignKey("finance_accounts.id"), nullable=False)
    transfer_account_id = Column(String, ForeignKey("finance_accounts.id"), nullable=True)
    category = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(timezone.utc))
