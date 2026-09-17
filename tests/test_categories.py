def test_categories_require_auth(anon_client):
    assert anon_client.get("/categories").status_code == 401


def test_create_category(client):
    response = client.post("/categories", json={"name": "Market", "type": "expense"})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Market"
    assert body["type"] == "expense"


def test_create_category_defaults_type_to_both(client):
    response = client.post("/categories", json={"name": "Maaş"})
    assert response.status_code == 201
    assert response.json()["type"] == "both"


def test_create_duplicate_category_name_rejected(client):
    client.post("/categories", json={"name": "Market"})
    response = client.post("/categories", json={"name": "Market"})
    assert response.status_code == 400


def test_list_categories_sorted_by_name(client):
    client.post("/categories", json={"name": "Ulaşım"})
    client.post("/categories", json={"name": "Eğlence"})

    names = [c["name"] for c in client.get("/categories").json()]
    assert names == sorted(names)


def test_update_category(client):
    created = client.post("/categories", json={"name": "Market", "type": "expense"}).json()
    response = client.put(f"/categories/{created['id']}", json={"name": "Süpermarket"})
    assert response.status_code == 200
    assert response.json()["name"] == "Süpermarket"
    assert response.json()["type"] == "expense"


def test_renaming_category_propagates_to_financial_records(client):
    category = client.post("/categories", json={"name": "Market"}).json()
    client.post("/transactions", json={"amount": 10, "type": "expense", "category": " market "})
    client.post("/subscriptions", json={"name": "S", "amount": 10, "category": "MARKET", "next_due_date": "2030-01-01"})
    client.post("/recurring-transactions", json={"name": "R", "amount": 10, "type": "expense", "category": "Market", "next_due_date": "2030-01-01"})
    client.post("/budgets", json={"category": "Market", "monthly_limit": 100})

    assert client.put(f"/categories/{category['id']}", json={"name": "Gıda"}).status_code == 200
    assert client.get("/transactions").json()[0]["category"] == "Gıda"
    assert client.get("/subscriptions").json()[0]["category"] == "Gıda"
    assert client.get("/recurring-transactions").json()[0]["category"] == "Gıda"
    assert client.get("/budgets").json()[0]["category"] == "Gıda"


def test_category_names_are_case_and_whitespace_insensitive(client):
    client.post("/categories", json={"name": " Market "})
    response = client.post("/categories", json={"name": "market"})
    assert response.status_code == 400


def test_update_category_rejects_rename_to_existing_name(client):
    client.post("/categories", json={"name": "Market"})
    other = client.post("/categories", json={"name": "Eğlence"}).json()
    response = client.put(f"/categories/{other['id']}", json={"name": "Market"})
    assert response.status_code == 400


def test_delete_category(client):
    created = client.post("/categories", json={"name": "Market"}).json()
    response = client.delete(f"/categories/{created['id']}")
    assert response.status_code == 204
    assert client.get("/categories").json() == []


def test_categories_scoped_to_owner(make_authed_client):
    alice = make_authed_client(email="alice_cat@example.com")
    bob = make_authed_client(email="bob_cat@example.com")

    alice.post("/categories", json={"name": "Market"})
    bob.post("/categories", json={"name": "Ulaşım"})

    categories = alice.get("/categories").json()
    assert len(categories) == 1
    assert categories[0]["name"] == "Market"
