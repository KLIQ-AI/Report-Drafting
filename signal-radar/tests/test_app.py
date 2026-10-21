import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.db import Database
from app.enrichment import MockEnricher
from app.icp import icp_fit, infer_seniority
from app.main import create_app
from app.pipeline import Pipeline
from app.providers import Engagement, Person, Post
from app.providers.mock import MockProvider
from app.scoring import Scorer, heuristic_score


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.vp = Person("https://linkedin.com/in/vp", "Ana Ruiz", "VP of Sales at Acme", "VP of Sales",
                         "Acme", "acme.com", 200, "Software", "Madrid, Spain")
        self.intern = Person("https://linkedin.com/in/intern", "Bo Li", "Sales Intern at Acme",
                             "Sales Intern", "Acme", "acme.com", 200, "Software", "Madrid, Spain")

    def search_posts(self, keywords, limit=20):
        return [Post("p1", "https://linkedin.com/feed/update/1", f"Thoughts on {keywords[0]}",
                     author_url="https://linkedin.com/in/author", posted_at=None),
                Post("p2", "https://linkedin.com/feed/update/2", "We're hiring SDRs!")]

    def profile_posts(self, url, limit=10):
        return self.search_posts(["competitor"])

    def engagements(self, post, limit=100):
        return [
            Engagement(self.vp, "comment", comment_text="Looking for an alternative, what's the pricing?"),
            Engagement(self.intern, "reaction", reaction_type="like"),
            Engagement(Person("https://linkedin.com/in/author", "Author"), "reaction"),
        ]


@pytest.fixture
def hooks():
    return []


@pytest.fixture
def client(tmp_path, hooks):
    def handler(request: httpx.Request):
        hooks.append(request)
        return httpx.Response(200)

    db = Database(str(tmp_path / "t.db"))
    pipeline = Pipeline(db, FakeProvider(), MockEnricher(), Scorer("", "unused"),
                        http=httpx.Client(transport=httpx.MockTransport(handler)))
    settings = load_settings().__class__(**{**load_settings().__dict__, "run_interval_minutes": 0})
    with TestClient(create_app(settings, pipeline)) as c:
        yield c


def test_seniority_inference():
    assert infer_seniority("Co-founder & CEO") == "c_level"
    assert infer_seniority("VP of Sales") == "vp"
    assert infer_seniority("Head of Growth") == "director"
    assert infer_seniority("Software Engineer") == "ic"


def test_icp_fit_excludes_and_matches():
    icp = {"titles_include": ["sales"], "titles_exclude": ["intern"], "seniorities": ["vp"],
           "company_size_min": 50, "company_size_max": 500, "industries": ["software"], "locations": ["spain"]}
    vp = {"title": "VP of Sales", "seniority": "vp", "company_size": 200, "industry": "Software",
          "location": "Madrid, Spain"}
    assert icp_fit(vp, icp)[0] == 100
    assert icp_fit({**vp, "title": "Sales Intern"}, icp)[0] == 0
    assert icp_fit({**vp, "company_size": 5000}, icp)[0] == 80


def test_heuristic_ranks_questions_above_likes():
    lead = {"name": "Ana Ruiz"}
    comment = heuristic_score(lead, [{"kind": "comment", "comment_text": "Any recommendations? What's the pricing?"}])
    like = heuristic_score(lead, [{"kind": "reaction", "comment_text": "", "reaction_type": "like"}])
    assert comment.intent_score > like.intent_score
    assert comment.buying_stage == "evaluating"
    assert "Ana" in comment.suggested_opener


def test_full_flow(client, hooks):
    client.put("/api/settings/icp", json={"titles_exclude": ["intern"]})
    client.put("/api/settings/routing", json={"min_icp_fit": 60, "min_intent": 50,
                                              "webhook_url": "https://hook.test/x",
                                              "slack_webhook_url": "https://hooks.slack.test/y"})
    m = client.post("/api/monitors", json={"name": "Outbound", "kind": "keyword",
                                           "query": "outbound tools", "exclude_keywords": "hiring"}).json()
    run = client.post(f"/api/monitors/{m['id']}/run").json()
    assert run["error"] == ""
    assert run["posts_found"] == 1          # the "hiring" post was excluded
    assert run["new_leads"] == 2            # post author is skipped

    leads = {l["name"]: l for l in client.get("/api/leads").json()}
    assert leads["Ana Ruiz"]["status"] == "qualified"
    assert leads["Ana Ruiz"]["email"] == "ana.ruiz@acme.com"
    assert leads["Bo Li"]["status"] == "disqualified"
    assert {r.url.host for r in hooks} == {"hook.test", "hooks.slack.test"}

    # re-running is idempotent: no duplicate signals, no duplicate deliveries
    again = client.post(f"/api/monitors/{m['id']}/run").json()
    assert again["signals_found"] == 0 and again["new_leads"] == 0
    assert len(hooks) == 2

    detail = client.get(f"/api/leads/{leads['Ana Ruiz']['id']}").json()
    assert detail["signals"][0]["kind"] == "comment"
    assert all(d["ok"] for d in detail["deliveries"])

    csv = client.get("/api/leads.csv?status=qualified").text
    assert "Ana Ruiz" in csv and "Bo Li" not in csv

    assert client.patch(f"/api/leads/{leads['Ana Ruiz']['id']}", json={"status": "contacted"}).json()["status"] == "contacted"
    client.delete(f"/api/monitors/{m['id']}")
    assert client.get("/api/leads").json() == []


def test_mock_provider_is_deterministic():
    p = MockProvider()
    a, b = p.search_posts(["revops"]), p.search_posts(["revops"])
    assert [x.external_id for x in a] == [x.external_id for x in b]
    assert p.engagements(a[0])


def test_dashboard_served(client):
    assert "Signal Radar" in client.get("/").text
    assert client.get("/api/status").json()["scoring"] == "heuristic"
