from datetime import date, datetime
from typing import Optional, Literal

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    email: str
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    created_at: datetime


class UserUpdate(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = Field(default=None, min_length=8)


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class MessageOut(BaseModel):
    detail: str


TransactionType = Literal["expense", "income"]


class TransactionCreate(BaseModel):
    amount: float = Field(gt=0)
    type: TransactionType
    category: Optional[str] = None
    note: Optional[str] = None
    occurred_on: Optional[date] = None


class TransactionUpdate(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    type: Optional[TransactionType] = None
    category: Optional[str] = None
    note: Optional[str] = None
    occurred_on: Optional[date] = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: float
    type: TransactionType
    category: Optional[str] = None
    note: Optional[str] = None
    occurred_on: date
    created_at: datetime


BillingCycle = Literal["weekly", "monthly", "yearly"]


class SubscriptionCreate(BaseModel):
    name: str
    amount: float = Field(gt=0)
    billing_cycle: BillingCycle = "monthly"
    next_due_date: date
    category: Optional[str] = None
    note: Optional[str] = None


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = Field(default=None, gt=0)
    billing_cycle: Optional[BillingCycle] = None
    next_due_date: Optional[date] = None
    category: Optional[str] = None
    note: Optional[str] = None
    is_active: Optional[bool] = None


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    amount: float
    billing_cycle: BillingCycle
    next_due_date: date
    category: Optional[str] = None
    note: Optional[str] = None
    is_active: bool
    created_at: datetime


class OverviewOut(BaseModel):
    month_income: float
    month_expense: float
    net_balance: float
    monthly_subscription_cost: float
    upcoming_subscriptions: int
