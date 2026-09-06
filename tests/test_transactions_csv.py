import io

from datetime import date

TODAY = date.today().isoformat()


def test_export_requires_auth(anon_client):
    assert anon_client.get("/transactions/export").status_code == 401


def test_export_returns_csv_with_header_and_rows(client):
    client.post("/transactions", json={"amount": 100, "type": "expense", "category": "Market", "occurred_on": TODAY})
    client.post("/transactions", json={"amount": 5000, "type": "income", "occurred_on": TODAY})

    response = client.get("/transactions/export")
    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    lines = response.text.strip().splitlines()
    assert lines[0] == "occurred_on,type,category,note,amount"
    assert len(lines) == 3


def test_export_honors_filters(client):
    client.post("/transactions", json={"amount": 100, "type": "expense", "category": "Market", "occurred_on": TODAY})
    client.post("/transactions", json={"amount": 5000, "type": "income", "occurred_on": TODAY})

    response = client.get("/transactions/export", params={"type": "income"})
    lines = response.text.strip().splitlines()
    assert len(lines) == 2
    assert "income" in lines[1]


def test_import_requires_auth(anon_client):
    csv_content = "occurred_on,type,category,note,amount\n" + f"{TODAY},expense,Market,,100\n"
    response = anon_client.post(
        "/transactions/import", files={"file": ("tx.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    )
    assert response.status_code == 401


def test_import_creates_transactions(client):
    csv_content = (
        "occurred_on,type,category,note,amount\n"
        f"{TODAY},expense,Market,Haftalık alışveriş,250.5\n"
        f"{TODAY},income,,,5000\n"
    )
    response = client.post(
        "/transactions/import", files={"file": ("tx.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 2
    assert body["skipped"] == 0
    assert body["errors"] == []

    transactions = client.get("/transactions").json()
    assert len(transactions) == 2


def test_import_reports_errors_for_invalid_rows(client):
    csv_content = (
        "occurred_on,type,category,note,amount\n"
        f"{TODAY},expense,Market,,100\n"
        "not-a-date,expense,Market,,50\n"
        f"{TODAY},not-a-type,Market,,50\n"
        f"{TODAY},expense,Market,,-5\n"
    )
    response = client.post(
        "/transactions/import", files={"file": ("tx.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] == 1
    assert body["skipped"] == 3
    assert len(body["errors"]) == 3


def test_import_rejects_missing_columns(client):
    csv_content = "date,kind,amount\n2024-01-01,expense,100\n"
    response = client.post(
        "/transactions/import", files={"file": ("tx.csv", io.BytesIO(csv_content.encode()), "text/csv")}
    )
    assert response.status_code == 400


def test_import_does_not_leak_across_owners(make_authed_client):
    alice = make_authed_client(email="alice_csv@example.com")
    bob = make_authed_client(email="bob_csv@example.com")
    csv_content = f"occurred_on,type,category,note,amount\n{TODAY},expense,Market,,100\n"
    alice.post("/transactions/import", files={"file": ("tx.csv", io.BytesIO(csv_content.encode()), "text/csv")})

    assert len(bob.get("/transactions").json()) == 0
    assert len(alice.get("/transactions").json()) == 1
