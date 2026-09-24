import csv
import io

from conftest import signup


def make_brand(client, h, industry="real_estate"):
    r = client.post("/api/brands", headers=h, json={"name": "Harbor Realty", "industry": industry})
    assert r.status_code == 200, r.text
    return r.json()["brand"]["id"]


def ready_kit(client, h, bid):
    client.post(f"/api/brands/{bid}/sources", headers=h,
                json={"platform": "facebook", "kind": "post", "text": "Just listed in North Tacoma!"})
    job = client.post(f"/api/brands/{bid}/kit/build", headers=h).json()
    job = client.get(f"/api/jobs/{job['id']}", headers=h).json()
    assert job["status"] == "done", job
    kit = client.get(f"/api/brands/{bid}/kit", headers=h).json()["kit"]
    kit["guessed"] = {}
    kit["locations"] = [{"name": "North Tacoma", "references": ["Point Defiance"]}]
    kit["offers"] = [{"headline": "Free home valuation", "cta": "Book"}]
    r = client.put(f"/api/brands/{bid}/kit", headers=h, json={"kit": kit})
    assert r.status_code == 200, r.text
    return r.json()["kit"]


def generate(client, h, bid, **body):
    body.setdefault("formats", ["facebook_feed"])
    body.setdefault("count", 2)
    r = client.post(f"/api/brands/{bid}/requests", headers=h, json=body)
    assert r.status_code == 200, r.text
    job = client.get(f"/api/jobs/{r.json()['id']}", headers=h).json()
    assert job["status"] == "done", job
    return job["result"]


def test_auth_required_and_login(client):
    assert client.get("/api/brands").status_code == 401
    signup(client)
    r = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "wrong-pass"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "OWNER@example.com", "password": "password123"})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/api/me", headers=h).json()["role"] == "Owner"
    client.post("/api/auth/logout", headers=h)
    assert client.get("/api/me", headers=h).status_code == 401


def test_full_flow(client, fake_llm):
    h = signup(client)
    bid = make_brand(client, h)

    # Kit build marks guesses; generation is blocked until they are reviewed.
    client.post(f"/api/brands/{bid}/sources", headers=h, json={"platform": "facebook", "text": "Open house Sunday"})
    job = client.post(f"/api/brands/{bid}/kit/build", headers=h).json()
    assert client.get(f"/api/jobs/{job['id']}", headers=h).json()["status"] == "done"
    kit = client.get(f"/api/brands/{bid}/kit", headers=h).json()["kit"]
    assert kit["guessed"]["core_voice"] == "From the About page"
    assert "platform_themes.facebook" in kit["guessed"]
    assert "Equal Housing Opportunity" in kit["compliance"]["required_disclaimers"]
    assert kit["compliance"]["special_ad_category"] is True
    assert "cheap" in kit["never_words"]
    r = client.post(f"/api/brands/{bid}/requests", headers=h, json={"formats": ["facebook_feed"], "count": 1})
    assert r.status_code == 422 and "guessed" in r.json()["detail"]

    kit = ready_kit(client, h, bid)
    assert client.get(f"/api/brands/{bid}", headers=h).json()["kit_ready"] is True

    # Every-platform + location run.
    result = generate(client, h, bid, formats=["facebook_feed", "google_search", "x_promoted"],
                      locations=["North Tacoma"], count=2)
    assert result["ads"] == 6
    ads = client.get(f"/api/brands/{bid}/ads", headers=h).json()
    assert {a["platform"] for a in ads} == {"facebook", "google", "x"}
    assert all(a["location"] == "North Tacoma" for a in ads)
    google = next(a for a in ads if a["platform"] == "google")
    assert google["content"]["hashtags"] == []
    fb = next(a for a in ads if a["platform"] == "facebook")
    assert "North Tacoma" in fb["content"]["fields"]["primary_text"]

    # The kit went into a cached system block; the platform block is cached too.
    write_call = next(c for c in fake_llm.calls if c["schema"] == "Batch_facebook_feed")
    assert write_call["system"][1]["cache_control"] == {"type": "ephemeral"}
    assert write_call["content"][0]["cache_control"] == {"type": "ephemeral"}

    # Edit to add an unsupported number -> blocking flag -> cannot approve.
    fields = dict(fb["content"]["fields"])
    fields["primary_text"] = "500 homes sold in North Tacoma. Equal Housing Opportunity"
    r = client.patch(f"/api/ads/{fb['id']}", headers=h, json={"content": {"fields": fields}})
    ad = r.json()
    assert ad["edited"] is True and ad["blocking"] == 1
    r = client.patch(f"/api/ads/{fb['id']}", headers=h, json={"status": "approved"})
    assert r.status_code == 422

    # Owner overrides with a reason, then approves.
    idx = next(i for i, f in enumerate(ad["flags"]) if f["rule"] == "unsupported_claim")
    r = client.patch(f"/api/ads/{fb['id']}", headers=h, json={"override": {"index": idx, "reason": "Verified MLS data"}})
    assert r.json()["blocking"] == 0
    assert client.patch(f"/api/ads/{fb['id']}", headers=h, json={"status": "approved"}).status_code == 200

    # Export only includes approved ads, and marks them exported.
    r = client.post(f"/api/brands/{bid}/exports", headers=h, json={"platform": "facebook"})
    assert r.status_code == 200, r.text
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["Adpress Ad ID"] for row in rows] == [fb["id"]]
    assert rows[0]["Special Ad Category"] == "HOUSING"
    assert client.get(f"/api/brands/{bid}/ads?status=exported", headers=h).json()[0]["id"] == fb["id"]

    # Refine replaces the ad with a child.
    other = next(a for a in ads if a["platform"] == "x")
    r = client.post(f"/api/ads/{other['id']}/refine", headers=h, json={"instruction": "shorter"})
    assert r.status_code == 200, r.text
    child = r.json()
    assert child["parent_ad_id"] == other["id"]
    ids = [a["id"] for a in client.get(f"/api/brands/{bid}/ads", headers=h).json()]
    assert child["id"] in ids and other["id"] not in ids

    m = client.get(f"/api/brands/{bid}/metrics", headers=h).json()
    assert m["ads_generated"] == 7 and m["ads_kept"] == 1 and m["kept_without_edits_pct"] == 0.0

    # Kit export/import round trip.
    md = client.get(f"/api/brands/{bid}/kit/export.md", headers=h).text
    r = client.post(f"/api/brands/{bid}/kit/import", headers=h, json={"markdown": md})
    assert r.status_code == 200
    assert r.json()["kit"]["locations"][0]["name"] == "North Tacoma"


def test_review_flags_become_blocking(client, fake_llm):
    h = signup(client)
    bid = make_brand(client, h)
    ready_kit(client, h, bid)
    fake_llm.review_issues = [{"ad_index": 0, "rule": "unsupported_claim", "words": "Harbor Realty",
                               "explanation": "Award not in kit", "suggestion": "Harbor"},
                              {"ad_index": 0, "rule": "off_brand", "words": "not in the ad",
                               "explanation": "ignored", "suggestion": ""}]
    generate(client, h, bid, count=1)
    ad = client.get(f"/api/brands/{bid}/ads", headers=h).json()[0]
    review = [f for f in ad["flags"] if f["source"] == "review"]
    assert len(review) == 1 and review[0]["severity"] == "blocking"


def test_limits_and_validation(client):
    h = signup(client)
    bid = make_brand(client, h)
    ready_kit(client, h, bid)
    r = client.post(f"/api/brands/{bid}/requests", headers=h, json={"formats": ["nope"], "count": 1})
    assert r.status_code == 422
    r = client.post(f"/api/brands/{bid}/requests", headers=h, json={"formats": ["facebook_feed"], "count": 21})
    assert r.status_code == 422
    r = client.post(f"/api/brands/{bid}/requests", headers=h,
                    json={"formats": ["facebook_feed"], "locations": ["Mars"], "count": 1})
    assert r.status_code == 422
    for _ in range(10):
        client.post(f"/api/brands/{bid}/sources", headers=h, json={"platform": "x", "text": "post"})
    assert client.post(f"/api/brands/{bid}/sources", headers=h, json={"platform": "x", "text": "post"}).status_code == 422
    kit = client.get(f"/api/brands/{bid}/kit", headers=h).json()
    bad = dict(kit["kit"], voice_dials={"formal": 9})
    assert client.put(f"/api/brands/{bid}/kit", headers=h, json={"kit": bad}).status_code == 422
    stale = client.put(f"/api/brands/{bid}/kit", headers=h, json={"kit": kit["kit"], "base_version": 1})
    assert stale.status_code == 409


def test_roles_and_isolation(client):
    h = signup(client)
    bid = make_brand(client, h)
    r = client.post("/api/workspace/users", headers=h,
                    json={"email": "viewer@example.com", "password": "password123", "role": "Viewer"})
    assert r.status_code == 200
    vh = {"Authorization": "Bearer " + client.post("/api/auth/login", json={
        "email": "viewer@example.com", "password": "password123"}).json()["token"]}
    assert client.get(f"/api/brands/{bid}", headers=vh).status_code == 200
    assert client.post("/api/brands", headers=vh, json={"name": "X"}).status_code == 403
    assert client.delete(f"/api/brands/{bid}", headers=vh).status_code == 403

    other = signup(client, "other@example.com", "Other")
    assert client.get(f"/api/brands/{bid}", headers=other).status_code == 404
    assert client.get("/api/brands", headers=other).json() == []

    assert client.delete(f"/api/brands/{bid}", headers=h).status_code == 200
    assert client.get(f"/api/brands/{bid}", headers=h).status_code == 404


def test_import_job_failure_is_reported(client, monkeypatch):
    from adpress import main

    def boom(self, url):
        raise main.FetchError("No readable content was found on that website.")

    monkeypatch.setattr(main.Fetcher, "fetch_site", boom)
    h = signup(client)
    r = client.post("/api/brands", headers=h, json={"name": "B", "website_url": "harbor.example"})
    job = client.get(f"/api/jobs/{r.json()['job']['id']}", headers=h).json()
    assert job["status"] == "failed" and "No readable content" in job["error"]
