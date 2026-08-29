from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
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

app = FastAPI(title="Budget Tracker API")
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
):
    return (
        db.query(models.Transaction)
        .filter(models.Transaction.owner_id == current_user.id)
        .order_by(models.Transaction.occurred_on.desc(), models.Transaction.id.desc())
        .all()
    )


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
):
    return (
        db.query(models.Subscription)
        .filter(models.Subscription.owner_id == current_user.id)
        .order_by(models.Subscription.next_due_date.asc())
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

    return schemas.OverviewOut(
        month_income=round(month_income, 2),
        month_expense=round(month_expense, 2),
        net_balance=round(month_income - month_expense, 2),
        monthly_subscription_cost=round(monthly_subscription_cost, 2),
        upcoming_subscriptions=upcoming_subscriptions,
    )
