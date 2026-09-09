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
    category: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=1000)
    occurred_on: Optional[date] = None


class TransactionUpdate(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    type: Optional[TransactionType] = None
    category: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=1000)
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
    recurring_transaction_id: Optional[int] = None


class TransactionImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str]


BillingCycle = Literal["weekly", "monthly", "yearly"]


class RecurringTransactionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)
    type: TransactionType
    frequency: BillingCycle = "monthly"
    next_due_date: date
    category: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=1000)


class RecurringTransactionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    amount: Optional[float] = Field(default=None, gt=0)
    type: Optional[TransactionType] = None
    frequency: Optional[BillingCycle] = None
    next_due_date: Optional[date] = None
    category: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=1000)
    is_active: Optional[bool] = None


class RecurringTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    amount: float
    type: TransactionType
    frequency: BillingCycle
    next_due_date: date
    category: Optional[str] = None
    note: Optional[str] = None
    is_active: bool
    created_at: datetime


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    amount: float = Field(gt=0)
    billing_cycle: BillingCycle = "monthly"
    next_due_date: date
    category: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=1000)


class SubscriptionUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    amount: Optional[float] = Field(default=None, gt=0)
    billing_cycle: Optional[BillingCycle] = None
    next_due_date: Optional[date] = None
    category: Optional[str] = Field(default=None, max_length=100)
    note: Optional[str] = Field(default=None, max_length=1000)
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
    last_paid_date: Optional[date] = None
    created_at: datetime
    is_paid_this_cycle: bool


class SubscriptionPayOut(BaseModel):
    subscription: SubscriptionOut
    transaction: TransactionOut


class OverviewOut(BaseModel):
    month_income: float
    month_expense: float
    net_balance: float
    monthly_subscription_cost: float
    upcoming_subscriptions: int
    budgets_over_limit: int


CategoryType = Literal["expense", "income", "both"]


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    type: CategoryType = "both"


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    type: Optional[CategoryType] = None


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    type: CategoryType
    created_at: datetime


class CategoryBreakdownItem(BaseModel):
    category: str
    amount: float


class MonthlyTrendItem(BaseModel):
    month: str  # "YYYY-MM"
    income: float
    expense: float


class BudgetLimitCreate(BaseModel):
    category: Optional[str] = Field(default=None, max_length=100)
    monthly_limit: float = Field(gt=0)


class BudgetLimitUpdate(BaseModel):
    monthly_limit: float = Field(gt=0)


class BudgetLimitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: Optional[str] = None
    monthly_limit: float
    created_at: datetime


class BudgetStatusOut(BudgetLimitOut):
    spent_this_month: float
    remaining: float
    is_over_limit: bool


class CreditCardCreate(BaseModel):
    bank_name: str = Field(min_length=1, max_length=200)
    card_name: Optional[str] = Field(default=None, max_length=200)
    limit_amount: float = Field(gt=0)
    current_debt: float = Field(default=0, ge=0)
    statement_day: int = Field(ge=1, le=31)
    due_day: int = Field(ge=1, le=31)
    note: Optional[str] = Field(default=None, max_length=1000)


class CreditCardUpdate(BaseModel):
    bank_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    card_name: Optional[str] = Field(default=None, max_length=200)
    limit_amount: Optional[float] = Field(default=None, gt=0)
    current_debt: Optional[float] = Field(default=None, ge=0)
    statement_day: Optional[int] = Field(default=None, ge=1, le=31)
    due_day: Optional[int] = Field(default=None, ge=1, le=31)
    note: Optional[str] = Field(default=None, max_length=1000)


class CreditCardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    bank_name: str
    card_name: Optional[str] = None
    limit_amount: float
    current_debt: float
    statement_day: int
    due_day: int
    note: Optional[str] = None
    created_at: datetime
    available_limit: float
    next_statement_date: date
    next_due_date: date
