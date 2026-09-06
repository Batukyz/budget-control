from sqlalchemy import Column, ForeignKey, Index, Integer, String, Boolean, Date, DateTime, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    transactions = relationship("Transaction", back_populates="owner", cascade="all, delete-orphan")
    subscriptions = relationship("Subscription", back_populates="owner", cascade="all, delete-orphan")
    budget_limits = relationship("BudgetLimit", back_populates="owner", cascade="all, delete-orphan")
    recurring_transactions = relationship(
        "RecurringTransaction", back_populates="owner", cascade="all, delete-orphan"
    )
    credit_cards = relationship("CreditCard", back_populates="owner", cascade="all, delete-orphan")


class Transaction(Base):
    """A single income or expense entry."""

    __tablename__ = "transactions"
    __table_args__ = (Index("ix_transactions_owner_occurred", "owner_id", "occurred_on"),)

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    type = Column(String, nullable=False)  # "expense" | "income"
    category = Column(String, nullable=True)
    note = Column(String, nullable=True)
    occurred_on = Column(Date, server_default=func.current_date(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    recurring_transaction_id = Column(
        Integer, ForeignKey("recurring_transactions.id"), nullable=True
    )

    owner = relationship("User", back_populates="transactions")


class RecurringTransaction(Base):
    """A fixed, regularly repeating income or expense (salary, scholarship, rent, ...)
    that automatically generates real Transaction rows as it comes due, as opposed
    to one-off variable transactions entered manually."""

    __tablename__ = "recurring_transactions"
    __table_args__ = (
        Index("ix_recurring_transactions_owner_active_due", "owner_id", "is_active", "next_due_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    type = Column(String, nullable=False)  # "expense" | "income"
    frequency = Column(String, nullable=False, default="monthly")  # "weekly" | "monthly" | "yearly"
    next_due_date = Column(Date, nullable=False)
    category = Column(String, nullable=True)
    note = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="recurring_transactions")


class Subscription(Base):
    """A recurring cost (streaming, software, gym, etc.) tracked separately
    from one-off transactions so upcoming renewals can be surfaced."""

    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_owner_active_due", "owner_id", "is_active", "next_due_date"),)

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    billing_cycle = Column(String, nullable=False, default="monthly")  # "weekly" | "monthly" | "yearly"
    next_due_date = Column(Date, nullable=False)
    category = Column(String, nullable=True)
    note = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="subscriptions")


class CreditCard(Base):
    """A bank/credit card, tracked for its limit, current debt, and the
    monthly statement (ekstre) and payment due (son ödeme) days."""

    __tablename__ = "credit_cards"
    __table_args__ = (Index("ix_credit_cards_owner", "owner_id"),)

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    bank_name = Column(String, nullable=False)
    card_name = Column(String, nullable=True)
    limit_amount = Column(Float, nullable=False)
    current_debt = Column(Float, nullable=False, default=0)
    statement_day = Column(Integer, nullable=False)  # 1-31, ekstre kesim günü
    due_day = Column(Integer, nullable=False)  # 1-31, son ödeme günü
    note = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="credit_cards")


class BudgetLimit(Base):
    """A monthly spending cap for one category, or the whole budget when category is None."""

    __tablename__ = "budget_limits"
    __table_args__ = (Index("ix_budget_limits_owner_category", "owner_id", "category"),)

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String, nullable=True)
    monthly_limit = Column(Float, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="budget_limits")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
