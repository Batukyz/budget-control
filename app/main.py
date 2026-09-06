import calendar
import csv
import io
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session

from . import models, schemas
from .auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    revoke_refresh_token,
    use_refresh_token,
)
from .database import get_db
from .logging_config import RequestLoggingMiddleware, configure_logging, logger
from .rate_limit import limiter
from .security import hash_password, verify_password

configure_logging()

app = FastAPI(title="Budget Control")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(RequestLoggingMiddleware)
app.mount("/app", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="frontend")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/register", response_model=schemas.UserOut, status_code=201)
@limiter.limit("5/minute")
def register(request: Request, user: schemas.UserCreate, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user.email).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="Email already registered")
    db_user = models.User(email=user.email, hashed_password=hash_password(user.password))
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@app.post("/auth/login", response_model=schemas.Token)
@limiter.limit("5/minute")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return schemas.Token(
        access_token=create_access_token(subject=user.email),
        refresh_token=create_refresh_token(user_id=user.id, db=db),
    )


@app.post("/auth/refresh", response_model=schemas.Token)
def refresh(payload: schemas.RefreshRequest, db: Session = Depends(get_db)):
    user = use_refresh_token(payload.refresh_token, db)
    revoke_refresh_token(payload.refresh_token, db)
    return schemas.Token(
        access_token=create_access_token(subject=user.email),
        refresh_token=create_refresh_token(user_id=user.id, db=db),
    )


@app.post("/auth/logout", status_code=204)
def logout(payload: schemas.LogoutRequest, db: Session = Depends(get_db)):
    revoke_refresh_token(payload.refresh_token, db)


@app.get("/me", response_model=schemas.UserOut)
def read_me(current_user: models.User = Depends(get_current_user)):
    return current_user


@app.put("/me", response_model=schemas.UserOut)
def update_me(
    update: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    if update.email is not None:
        existing = (
            db.query(models.User)
            .filter(models.User.email == update.email, models.User.id != current_user.id)
            .first()
        )
        if existing is not None:
            raise HTTPException(status_code=400, detail="Email already registered")
        current_user.email = update.email
    if update.password is not None:
        current_user.hashed_password = hash_password(update.password)
    db.commit()
    db.refresh(current_user)
    return current_user


def _get_owned_transaction(transaction_id: int, owner_id: int, db: Session) -> models.Transaction:
    transaction = (
        db.query(models.Transaction)
        .filter(models.Transaction.id == transaction_id, models.Transaction.owner_id == owner_id)
        .first()
    )
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction


def _advance_recurring_date(d: date, frequency: str) -> date:
    if frequency == "weekly":
        return d + timedelta(days=7)
    if frequency == "yearly":
        try:
            return d.replace(year=d.year + 1)
        except ValueError:  # Feb 29 on a non-leap target year
            return d.replace(year=d.year + 1, day=28)
    month = d.month + 1 if d.month < 12 else 1
    year = d.year + 1 if d.month == 12 else d.year
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _process_due_recurring_transactions(db: Session, owner_id: int) -> None:
    today = date.today()
    due = (
        db.query(models.RecurringTransaction)
        .filter(
            models.RecurringTransaction.owner_id == owner_id,
            models.RecurringTransaction.is_active.is_(True),
            models.RecurringTransaction.next_due_date <= today,
        )
        .all()
    )
    if not due:
        return
    for recurring in due:
        for _ in range(500):  # safety cap against pathological/infinite loops
            if recurring.next_due_date > today:
                break
            db.add(
                models.Transaction(
                    owner_id=owner_id,
                    amount=recurring.amount,
                    type=recurring.type,
                    category=recurring.category,
                    note=recurring.note or recurring.name,
                    occurred_on=recurring.next_due_date,
                    recurring_transaction_id=recurring.id,
                )
            )
            recurring.next_due_date = _advance_recurring_date(recurring.next_due_date, recurring.frequency)
    db.commit()


@app.post("/transactions", response_model=schemas.TransactionOut, status_code=201)
def create_transaction(
    payload: schemas.TransactionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    data = payload.model_dump()
    if data["occurred_on"] is None:
        data["occurred_on"] = date.today()
    transaction = models.Transaction(owner_id=current_user.id, **data)
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


@app.get("/transactions", response_model=list[schemas.TransactionOut])
def list_transactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    type: Optional[schemas.TransactionType] = None,
    category: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    _process_due_recurring_transactions(db, current_user.id)
    query = db.query(models.Transaction).filter(models.Transaction.owner_id == current_user.id)
    if type is not None:
        query = query.filter(models.Transaction.type == type)
    if category is not None:
        query = query.filter(models.Transaction.category == category)
    if from_date is not None:
        query = query.filter(models.Transaction.occurred_on >= from_date)
    if to_date is not None:
        query = query.filter(models.Transaction.occurred_on <= to_date)
    return (
        query.order_by(models.Transaction.occurred_on.desc(), models.Transaction.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


CSV_COLUMNS = ["occurred_on", "type", "category", "note", "amount"]


@app.get("/transactions/export")
def export_transactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    type: Optional[schemas.TransactionType] = None,
    category: Optional[str] = None,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
):
    query = db.query(models.Transaction).filter(models.Transaction.owner_id == current_user.id)
    if type is not None:
        query = query.filter(models.Transaction.type == type)
    if category is not None:
        query = query.filter(models.Transaction.category == category)
    if from_date is not None:
        query = query.filter(models.Transaction.occurred_on >= from_date)
    if to_date is not None:
        query = query.filter(models.Transaction.occurred_on <= to_date)
    transactions = query.order_by(models.Transaction.occurred_on.desc(), models.Transaction.id.desc()).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for t in transactions:
        writer.writerow([t.occurred_on.isoformat(), t.type, t.category or "", t.note or "", t.amount])
    buffer.seek(0)
    filename = f"islemler_{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/transactions/import", response_model=schemas.TransactionImportResult)
def import_transactions(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    raw = file.file.read().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(raw))
    missing = set(["occurred_on", "type", "amount"]) - set(reader.fieldnames or [])
    if missing:
        raise HTTPException(status_code=400, detail=f"CSV eksik sütun(lar): {', '.join(sorted(missing))}")

    created = 0
    errors: list[str] = []
    new_transactions = []
    for i, row in enumerate(reader, start=2):  # row 1 is the header
        try:
            occurred_on = date.fromisoformat(row["occurred_on"].strip())
            tx_type = row["type"].strip().lower()
            if tx_type not in ("income", "expense"):
                raise ValueError(f"geçersiz tür '{tx_type}'")
            amount = float(row["amount"])
            if amount <= 0:
                raise ValueError("tutar 0'dan büyük olmalı")
        except (KeyError, ValueError, AttributeError) as exc:
            errors.append(f"Satır {i}: {exc}")
            continue
        new_transactions.append(
            models.Transaction(
                owner_id=current_user.id,
                amount=amount,
                type=tx_type,
                category=(row.get("category") or "").strip() or None,
                note=(row.get("note") or "").strip() or None,
                occurred_on=occurred_on,
            )
        )
        created += 1

    db.add_all(new_transactions)
    db.commit()
    return schemas.TransactionImportResult(created=created, skipped=len(errors), errors=errors)


@app.get("/transactions/{transaction_id}", response_model=schemas.TransactionOut)
def get_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return _get_owned_transaction(transaction_id, current_user.id, db)


@app.put("/transactions/{transaction_id}", response_model=schemas.TransactionOut)
def update_transaction(
    transaction_id: int,
    update: schemas.TransactionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    transaction = _get_owned_transaction(transaction_id, current_user.id, db)
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(transaction, field, value)
    db.commit()
    db.refresh(transaction)
    return transaction


@app.delete("/transactions/{transaction_id}", status_code=204)
def delete_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    transaction = _get_owned_transaction(transaction_id, current_user.id, db)
    db.delete(transaction)
    db.commit()


def _get_owned_recurring_transaction(
    recurring_id: int, owner_id: int, db: Session
) -> models.RecurringTransaction:
    recurring = (
        db.query(models.RecurringTransaction)
        .filter(models.RecurringTransaction.id == recurring_id, models.RecurringTransaction.owner_id == owner_id)
        .first()
    )
    if recurring is None:
        raise HTTPException(status_code=404, detail="Recurring transaction not found")
    return recurring


@app.post("/recurring-transactions", response_model=schemas.RecurringTransactionOut, status_code=201)
def create_recurring_transaction(
    payload: schemas.RecurringTransactionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    recurring = models.RecurringTransaction(owner_id=current_user.id, **payload.model_dump())
    db.add(recurring)
    db.commit()
    db.refresh(recurring)
    _process_due_recurring_transactions(db, current_user.id)
    db.refresh(recurring)
    return recurring


@app.get("/recurring-transactions", response_model=list[schemas.RecurringTransactionOut])
def list_recurring_transactions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    is_active: Optional[bool] = None,
):
    _process_due_recurring_transactions(db, current_user.id)
    query = db.query(models.RecurringTransaction).filter(models.RecurringTransaction.owner_id == current_user.id)
    if is_active is not None:
        query = query.filter(models.RecurringTransaction.is_active == is_active)
    return query.order_by(models.RecurringTransaction.next_due_date.asc()).all()


@app.get("/recurring-transactions/{recurring_id}", response_model=schemas.RecurringTransactionOut)
def get_recurring_transaction(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return _get_owned_recurring_transaction(recurring_id, current_user.id, db)


@app.put("/recurring-transactions/{recurring_id}", response_model=schemas.RecurringTransactionOut)
def update_recurring_transaction(
    recurring_id: int,
    update: schemas.RecurringTransactionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    recurring = _get_owned_recurring_transaction(recurring_id, current_user.id, db)
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(recurring, field, value)
    db.commit()
    db.refresh(recurring)
    return recurring


@app.delete("/recurring-transactions/{recurring_id}", status_code=204)
def delete_recurring_transaction(
    recurring_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    recurring = _get_owned_recurring_transaction(recurring_id, current_user.id, db)
    db.query(models.Transaction).filter(models.Transaction.recurring_transaction_id == recurring.id).update(
        {"recurring_transaction_id": None}
    )
    db.delete(recurring)
    db.commit()


def _get_owned_subscription(subscription_id: int, owner_id: int, db: Session) -> models.Subscription:
    subscription = (
        db.query(models.Subscription)
        .filter(models.Subscription.id == subscription_id, models.Subscription.owner_id == owner_id)
        .first()
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return subscription


@app.post("/subscriptions", response_model=schemas.SubscriptionOut, status_code=201)
def create_subscription(
    payload: schemas.SubscriptionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    subscription = models.Subscription(owner_id=current_user.id, **payload.model_dump())
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


@app.get("/subscriptions", response_model=list[schemas.SubscriptionOut])
def list_subscriptions(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    is_active: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
):
    query = db.query(models.Subscription).filter(models.Subscription.owner_id == current_user.id)
    if is_active is not None:
        query = query.filter(models.Subscription.is_active == is_active)
    return (
        query.order_by(models.Subscription.next_due_date.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@app.get("/subscriptions/{subscription_id}", response_model=schemas.SubscriptionOut)
def get_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return _get_owned_subscription(subscription_id, current_user.id, db)


@app.put("/subscriptions/{subscription_id}", response_model=schemas.SubscriptionOut)
def update_subscription(
    subscription_id: int,
    update: schemas.SubscriptionUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    subscription = _get_owned_subscription(subscription_id, current_user.id, db)
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(subscription, field, value)
    db.commit()
    db.refresh(subscription)
    return subscription


@app.delete("/subscriptions/{subscription_id}", status_code=204)
def delete_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    subscription = _get_owned_subscription(subscription_id, current_user.id, db)
    db.delete(subscription)
    db.commit()


_MONTHLY_MULTIPLIER = {"weekly": 52 / 12, "monthly": 1.0, "yearly": 1 / 12}


@app.get("/overview", response_model=schemas.OverviewOut)
def get_overview(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    _process_due_recurring_transactions(db, current_user.id)
    today = date.today()
    month_start = today.replace(day=1)

    month_transactions = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.occurred_on >= month_start,
            models.Transaction.occurred_on <= today,
        )
        .all()
    )
    month_income = sum(t.amount for t in month_transactions if t.type == "income")
    month_expense = sum(t.amount for t in month_transactions if t.type == "expense")

    active_subscriptions = (
        db.query(models.Subscription)
        .filter(models.Subscription.owner_id == current_user.id, models.Subscription.is_active.is_(True))
        .all()
    )
    monthly_subscription_cost = sum(
        s.amount * _MONTHLY_MULTIPLIER.get(s.billing_cycle, 1.0) for s in active_subscriptions
    )
    upcoming_cutoff = today + timedelta(days=7)
    upcoming_subscriptions = sum(1 for s in active_subscriptions if today <= s.next_due_date <= upcoming_cutoff)

    budget_limits = (
        db.query(models.BudgetLimit).filter(models.BudgetLimit.owner_id == current_user.id).all()
    )
    budgets_over_limit = 0
    if budget_limits:
        category_expense: dict = {}
        for t in month_transactions:
            if t.type == "expense":
                category_expense[t.category] = category_expense.get(t.category, 0.0) + t.amount
        for b in budget_limits:
            spent = month_expense if b.category is None else category_expense.get(b.category, 0.0)
            if spent > b.monthly_limit:
                budgets_over_limit += 1

    return schemas.OverviewOut(
        month_income=round(month_income, 2),
        month_expense=round(month_expense, 2),
        net_balance=round(month_income - month_expense, 2),
        monthly_subscription_cost=round(monthly_subscription_cost, 2),
        upcoming_subscriptions=upcoming_subscriptions,
        budgets_over_limit=budgets_over_limit,
    )


def _month_start_offset(base: date, months_back: int) -> date:
    total = base.year * 12 + (base.month - 1) - months_back
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


@app.get("/reports/monthly-trend", response_model=list[schemas.MonthlyTrendItem])
def monthly_trend(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    months: int = Query(6, ge=1, le=24),
):
    today = date.today()
    range_start = _month_start_offset(today, months - 1)
    transactions = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.occurred_on >= range_start,
            models.Transaction.occurred_on <= today,
        )
        .all()
    )
    totals: dict = {}
    for t in transactions:
        key = f"{t.occurred_on.year:04d}-{t.occurred_on.month:02d}"
        entry = totals.setdefault(key, {"income": 0.0, "expense": 0.0})
        entry[t.type] += t.amount

    results = []
    for i in range(months):
        month_date = _month_start_offset(today, months - 1 - i)
        key = f"{month_date.year:04d}-{month_date.month:02d}"
        entry = totals.get(key, {"income": 0.0, "expense": 0.0})
        results.append(
            schemas.MonthlyTrendItem(
                month=key, income=round(entry["income"], 2), expense=round(entry["expense"], 2)
            )
        )
    return results


@app.get("/reports/category-breakdown", response_model=list[schemas.CategoryBreakdownItem])
def category_breakdown(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
    month: Optional[str] = None,
    type: schemas.TransactionType = "expense",
):
    if month is not None:
        try:
            year, month_num = (int(part) for part in month.split("-"))
        except ValueError:
            raise HTTPException(status_code=400, detail="month formatı 'YYYY-MM' olmalı")
    else:
        today = date.today()
        year, month_num = today.year, today.month

    month_start = date(year, month_num, 1)
    month_end = date(year, month_num, calendar.monthrange(year, month_num)[1])

    transactions = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.type == type,
            models.Transaction.occurred_on >= month_start,
            models.Transaction.occurred_on <= month_end,
        )
        .all()
    )
    totals: dict = {}
    for t in transactions:
        key = t.category or "Diğer"
        totals[key] = totals.get(key, 0.0) + t.amount

    return [
        schemas.CategoryBreakdownItem(category=category, amount=round(amount, 2))
        for category, amount in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    ]


def _get_owned_budget(budget_id: int, owner_id: int, db: Session) -> models.BudgetLimit:
    budget = (
        db.query(models.BudgetLimit)
        .filter(models.BudgetLimit.id == budget_id, models.BudgetLimit.owner_id == owner_id)
        .first()
    )
    if budget is None:
        raise HTTPException(status_code=404, detail="Budget limit not found")
    return budget


@app.post("/budgets", response_model=schemas.BudgetLimitOut, status_code=201)
def create_budget(
    payload: schemas.BudgetLimitCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    existing = (
        db.query(models.BudgetLimit)
        .filter(
            models.BudgetLimit.owner_id == current_user.id,
            models.BudgetLimit.category == payload.category,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail="Bu kategori için zaten bir bütçe limiti tanımlı")
    budget = models.BudgetLimit(owner_id=current_user.id, **payload.model_dump())
    db.add(budget)
    db.commit()
    db.refresh(budget)
    return budget


@app.get("/budgets", response_model=list[schemas.BudgetStatusOut])
def list_budgets(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    budgets = (
        db.query(models.BudgetLimit)
        .filter(models.BudgetLimit.owner_id == current_user.id)
        .order_by(models.BudgetLimit.id.asc())
        .all()
    )
    today = date.today()
    month_start = today.replace(day=1)
    month_expenses = (
        db.query(models.Transaction)
        .filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.type == "expense",
            models.Transaction.occurred_on >= month_start,
            models.Transaction.occurred_on <= today,
        )
        .all()
    )
    category_expense: dict = {}
    total_expense = 0.0
    for t in month_expenses:
        total_expense += t.amount
        category_expense[t.category] = category_expense.get(t.category, 0.0) + t.amount

    results = []
    for b in budgets:
        spent = total_expense if b.category is None else category_expense.get(b.category, 0.0)
        results.append(
            schemas.BudgetStatusOut(
                id=b.id,
                category=b.category,
                monthly_limit=b.monthly_limit,
                created_at=b.created_at,
                spent_this_month=round(spent, 2),
                remaining=round(b.monthly_limit - spent, 2),
                is_over_limit=spent > b.monthly_limit,
            )
        )
    return results


@app.put("/budgets/{budget_id}", response_model=schemas.BudgetLimitOut)
def update_budget(
    budget_id: int,
    update: schemas.BudgetLimitUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    budget = _get_owned_budget(budget_id, current_user.id, db)
    budget.monthly_limit = update.monthly_limit
    db.commit()
    db.refresh(budget)
    return budget


@app.delete("/budgets/{budget_id}", status_code=204)
def delete_budget(
    budget_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    budget = _get_owned_budget(budget_id, current_user.id, db)
    db.delete(budget)
    db.commit()


def _get_owned_category(category_id: int, owner_id: int, db: Session) -> models.Category:
    category = (
        db.query(models.Category)
        .filter(models.Category.id == category_id, models.Category.owner_id == owner_id)
        .first()
    )
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    return category


@app.post("/categories", response_model=schemas.CategoryOut, status_code=201)
def create_category(
    payload: schemas.CategoryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    existing = (
        db.query(models.Category)
        .filter(models.Category.owner_id == current_user.id, models.Category.name == payload.name)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail="Bu isimde bir kategori zaten var")
    category = models.Category(owner_id=current_user.id, **payload.model_dump())
    db.add(category)
    db.commit()
    db.refresh(category)
    return category


@app.get("/categories", response_model=list[schemas.CategoryOut])
def list_categories(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Category)
        .filter(models.Category.owner_id == current_user.id)
        .order_by(models.Category.name.asc())
        .all()
    )


@app.put("/categories/{category_id}", response_model=schemas.CategoryOut)
def update_category(
    category_id: int,
    update: schemas.CategoryUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    category = _get_owned_category(category_id, current_user.id, db)
    if update.name is not None and update.name != category.name:
        existing = (
            db.query(models.Category)
            .filter(
                models.Category.owner_id == current_user.id,
                models.Category.name == update.name,
                models.Category.id != category_id,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(status_code=400, detail="Bu isimde bir kategori zaten var")
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(category, field, value)
    db.commit()
    db.refresh(category)
    return category


@app.delete("/categories/{category_id}", status_code=204)
def delete_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    category = _get_owned_category(category_id, current_user.id, db)
    db.delete(category)
    db.commit()


def _next_occurrence_of_day(today: date, day: int) -> date:
    """The next date (today included) that falls on the given day-of-month."""
    this_month_day = min(day, calendar.monthrange(today.year, today.month)[1])
    candidate = today.replace(day=this_month_day)
    if candidate >= today:
        return candidate
    month = today.month + 1 if today.month < 12 else 1
    year = today.year + 1 if today.month == 12 else today.year
    next_month_day = min(day, calendar.monthrange(year, month)[1])
    return date(year, month, next_month_day)


def _credit_card_to_out(card: models.CreditCard) -> schemas.CreditCardOut:
    today = date.today()
    return schemas.CreditCardOut(
        id=card.id,
        bank_name=card.bank_name,
        card_name=card.card_name,
        limit_amount=card.limit_amount,
        current_debt=card.current_debt,
        statement_day=card.statement_day,
        due_day=card.due_day,
        note=card.note,
        created_at=card.created_at,
        available_limit=round(card.limit_amount - card.current_debt, 2),
        next_statement_date=_next_occurrence_of_day(today, card.statement_day),
        next_due_date=_next_occurrence_of_day(today, card.due_day),
    )


def _get_owned_credit_card(card_id: int, owner_id: int, db: Session) -> models.CreditCard:
    card = (
        db.query(models.CreditCard)
        .filter(models.CreditCard.id == card_id, models.CreditCard.owner_id == owner_id)
        .first()
    )
    if card is None:
        raise HTTPException(status_code=404, detail="Credit card not found")
    return card


@app.post("/credit-cards", response_model=schemas.CreditCardOut, status_code=201)
def create_credit_card(
    payload: schemas.CreditCardCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    card = models.CreditCard(owner_id=current_user.id, **payload.model_dump())
    db.add(card)
    db.commit()
    db.refresh(card)
    return _credit_card_to_out(card)


@app.get("/credit-cards", response_model=list[schemas.CreditCardOut])
def list_credit_cards(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    cards = (
        db.query(models.CreditCard)
        .filter(models.CreditCard.owner_id == current_user.id)
        .order_by(models.CreditCard.id.asc())
        .all()
    )
    return [_credit_card_to_out(c) for c in cards]


@app.get("/credit-cards/{card_id}", response_model=schemas.CreditCardOut)
def get_credit_card(
    card_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return _credit_card_to_out(_get_owned_credit_card(card_id, current_user.id, db))


@app.put("/credit-cards/{card_id}", response_model=schemas.CreditCardOut)
def update_credit_card(
    card_id: int,
    update: schemas.CreditCardUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    card = _get_owned_credit_card(card_id, current_user.id, db)
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(card, field, value)
    db.commit()
    db.refresh(card)
    return _credit_card_to_out(card)


@app.delete("/credit-cards/{card_id}", status_code=204)
def delete_credit_card(
    card_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    card = _get_owned_credit_card(card_id, current_user.id, db)
    db.delete(card)
    db.commit()
