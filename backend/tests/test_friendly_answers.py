"""
Answers an office user can use: analysis kept, only unsupported claims left out, estimates marked, data readable.

Reported: "Identify opportunities to improve the website's SEO." came back as "I couldn't verify my own summary…"
plus a raw dump (ctr: 0.0017301038062283738 …): one figure the checker could not trace (a target, or a fact from the
company's own documents) threw away the whole analysis.

Through the real API, planner, Search Console provider and answer checks (FAKED: the language model and Google's
API, as in test_search_console_seo_e2e).
"""
from __future__ import annotations

from app.services.grounding import verify_answer
from app.services.readable import tables_from_evidence, value
from tests.test_search_console_seo_e2e import ask, connect_gsc, gsc_api, llm, plan_row  # noqa: F401 (fixtures)

EV = """[integration_8c87983f_get_search_analytics] Integration: Google Search Console
Source: Google Search Console (property https://gecservices.in/, 2026-10-07 to 2026-11-01)
Capability: get_search_analytics
Rows: 3

  1. query: community certificate | clicks: 2 | impressions: 1156 | ctr: 0.0017301038062283738 | position: 9.666089965397925
  2. query: income certificate application | clicks: 1 | impressions: 597 | ctr: 0.0016750418760469012 | position: 8.159128978224455
  3. query: professional tax online payment | clicks: 5 | impressions: 170 | ctr: 0.029411764705882353 | position: 6.188235294117647

Total clicks across the 3 rows above: 8
Overall CTR across these rows (total clicks / total impressions): 0.42%"""


# ── sentence-level checking ──────────────────────────────────────────────────

def test_supported_analysis_is_kept_and_only_the_invented_sentence_is_left_out():
    ans = ("**Community certificate** has 1,156 impressions but only 2 clicks (0.17% CTR) at position 9.7. "
           "It also gets 4,200 visits from Facebook every month.\n"
           "- Income certificate application: 597 impressions, 1 click.")
    v = verify_answer(ans, EV)
    assert "1,156 impressions" in v.text and "597 impressions" in v.text
    assert "4,200" not in v.text and v.removed == ["It also gets 4,200 visits from Facebook every month."]
    assert not v.replaced


def test_targets_and_estimates_are_kept_and_marked():
    v = verify_answer("Rewrite the title; aim for a 3.5% CTR, which could bring about 40 clicks a month.", EV)
    assert "aim for a 3.5% CTR" in v.text and "*(estimate)*" in v.text and v.estimates == 1 and not v.removed


def test_general_guidance_years_and_small_counts_are_not_data_claims():
    v = verify_answer("Keep titles under 60 characters, add 3 FAQs and review again in 2 weeks (2026 plan).", EV)
    assert not v.removed and v.text.startswith("Keep titles under 60 characters")


def test_a_wrong_date_range_is_caught_even_when_the_total_is_right():
    v = verify_answer("Between 2020-01-01 and 2020-01-28 we got 8 clicks.", EV)
    assert v.removed and v.replaced


def test_facts_from_the_companys_own_documents_count_as_supported():
    v = verify_answer("We offer over 200 government services.", EV + "\nGEC offers 200+ online services in Kerala.")
    assert not v.removed


def test_mostly_invented_answers_are_replaced_by_the_data():
    v = verify_answer("Clicks grew 38% to 12,345. CTR reached 9.99%. Revenue was 45,000.", EV)
    assert v.replaced and len(v.removed) == 3


def test_a_table_row_with_invented_numbers_is_dropped_but_the_table_kept():
    ans = "| Query | Impressions |\n|---|---|\n| community certificate | 1,156 |\n| made up | 9,999 |"
    v = verify_answer(ans, EV)
    assert "community certificate | 1,156" in v.text and "9,999" not in v.text and "|---|" in v.text


# ── readable data ────────────────────────────────────────────────────────────

def test_integration_rows_become_a_readable_table():
    t = tables_from_evidence(EV)
    assert "| Search query | Clicks | Impressions | Click-through rate | Avg. position |" in t
    assert "| community certificate | 2 | 1,156 | 0.17% | 9.7 |" in t
    assert "| professional tax online payment | 5 | 170 | 2.9% | 6.2 |" in t
    assert "0.0017301" not in t and "Overall click-through rate: 0.42%" in t
    assert value("permission", "siteOwner") == "Owner"


# ── end to end: the reported question ────────────────────────────────────────

def test_the_seo_opportunities_question_gets_the_analysis_not_a_data_dump(world, llm, gsc_api):
    connect_gsc(world)
    llm.synth = lambda g: (
        "**Biggest opportunity: ‘trail shoes’.** It is shown 5,000 times but gets only 150 clicks (3% CTR) at "
        "position 6.8.\n\n"
        "1. Rewrite the page title and description for ‘trail shoes’ — aim for a 5% CTR, which could mean about "
        "250 clicks.\n"
        "2. ‘running shoes’ already brings 320 clicks at position 4.2: add an FAQ section to keep it.\n"
        "3. Our competitor gets 9,876 clicks for the same query.\n\n"
        "**Next steps:** update the two titles this week.")
    body = ask(world, prompt="Identify opportunities to improve the website's SEO.").json()
    msg = body["message"]
    assert "Biggest opportunity" in msg and "5,000 times" in msg and "Next steps" in msg   # analysis kept
    assert "aim for a 5% CTR" in msg and "*(estimate)*" in msg                          # target kept, marked
    assert "9,876" not in msg and "I left out 1 statement" in msg                        # only that one dropped
    assert "couldn’t verify" not in msg and "ctr: 0.0" not in msg
    assert "Data source:" in msg
    grounding = plan_row(world, body["plan_id"])[-1][1]
    assert "1 unsupported statement(s) left out" in grounding and "1 estimate(s) marked" in grounding


def test_every_answer_is_written_with_the_plain_language_rules(monkeypatch):
    """Both answer paths send the writing rules to the model: the planner (workflows, meetings) and the chat agent."""
    import asyncio
    from types import SimpleNamespace
    from langchain_core.messages import AIMessage
    from app.llm.gateway import LLMGateway
    from app.schemas.blueprint import AgentBlueprint
    from app.services import chat_agent, planner
    seen = []

    class Capture:
        async def ainvoke(self, messages, *a, **k):
            seen.append(str(messages[0].content))
            return AIMessage(content="ok")
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: Capture())
    bp = AgentBlueprint(agent_id="a", role_name="Digital Marketing Manager", role_key="DIGITAL_MARKETING_MANAGER",
                        system_persona="x", allowed_tools=[], guarded_tools=[], tenant_id="t")
    asyncio.run(planner._synthesise_response(objective="Improve SEO", step_results={0: "clicks: 5"}, blueprint=bp,
                                             system_persona="You are the marketing manager."))
    assert "office user" in seen[-1] and "Next steps" in seen[-1] and "prioritised list" in seen[-1]
    assert "office user" in chat_agent.WRITING_RULES and "more than one angle" in chat_agent.ADVICE_RULES


def test_step_labels_are_plain_words():
    from app.services.chat_agent import _label
    assert _label("web_search", {}) == "Searched the web"
    assert _label("make_chart", {}) == "Made a chart"
    assert _label("mcp_1a2b3c4d_firecrawl_scrape", {}) == "Connected tool: firecrawl scrape"


def test_the_chat_agent_system_prompt_carries_the_writing_and_advice_rules(world, chat_agent_model):
    from tests.test_chat_agent import pick, send
    pick(world, "a_admin", "DIGITAL_MARKETING_MANAGER")
    send(world, "a_admin", "Identify opportunities to improve the website's SEO.")
    system = chat_agent_model["m"].calls[0][0].content
    assert "the reader is an office user" in system and "Advice needs evidence from more than one angle" in system
    assert "search queries AND pages" in system


import pytest  # noqa: E402


@pytest.fixture()
def chat_agent_model(monkeypatch):
    from types import SimpleNamespace
    import app.config as cfg
    from app.llm.gateway import LLMGateway
    from tests.test_chat_agent import Script
    cfg.settings.__dict__["chat_engine"] = "agent"
    holder = {"m": Script("Here are the opportunities.")}
    monkeypatch.setattr(LLMGateway, "get_chat_model", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "get_chat_model_for_role", lambda self, *a, **k: holder["m"])
    monkeypatch.setattr(LLMGateway, "health", lambda self: SimpleNamespace(is_ready=True))
    return holder
