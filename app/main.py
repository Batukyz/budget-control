import calendar
import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import func, or_, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import models, schemas
from .auth import (
    APP_ENV,
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
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Health check database failure")
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ok"}


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Keep browser credentials out of JavaScript while retaining API token compatibility."""
    common = {
        "httponly": True,
        "secure": APP_ENV in {"production", "prod"},
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie("access_token", access_token, max_age=30 * 60, **common)
    response.set_cookie("refresh_token", refresh_token, max_age=30 * 24 * 60 * 60, **common)


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


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
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if user is None or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    access_token = create_access_token(subject=user.email)
    refresh_token = create_refresh_token(user_id=user.id, db=db)
    _set_auth_cookies(response, access_token, refresh_token)
    return schemas.Token(access_token=access_token, refresh_token=refresh_token)


@app.post("/auth/refresh", response_model=schemas.Token)
def refresh(
    request: Request,
    response: Response,
    payload: Optional[schemas.RefreshRequest] = None,
    db: Session = Depends(get_db),
):
    raw_token = (payload.refresh_token if payload is not None else None) or request.cookies.get("refresh_token")
    if not raw_token:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    user = use_refresh_token(raw_token, db)
    revoke_refresh_token(raw_token, db)
    access_token = create_access_token(subject=user.email)
    refresh_token = create_refresh_token(user_id=user.id, db=db)
    _set_auth_cookies(response, access_token, refresh_token)
    return schemas.Token(access_token=access_token, refresh_token=refresh_token)


@app.post("/auth/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    payload: Optional[schemas.LogoutRequest] = None,
    db: Session = Depends(get_db),
):
    raw_token = (payload.refresh_token if payload is not None else None) or request.cookies.get("refresh_token")
    if raw_token:
        revoke_refresh_token(raw_token, db)
    _clear_auth_cookies(response)


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


def _adjust_card_debt(db: Session, card_id: int, delta: float) -> None:
    """Nudges a credit card's current_debt by delta (never below zero) to keep it in
    sync with the expense transactions charged to it."""
    card = db.query(models.CreditCard).filter(models.CreditCard.id == card_id).first()
    if card is not None:
        card.current_debt = max(0.0, card.current_debt + delta)


def _advance_by_cycle(d: date, frequency: str) -> date:
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


def _process_due_recurring_transactions(db: Session, owner_id: int) -> int:
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
        return 0
    created = 0
    for recurring in due:
        for _ in range(500):  # safety cap against pathological/infinite loops
            if recurring.next_due_date > today:
                break
            occurrence_date = recurring.next_due_date
            exists = db.query(models.Transaction.id).filter(
                models.Transaction.owner_id == owner_id,
                models.Transaction.recurring_transaction_id == recurring.id,
                models.Transaction.occurred_on == occurrence_date,
            ).first()
            if not exists:
                db.add(models.Transaction(
                    owner_id=owner_id, amount=recurring.amount, type=recurring.type,
                    category=recurring.category, note=recurring.note or recurring.name,
                    occurred_on=occurrence_date, recurring_transaction_id=recurring.id,
                ))
                created += 1
            recurring.next_due_date = _advance_by_cycle(recurring.next_due_date, recurring.frequency)
    db.commit()
    return created


@app.post("/transactions", response_model=schemas.TransactionOut, status_code=201)
def create_transaction(
    payload: schemas.TransactionCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    data = payload.model_dump()
    if data["occurred_on"] is None:
        data["occurred_on"] = date.today()
    if data["credit_card_id"] is not None:
        if data["type"] != "expense":
            raise HTTPException(status_code=400, detail="Sadece gider işlemleri bir krediye bağlanabilir")
        card = _get_owned_credit_card(data["credit_card_id"], current_user.id, db)
        card.current_debt += data["amount"]
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
    search: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
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
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(models.Transaction.note.ilike(like), models.Transaction.category.ilike(like))
        )
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
    search: Optional[str] = None,
):
    query = db.query(models.Transaction).filter(models.Transaction.owner_id == current_user.id)
    if type is not None:
        query = query.filter(models.Transaction.type == type)
    if category is not None:
        query = query.filter(models.Transaction.category == category)
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(models.Transaction.note.ilike(like), models.Transaction.category.ilike(like))
        )
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
    updates = update.model_dump(exclude_unset=True)

    new_type = updates.get("type", transaction.type)
    new_amount = updates.get("amount", transaction.amount)
    new_card_id = updates.get("credit_card_id", transaction.credit_card_id)
    if new_card_id is not None and new_type != "expense":
        raise HTTPException(status_code=400, detail="Sadece gider işlemleri bir krediye bağlanabilir")

    new_card = _get_owned_credit_card(new_card_id, current_user.id, db) if new_card_id is not None else None
    old_card_id = transaction.credit_card_id
    old_amount = transaction.amount

    for field, value in updates.items():
        setattr(transaction, field, value)

    if old_card_id != new_card_id:
        if old_card_id is not None:
            _adjust_card_debt(db, old_card_id, -old_amount)
        if new_card is not None:
            new_card.current_debt += new_amount
    elif new_card is not None and new_amount != old_amount:
        new_card.current_debt = max(0.0, new_card.current_debt + (new_amount - old_amount))

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
    if transaction.credit_card_id is not None:
        _adjust_card_debt(db, transaction.credit_card_id, -transaction.amount)
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
    query = db.query(models.RecurringTransaction).filter(models.RecurringTransaction.owner_id == current_user.id)
    if is_active is not None:
        query = query.filter(models.RecurringTransaction.is_active == is_active)
    return query.order_by(models.RecurringTransaction.next_due_date.asc()).all()


@app.post("/recurring-transactions/process-due", response_model=schemas.RecurringProcessResult)
def process_due_recurring_transactions(
    db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)
):
    return schemas.RecurringProcessResult(created=_process_due_recurring_transactions(db, current_user.id))


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


def _is_paid_this_cycle(last_paid_date: Optional[date], billing_cycle: str, today: date) -> bool:
    if last_paid_date is None or last_paid_date > today:
        return False
    if billing_cycle == "weekly":
        return (today - last_paid_date).days < 7
    if billing_cycle == "yearly":
        return last_paid_date.year == today.year
    return last_paid_date.year == today.year and last_paid_date.month == today.month


def _subscription_to_out(subscription: models.Subscription) -> schemas.SubscriptionOut:
    return schemas.SubscriptionOut(
        id=subscription.id,
        name=subscription.name,
        amount=subscription.amount,
        billing_cycle=subscription.billing_cycle,
        next_due_date=subscription.next_due_date,
        category=subscription.category,
        note=subscription.note,
        is_active=subscription.is_active,
        last_paid_date=subscription.last_paid_date,
        created_at=subscription.created_at,
        is_paid_this_cycle=_is_paid_this_cycle(subscription.last_paid_date, subscription.billing_cycle, date.today()),
    )


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
    return _subscription_to_out(subscription)


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
    subscriptions = (
        query.order_by(models.Subscription.next_due_date.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return [_subscription_to_out(s) for s in subscriptions]


@app.get("/subscriptions/{subscription_id}", response_model=schemas.SubscriptionOut)
def get_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return _subscription_to_out(_get_owned_subscription(subscription_id, current_user.id, db))


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
    return _subscription_to_out(subscription)


@app.post("/subscriptions/{subscription_id}/pay", response_model=schemas.SubscriptionPayOut)
def pay_subscription(
    subscription_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    subscription = _get_owned_subscription(subscription_id, current_user.id, db)
    transaction = models.Transaction(
        owner_id=current_user.id,
        amount=subscription.amount,
        type="expense",
        category=subscription.category,
        note=subscription.note or subscription.name,
        occurred_on=date.today(),
    )
    db.add(transaction)
    subscription.last_paid_date = date.today()
    subscription.next_due_date = _advance_by_cycle(subscription.next_due_date, subscription.billing_cycle)
    db.commit()
    db.refresh(transaction)
    db.refresh(subscription)
    return schemas.SubscriptionPayOut(subscription=_subscription_to_out(subscription), transaction=transaction)


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


def _normalize_category(category: Optional[str]) -> str:
    """Case/whitespace-insensitive key so 'Market' and 'market' are treated
    as the same budget category instead of silently splitting spend totals."""
    return (category or "").strip().lower()


def _sum_amount(db: Session, owner_id: int, type_: str, start: date, end: date) -> float:
    total = (
        db.query(func.coalesce(func.sum(models.Transaction.amount), 0.0))
        .filter(
            models.Transaction.owner_id == owner_id,
            models.Transaction.type == type_,
            models.Transaction.occurred_on >= start,
            models.Transaction.occurred_on <= end,
        )
        .scalar()
    )
    return total or 0.0


def _month_category_expense(db: Session, owner_id: int, start: date, end: date) -> dict:
    """Normalized-category -> summed expense amount for the date range, aggregated in SQL
    so a month with thousands of transactions doesn't have to be pulled row-by-row into Python."""
    category_key = func.lower(func.trim(func.coalesce(models.Transaction.category, ""))).label("category_key")
    rows = (
        db.query(category_key, func.sum(models.Transaction.amount))
        .filter(
            models.Transaction.owner_id == owner_id,
            models.Transaction.type == "expense",
            models.Transaction.occurred_on >= start,
            models.Transaction.occurred_on <= end,
        )
        .group_by(category_key)
        .all()
    )
    return {key: total for key, total in rows}


@app.get("/overview", response_model=schemas.OverviewOut)
def get_overview(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    today = date.today()
    month_start = today.replace(day=1)

    category_expense = _month_category_expense(db, current_user.id, month_start, today)
    month_expense = sum(category_expense.values())
    month_income = _sum_amount(db, current_user.id, "income", month_start, today)

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
    for b in budget_limits:
        spent = month_expense if b.category is None else category_expense.get(_normalize_category(b.category), 0.0)
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
    year_expr = func.extract("year", models.Transaction.occurred_on).label("year")
    month_expr = func.extract("month", models.Transaction.occurred_on).label("month")
    rows = (
        db.query(year_expr, month_expr, models.Transaction.type, func.sum(models.Transaction.amount))
        .filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.occurred_on >= range_start,
            models.Transaction.occurred_on <= today,
        )
        .group_by(year_expr, month_expr, models.Transaction.type)
        .all()
    )
    totals: dict = {}
    for year, month_num, type_, total in rows:
        key = f"{int(year):04d}-{int(month_num):02d}"
        entry = totals.setdefault(key, {"income": 0.0, "expense": 0.0})
        entry[type_] = total

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

    rows = (
        db.query(models.Transaction.category, func.sum(models.Transaction.amount))
        .filter(
            models.Transaction.owner_id == current_user.id,
            models.Transaction.type == type,
            models.Transaction.occurred_on >= month_start,
            models.Transaction.occurred_on <= month_end,
        )
        .group_by(models.Transaction.category)
        .all()
    )
    totals: dict = {}
    for category, total in rows:
        key = category or "Diğer"
        totals[key] = totals.get(key, 0.0) + total

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
    owner_budgets = db.query(models.BudgetLimit).filter(models.BudgetLimit.owner_id == current_user.id).all()
    if any(_normalize_category(b.category) == _normalize_category(payload.category) for b in owner_budgets):
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
    category_expense = _month_category_expense(db, current_user.id, month_start, today)
    total_expense = sum(category_expense.values())

    results = []
    for b in budgets:
        spent = total_expense if b.category is None else category_expense.get(_normalize_category(b.category), 0.0)
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
    name = payload.name.strip()
    existing = (
        db.query(models.Category)
        .filter(
            models.Category.owner_id == current_user.id,
            func.lower(func.trim(models.Category.name)) == _normalize_category(name),
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=400, detail="Bu isimde bir kategori zaten var")
    category = models.Category(owner_id=current_user.id, name=name, type=payload.type)
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
    new_name = update.name.strip() if update.name is not None else None
    if new_name is not None and new_name != category.name:
        existing = (
            db.query(models.Category)
            .filter(
                models.Category.owner_id == current_user.id,
                func.lower(func.trim(models.Category.name)) == _normalize_category(new_name),
                models.Category.id != category_id,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(status_code=400, detail="Bu isimde bir kategori zaten var")
        old_key = _normalize_category(category.name)
        category_key = func.lower(func.trim(models.Transaction.category))
        db.query(models.Transaction).filter(
            models.Transaction.owner_id == current_user.id, category_key == old_key
        ).update({"category": new_name}, synchronize_session=False)
        db.query(models.Subscription).filter(
            models.Subscription.owner_id == current_user.id,
            func.lower(func.trim(models.Subscription.category)) == old_key,
        ).update({"category": new_name}, synchronize_session=False)
        db.query(models.RecurringTransaction).filter(
            models.RecurringTransaction.owner_id == current_user.id,
            func.lower(func.trim(models.RecurringTransaction.category)) == old_key,
        ).update({"category": new_name}, synchronize_session=False)
        db.query(models.BudgetLimit).filter(
            models.BudgetLimit.owner_id == current_user.id,
            func.lower(func.trim(models.BudgetLimit.category)) == old_key,
        ).update({"category": new_name}, synchronize_session=False)
    updates = update.model_dump(exclude_unset=True)
    if new_name is not None:
        updates["name"] = new_name
    for field, value in updates.items():
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
    total_installment_debt = 0.0
    active_installment_count = 0
    if hasattr(card, "installment_plans") and card.installment_plans:
        for plan in card.installment_plans:
            if plan.status == "active":
                active_installment_count += 1
                for p in plan.payments:
                    if p.status == "pending":
                        total_installment_debt += p.amount
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
        total_installment_debt=round(total_installment_debt, 2),
        active_installment_count=active_installment_count,
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
    unpaid_installments = (
        db.query(models.InstallmentPayment)
        .join(models.InstallmentPlan, models.InstallmentPayment.installment_plan_id == models.InstallmentPlan.id)
        .filter(
            models.InstallmentPlan.credit_card_id == card.id,
            models.InstallmentPlan.owner_id == current_user.id,
            models.InstallmentPayment.status == "pending",
        )
        .count()
    )
    if unpaid_installments > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Bu kartın devam eden {unpaid_installments} taksit ödemesi bulunuyor. Kartı silmeden önce bu planları yönetmelisiniz.",
        )
    db.query(models.Transaction).filter(models.Transaction.credit_card_id == card.id).update(
        {"credit_card_id": None}
    )
    db.delete(card)
    db.commit()


def _compute_installment_amounts(total_amount: float, count: int) -> list[float]:
    total_cents = round(total_amount * 100)
    base_cents = total_cents // count
    remainder = total_cents % count
    amounts = []
    for i in range(count):
        cents = base_cents + (1 if i >= count - remainder else 0)
        amounts.append(round(cents / 100.0, 2))
    return amounts


def _advance_by_month(base_date: date, month_offset: int, anchor_day: int) -> date:
    total_month = (base_date.year * 12 + (base_date.month - 1)) + month_offset
    year = total_month // 12
    month = (total_month % 12) + 1
    max_day = calendar.monthrange(year, month)[1]
    day = min(anchor_day, max_day)
    return date(year, month, day)


def _get_owned_installment_plan(plan_id: int, owner_id: int, db: Session) -> models.InstallmentPlan:
    plan = (
        db.query(models.InstallmentPlan)
        .filter(models.InstallmentPlan.id == plan_id, models.InstallmentPlan.owner_id == owner_id)
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Installment plan not found")
    return plan


def _installment_plan_to_out(plan: models.InstallmentPlan) -> schemas.InstallmentPlanOut:
    payments_out = [
        schemas.InstallmentPaymentOut(
            id=p.id,
            installment_plan_id=p.installment_plan_id,
            installment_number=p.installment_number,
            amount=p.amount,
            due_date=p.due_date,
            paid_at=p.paid_at,
            status=p.status,
            transaction_id=p.transaction_id,
        )
        for p in plan.payments
    ]
    paid_payments = [p for p in plan.payments if p.status == "paid"]
    paid_count = len(paid_payments)
    paid_amount = round(sum(p.amount for p in paid_payments), 2)
    remaining_amount = round(max(0.0, plan.total_amount - paid_amount), 2)
    card_name = plan.credit_card.card_name if plan.credit_card else None
    bank_name = plan.credit_card.bank_name if plan.credit_card else None

    return schemas.InstallmentPlanOut(
        id=plan.id,
        credit_card_id=plan.credit_card_id,
        description=plan.description,
        category=plan.category,
        total_amount=plan.total_amount,
        installment_count=plan.installment_count,
        installment_amount=plan.installment_amount,
        first_due_date=plan.first_due_date,
        status=plan.status,
        created_at=plan.created_at,
        payments=payments_out,
        paid_count=paid_count,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        card_name=card_name,
        bank_name=bank_name,
    )


@app.post("/installments", response_model=schemas.InstallmentPlanOut, status_code=201)
def create_installment_plan(
    payload: schemas.InstallmentPlanCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    card = _get_owned_credit_card(payload.credit_card_id, current_user.id, db)
    base_date = payload.first_due_date or date.today()
    amounts = _compute_installment_amounts(payload.total_amount, payload.installment_count)

    plan = models.InstallmentPlan(
        owner_id=current_user.id,
        credit_card_id=card.id,
        description=payload.description.strip(),
        category=payload.category,
        total_amount=round(payload.total_amount, 2),
        installment_count=payload.installment_count,
        installment_amount=round(payload.total_amount / payload.installment_count, 2),
        first_due_date=base_date,
        status="active",
    )
    db.add(plan)
    db.flush()

    for i in range(payload.installment_count):
        due_date = _advance_by_month(base_date, i, base_date.day)
        payment = models.InstallmentPayment(
            installment_plan_id=plan.id,
            installment_number=i + 1,
            amount=amounts[i],
            due_date=due_date,
            status="pending",
        )
        db.add(payment)

    db.commit()
    db.refresh(plan)
    return _installment_plan_to_out(plan)


@app.get("/installments", response_model=list[schemas.InstallmentPlanOut])
def list_installment_plans(
    status: Optional[str] = None,
    credit_card_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    query = db.query(models.InstallmentPlan).filter(models.InstallmentPlan.owner_id == current_user.id)
    if status is not None:
        query = query.filter(models.InstallmentPlan.status == status)
    if credit_card_id is not None:
        query = query.filter(models.InstallmentPlan.credit_card_id == credit_card_id)
    plans = query.order_by(models.InstallmentPlan.id.desc()).all()
    return [_installment_plan_to_out(p) for p in plans]


@app.get("/installments/{plan_id}", response_model=schemas.InstallmentPlanOut)
def get_installment_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    plan = _get_owned_installment_plan(plan_id, current_user.id, db)
    return _installment_plan_to_out(plan)


@app.put("/installments/{plan_id}", response_model=schemas.InstallmentPlanOut)
def update_installment_plan(
    plan_id: int,
    update: schemas.InstallmentPlanUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    plan = _get_owned_installment_plan(plan_id, current_user.id, db)
    if update.description is not None:
        plan.description = update.description.strip()
    if update.category is not None:
        plan.category = update.category
    db.commit()
    db.refresh(plan)
    return _installment_plan_to_out(plan)


@app.delete("/installments/{plan_id}", status_code=204)
def delete_installment_plan(
    plan_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    plan = _get_owned_installment_plan(plan_id, current_user.id, db)
    db.query(models.Transaction).filter(models.Transaction.installment_plan_id == plan.id).update(
        {"installment_plan_id": None}
    )
    db.delete(plan)
    db.commit()


@app.post("/installments/{plan_id}/payments/{payment_id}/pay", response_model=schemas.InstallmentPaymentPayOut)
def pay_installment_payment(
    plan_id: int,
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    plan = _get_owned_installment_plan(plan_id, current_user.id, db)
    payment = (
        db.query(models.InstallmentPayment)
        .filter(models.InstallmentPayment.id == payment_id, models.InstallmentPayment.installment_plan_id == plan.id)
        .first()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Installment payment not found")

    # Idempotency: If already paid, return existing state
    if payment.status == "paid" and payment.transaction_id is not None:
        tx = db.query(models.Transaction).filter(models.Transaction.id == payment.transaction_id).first()
        if tx:
            return schemas.InstallmentPaymentPayOut(
                payment=schemas.InstallmentPaymentOut.model_validate(payment),
                plan=_installment_plan_to_out(plan),
                transaction=tx,
            )

    payment.status = "paid"
    payment.paid_at = datetime.utcnow()

    # Create transaction in Activity
    note_text = f"{plan.description} ({payment.installment_number}/{plan.installment_count} Taksit)"
    tx = models.Transaction(
        owner_id=current_user.id,
        amount=payment.amount,
        type="expense",
        category=plan.category,
        note=note_text,
        occurred_on=date.today(),
        credit_card_id=plan.credit_card_id,
        installment_plan_id=plan.id,
    )
    db.add(tx)
    db.flush()

    payment.transaction_id = tx.id
    _adjust_card_debt(db, plan.credit_card_id, payment.amount)

    pending_count = (
        db.query(models.InstallmentPayment)
        .filter(models.InstallmentPayment.installment_plan_id == plan.id, models.InstallmentPayment.status == "pending")
        .count()
    )
    if pending_count == 0:
        plan.status = "completed"

    db.commit()
    db.refresh(plan)
    db.refresh(payment)
    db.refresh(tx)

    return schemas.InstallmentPaymentPayOut(
        payment=schemas.InstallmentPaymentOut.model_validate(payment),
        plan=_installment_plan_to_out(plan),
        transaction=tx,
    )


@app.post("/account/reset", response_model=schemas.AccountResetResponse)
def reset_account(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    owner_id = current_user.id
    try:
        # 1. Installment payments
        db.query(models.InstallmentPayment).filter(
            models.InstallmentPayment.installment_plan_id.in_(
                db.query(models.InstallmentPlan.id).filter(models.InstallmentPlan.owner_id == owner_id)
            )
        ).delete(synchronize_session=False)

        # 2. Transactions
        db.query(models.Transaction).filter(models.Transaction.owner_id == owner_id).delete(synchronize_session=False)

        # 3. Installment plans
        db.query(models.InstallmentPlan).filter(models.InstallmentPlan.owner_id == owner_id).delete(synchronize_session=False)

        # 4. Recurring transactions
        db.query(models.RecurringTransaction).filter(models.RecurringTransaction.owner_id == owner_id).delete(synchronize_session=False)

        # 5. Subscriptions
        db.query(models.Subscription).filter(models.Subscription.owner_id == owner_id).delete(synchronize_session=False)

        # 6. Budget limits
        db.query(models.BudgetLimit).filter(models.BudgetLimit.owner_id == owner_id).delete(synchronize_session=False)

        # 7. Credit cards
        db.query(models.CreditCard).filter(models.CreditCard.owner_id == owner_id).delete(synchronize_session=False)

        # 8. Categories
        db.query(models.Category).filter(models.Category.owner_id == owner_id).delete(synchronize_session=False)

        # 9. Backup imports
        db.query(models.BackupImport).filter(models.BackupImport.owner_id == owner_id).delete(synchronize_session=False)

        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Hesap sıfırlanamadı") from exc

    return schemas.AccountResetResponse(
        message="Hesabınız başarıyla sıfırlandı.",
        detail="Tüm finansal verileriniz temizlendi.",
    )


@app.get("/account/export", response_model=schemas.AccountBackup)
def export_account(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    owner_id = current_user.id
    transactions = db.query(models.Transaction).filter(models.Transaction.owner_id == owner_id).all()
    subscriptions = db.query(models.Subscription).filter(models.Subscription.owner_id == owner_id).all()
    recurring = db.query(models.RecurringTransaction).filter(models.RecurringTransaction.owner_id == owner_id).all()
    cards = db.query(models.CreditCard).filter(models.CreditCard.owner_id == owner_id).all()
    categories = db.query(models.Category).filter(models.Category.owner_id == owner_id).all()
    budgets = db.query(models.BudgetLimit).filter(models.BudgetLimit.owner_id == owner_id).all()
    plans = db.query(models.InstallmentPlan).filter(models.InstallmentPlan.owner_id == owner_id).all()
    payments = (
        db.query(models.InstallmentPayment)
        .join(models.InstallmentPlan, models.InstallmentPayment.installment_plan_id == models.InstallmentPlan.id)
        .filter(models.InstallmentPlan.owner_id == owner_id)
        .all()
    )

    return schemas.AccountBackup(
        exported_at=datetime.utcnow(),
        transactions=[
            schemas.AccountBackupTransaction(
                source_id=t.id, amount=t.amount, type=t.type, category=t.category, note=t.note,
                occurred_on=t.occurred_on, credit_card_source_id=t.credit_card_id,
                recurring_transaction_source_id=t.recurring_transaction_id,
                installment_plan_source_id=t.installment_plan_id,
            )
            for t in transactions
        ],
        subscriptions=[
            schemas.AccountBackupSubscription(
                name=s.name,
                amount=s.amount,
                billing_cycle=s.billing_cycle,
                next_due_date=s.next_due_date,
                category=s.category,
                note=s.note,
                is_active=s.is_active,
                last_paid_date=s.last_paid_date,
            )
            for s in subscriptions
        ],
        recurring_transactions=[
            schemas.AccountBackupRecurringTransaction(
                source_id=r.id, name=r.name,
                amount=r.amount,
                type=r.type,
                frequency=r.frequency,
                next_due_date=r.next_due_date,
                category=r.category,
                note=r.note,
                is_active=r.is_active,
            )
            for r in recurring
        ],
        credit_cards=[
            schemas.AccountBackupCreditCard(
                source_id=c.id, bank_name=c.bank_name,
                card_name=c.card_name,
                limit_amount=c.limit_amount,
                current_debt=c.current_debt,
                statement_day=c.statement_day,
                due_day=c.due_day,
                note=c.note,
            )
            for c in cards
        ],
        categories=[schemas.AccountBackupCategory(name=cat.name, type=cat.type) for cat in categories],
        budgets=[schemas.AccountBackupBudget(category=b.category, monthly_limit=b.monthly_limit) for b in budgets],
        installment_plans=[
            schemas.AccountBackupInstallmentPlan(
                source_id=p.id,
                credit_card_source_id=p.credit_card_id,
                description=p.description,
                category=p.category,
                total_amount=p.total_amount,
                installment_count=p.installment_count,
                installment_amount=p.installment_amount,
                first_due_date=p.first_due_date,
                status=p.status,
                created_at=p.created_at,
            )
            for p in plans
        ],
        installment_payments=[
            schemas.AccountBackupInstallmentPayment(
                plan_source_id=pay.installment_plan_id,
                installment_number=pay.installment_number,
                amount=pay.amount,
                due_date=pay.due_date,
                paid_at=pay.paid_at,
                status=pay.status,
                transaction_source_id=pay.transaction_id,
            )
            for pay in payments
        ],
    )


@app.post("/account/import", response_model=schemas.AccountImportResult, response_model_exclude_none=True)
def import_account(
    payload: schemas.AccountBackup,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    owner_id = current_user.id
    canonical = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    already_imported = db.query(models.BackupImport).filter(
        models.BackupImport.owner_id == owner_id, models.BackupImport.fingerprint == fingerprint
    ).first()
    if already_imported:
        return schemas.AccountImportResult(
            transactions=0, subscriptions=0, recurring_transactions=0,
            credit_cards=0, categories=0, budgets=0,
            installment_plans=0 if payload.installment_plans else None,
            installment_payments=0 if payload.installment_payments else None,
        )

    card_map: dict[int, int] = {}
    recurring_map: dict[int, int] = {}
    plan_map: dict[int, int] = {}

    for c in payload.credit_cards:
        card = models.CreditCard(owner_id=owner_id, **c.model_dump(exclude={"source_id"}))
        db.add(card)
        db.flush()
        if c.source_id is not None:
            card_map[c.source_id] = card.id

    for r in payload.recurring_transactions:
        recurring = models.RecurringTransaction(owner_id=owner_id, **r.model_dump(exclude={"source_id"}))
        db.add(recurring)
        db.flush()
        if r.source_id is not None:
            recurring_map[r.source_id] = recurring.id

    for p in payload.installment_plans:
        new_card_id = card_map.get(p.credit_card_source_id)
        if new_card_id is not None:
            plan = models.InstallmentPlan(
                owner_id=owner_id,
                credit_card_id=new_card_id,
                description=p.description,
                category=p.category,
                total_amount=p.total_amount,
                installment_count=p.installment_count,
                installment_amount=p.installment_amount,
                first_due_date=p.first_due_date,
                status=p.status,
            )
            db.add(plan)
            db.flush()
            if p.source_id is not None:
                plan_map[p.source_id] = plan.id

    for pay in payload.installment_payments:
        new_plan_id = plan_map.get(pay.plan_source_id)
        if new_plan_id is not None:
            payment = models.InstallmentPayment(
                installment_plan_id=new_plan_id,
                installment_number=pay.installment_number,
                amount=pay.amount,
                due_date=pay.due_date,
                paid_at=pay.paid_at,
                status=pay.status,
            )
            db.add(payment)

    for t in payload.transactions:
        data = t.model_dump(
            exclude={"source_id", "credit_card_source_id", "recurring_transaction_source_id", "installment_plan_source_id"}
        )
        data["credit_card_id"] = card_map.get(t.credit_card_source_id)
        data["recurring_transaction_id"] = recurring_map.get(t.recurring_transaction_source_id)
        data["installment_plan_id"] = plan_map.get(t.installment_plan_source_id)
        db.add(models.Transaction(owner_id=owner_id, **data))

    for s in payload.subscriptions:
        db.add(models.Subscription(owner_id=owner_id, **s.model_dump()))

    existing_category_names = {
        _normalize_category(c.name)
        for c in db.query(models.Category).filter(models.Category.owner_id == owner_id).all()
    }
    categories_created = 0
    for cat in payload.categories:
        key = _normalize_category(cat.name)
        if key in existing_category_names:
            continue
        existing_category_names.add(key)
        db.add(models.Category(owner_id=owner_id, **cat.model_dump()))
        categories_created += 1

    existing_budget_categories = {
        _normalize_category(b.category)
        for b in db.query(models.BudgetLimit).filter(models.BudgetLimit.owner_id == owner_id).all()
    }
    budgets_created = 0
    for b in payload.budgets:
        key = _normalize_category(b.category)
        if key in existing_budget_categories:
            continue
        existing_budget_categories.add(key)
        db.add(models.BudgetLimit(owner_id=owner_id, **b.model_dump()))
        budgets_created += 1

    db.add(models.BackupImport(owner_id=owner_id, fingerprint=fingerprint))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Yedek geri yüklenemedi; hiçbir veri değiştirilmedi") from exc

    return schemas.AccountImportResult(
        transactions=len(payload.transactions),
        subscriptions=len(payload.subscriptions),
        recurring_transactions=len(payload.recurring_transactions),
        credit_cards=len(payload.credit_cards),
        categories=categories_created,
        budgets=budgets_created,
        installment_plans=len(payload.installment_plans) if payload.installment_plans else None,
        installment_payments=len(payload.installment_payments) if payload.installment_payments else None,
    )
