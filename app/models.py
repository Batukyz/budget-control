from sqlalchemy import Column, ForeignKey, Integer, String, Boolean, Date, DateTime, Float
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


class Transaction(Base):
    """A single income or expense entry."""

    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    type = Column(String, nullable=False)  # "expense" | "income"
    category = Column(String, nullable=True)
    note = Column(String, nullable=True)
    occurred_on = Column(Date, server_default=func.current_date(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", back_populates="transactions")


class Subscription(Base):
    """A recurring cost (streaming, software, gym, etc.) tracked separately
    from one-off transactions so upcoming renewals can be surfaced."""

    __tablename__ = "subscriptions"

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


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
