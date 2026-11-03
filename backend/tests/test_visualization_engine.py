"""
Universal visualization engine (backend half): every AI employee, one ChartSpec, verified data, never raw JSON.

Through the real API, agent loop, make_chart, chart verification, text extraction and conversation history.
FAKED: the language model (scripted) and the internet behind read_web_page (the `web` fixture).
The frontend half (rendering, themes, responsive layout, render failure fallback) is verified with Playwright
screenshots — see the final report.
"""
from __future__ import annotations

import json

import pytest

from app.toolhub import charts
from tests.test_chat_agent import pick
from tests.test_toolhub_orchestration import NAMES, Agent, agent, calls, send_as, web  # noqa: F401 (fixtures)

DMM, ANALYST, CLERK, MED = ("DIGITAL_MARKETING_MANAGER", "DATA_INTELLIGENCE_ANALYST", "INSTITUTIONAL_CLERK",
                            "MEDICAL_ASSISTANT")
ROWS = [{"query": "passport renewal", "clicks": 320, "impressions": 8000},
        {"query": "visa help kochi", "clicks": 150, "impressions": 3800},
        {"query": "pan card", "clicks": 90, "impressions": 2100}]
DAILY = [{"date": f"2026-10-{d:02d}", "sessions": 40 + d * 3} for d in range(1, 11)]


def turn(world, agent, web, chart_args, data=ROWS, role=DMM, reply="Here it is.", prompt="chart it"):
    web["pages"]["https://data.example/d"] = "Data\n" + json.dumps(data) + "\nSource: data.example"
    agent["m"] = Agent(calls(("read_web_page", {"url": "https://data.example/d"})),
                       calls(("make_chart", chart_args)) if chart_args is not None else reply, reply)
    pick(world, "a_admin", role)
    return send_as(world, role, prompt), agent["m"].calls[-1][-1].content


QUERIES = [r["query"] for r in ROWS]
NAMES.setdefault("INSTITUTIONAL_CLERK", "Institutional Clerk")


# 1 ─ bar chart from structured fields (not a JSON string)
def test_1_a_bar_chart_from_structured_fields(world, agent, web):
    body, _ = turn(world, agent, web, {"title": "Clicks by query", "type": "bar", "labels": QUERIES,
                                       "series": [{"name": "Clicks", "values": [320, 150, 90]}],
                                       "description": "Top queries, last 28 days", "y_label": "clicks"})
    c = body["charts"][0]
    assert (c["type"], c["title"], c["labels"], c["series"][0]["values"]) == ("bar", "Clicks by query", QUERIES,
                                                                             [320, 150, 90])
    assert c["description"] == "Top queries, last 28 days" and "{" not in body["message"]


# 2 ─ line chart (dates → line when no type is given)
def test_2_dates_become_a_line_chart(world, agent, web):
    body, _ = turn(world, agent, web, {"title": "Daily sessions", "labels": [r["date"] for r in DAILY],
                                       "series": [{"name": "Sessions", "values": [r["sessions"] for r in DAILY]}]},
                   data=DAILY)
    assert body["charts"][0]["type"] == "line" and len(body["charts"][0]["labels"]) == 10


# 3 ─ pie and donut
@pytest.mark.parametrize("ctype", ["pie", "donut", "doughnut"])
def test_3_pie_and_donut(world, agent, web, ctype):
    body, _ = turn(world, agent, web, {"title": "Click share", "type": ctype, "labels": QUERIES,
                                       "series": [{"name": "Clicks", "values": [320, 150, 90]}]})
    assert body["charts"][0]["type"] == ("donut" if ctype == "doughnut" else ctype)


# 4 ─ multiple series: grouped, stacked, horizontal comparison
def test_4_multiple_series_grouped_stacked_and_horizontal(world, agent, web):
    two = [{"name": "Clicks", "values": [320, 150, 90]}, {"name": "Impressions", "values": [8000, 3800, 2100]}]
    body, _ = turn(world, agent, web, {"title": "Clicks vs impressions", "labels": QUERIES, "series": two})
    assert body["charts"][0]["type"] == "bar" and len(body["charts"][0]["series"]) == 2
    assert body["charts"][0]["stacked"] is False
    body, _ = turn(world, agent, web, {"title": "Stacked", "type": "stacked_bar", "labels": QUERIES, "series": two})
    assert body["charts"][0]["stacked"] is True
    body, _ = turn(world, agent, web, {"title": "Ranking", "type": "hbar", "labels": QUERIES, "series": two[:1]})
    assert body["charts"][0]["type"] == "hbar"


def test_histogram_bins_are_counted_from_the_returned_values(world, agent, web):
    body, _ = turn(world, agent, web, {"title": "Sessions per day", "type": "histogram",
                                       "values": [r["sessions"] for r in DAILY], "bins": 3}, data=DAILY)
    c = body["charts"][0]
    assert c["type"] == "histogram" and len(c["labels"]) == 3 and sum(c["series"][0]["values"]) == 10


def test_kpi_cards(world, agent, web):
    body, _ = turn(world, agent, web, {"title": "Headline", "type": "kpi",
                                       "kpis": [{"label": "Clicks", "value": 320}, {"label": "Total clicks",
                                                                                     "value": 560}]})
    assert [k["value"] for k in body["charts"][0]["kpis"]] == [320, 560]          # 560 = a derived total


# 5 ─ empty data
def test_5_empty_data_is_refused_with_a_reason_and_the_answer_still_arrives(world, agent, web):
    body, work = turn(world, agent, web, {"title": "Nothing", "labels": QUERIES, "series": []})
    assert body["charts"] == [] and body["message"] == "Here it is." and "needs at least one series" in work


# 6 ─ malformed chart JSON
def test_6_malformed_legacy_chart_json_is_reported_not_rendered(world, agent, web):
    body, work = turn(world, agent, web, {"chart_json": '{"title": "Broken", "labels": ["a"'})
    assert body["charts"] == [] and "must be valid JSON" in work


def test_6_a_chart_the_model_wrote_into_its_answer_becomes_a_real_chart(world, agent, web):
    written = ("Top queries:\n\n```json\n" + json.dumps({"type": "bar", "title": "Clicks by query", "labels": QUERIES,
               "series": [{"name": "Clicks", "values": [320, 150, 90]}]}) + "\n```\n\nPassport leads.")
    body, _ = turn(world, agent, web, None, reply=written)
    assert body["charts"] and body["charts"][0]["series"][0]["values"] == [320, 150, 90]
    assert "```" not in body["message"] and '"series"' not in body["message"]
    assert "Passport leads." in body["message"] and "Chart: Clicks by query" in body["message"]


def test_6_chart_json_in_common_other_shapes_is_understood(world, agent, web):
    written = json.dumps({"chart_type": "column", "title": "Clicks", "data": [
        {"label": q, "value": v} for q, v in zip(QUERIES, [320, 150, 90])]})
    body, _ = turn(world, agent, web, None, reply="Here:\n" + written)
    assert body["charts"][0]["type"] == "bar" and body["charts"][0]["labels"] == QUERIES


def test_6_invented_values_in_written_chart_json_are_hidden_not_shown(world, agent, web):
    written = "```json\n" + json.dumps({"type": "pie", "title": "Made up", "labels": ["a", "b"],
                                        "series": [{"name": "x", "values": [55, 45]}]}) + "\n```"
    body, _ = turn(world, agent, web, None, reply=written)
    assert body["charts"] == [] and "55" not in body["message"] and "could not be drawn" in body["message"]


def test_6_cut_off_chart_json_never_reaches_the_person(world, agent, web):
    body, _ = turn(world, agent, web, None, reply='Here:\n```json\n{"type": "bar", "labels": ["a", "b"], "series": [')
    assert '"series"' not in body["message"] and "data was incomplete" in body["message"]


# 7 ─ normal conversation: no chart, text untouched
def test_7_a_normal_answer_has_no_chart_and_is_unchanged(world, agent, web):
    text = "Passport renewal takes about 30 days. Use `{name}` placeholders in templates:\n```python\nx = {'a': 1}\n```"
    body, _ = turn(world, agent, web, None, reply=text)
    assert body["charts"] == [] and body["message"] == text


# 8 ─ structured output is kept separate in the response and in saved history
def test_8_charts_are_separate_structured_data_in_the_response_and_history(world, agent, web):
    body, _ = turn(world, agent, web, {"title": "Clicks by query", "labels": QUERIES,
                                       "series": [{"name": "Clicks", "values": [320, 150, 90]}]})
    assert isinstance(body["charts"], list) and isinstance(body["charts"][0], dict)
    saved = world.client.get(f"/api/v1/conversations/{body['conversation_id']}", headers=world.auth("a_admin")).json()
    assert saved["messages"][-1]["charts"][0]["title"] == "Clicks by query"


# 9 ─ every AI employee uses the same engine
@pytest.mark.parametrize("role", [DMM, ANALYST, CLERK, MED])
def test_9_every_ai_employee_gets_the_same_chart_engine(world, agent, web, role):
    body, _ = turn(world, agent, web, {"title": "Clicks by query", "labels": QUERIES,
                                       "series": [{"name": "Clicks", "values": [320, 150, 90]}]}, role=role)
    assert "make_chart" in agent["m"].tools
    if role == MED:      # the medical role has no internet tools, so nothing verifies the numbers → refused
        assert body["charts"] == []
    else:
        assert body["charts"][0]["type"] == "bar"


# unit level
def test_extraction_leaves_non_chart_json_and_code_alone():
    text = 'Config:\n```json\n{"timeout": 30, "retries": 2}\n```\nand {"a": 1} inline.'
    assert charts.extract_from_text(text, "30 2") == (text, [], [])


def test_normalize_reads_chartjs_datasets_and_kpi_maps():
    n = charts.normalize({"type": "line", "title": "T", "labels": ["a", "b"],
                          "datasets": [{"label": "S", "data": [1, 2]}]})
    assert n["series"] == [{"name": "S", "values": [1, 2]}]
    k = charts.normalize({"title": "K", "kpis": {"Clicks": 5}})
    assert k["kpis"] == [{"label": "Clicks", "value": 5}]
    assert charts.normalize({"timeout": 30}) is None
