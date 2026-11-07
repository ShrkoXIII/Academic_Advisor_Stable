from pathlib import Path
import json

from streamlit.testing.v1 import AppTest
from tests.integration.test_api_stable import api_client
from tools.academic_advisor_streamlit.ui_client import HttpClient


APP = Path(__file__).resolve().parents[2] / "tools/academic_advisor_streamlit/streamlit_app.py"


def test_initial_ui_loads_without_models_or_upstream_connections():
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    assert len(app.exception) == 0
    assert app.title[0].value == "Academic Advisor — Stable"
    assert app.sidebar.radio[0].value == "JSON محلي"


def test_a_new_invalid_request_clears_the_previous_evaluation():
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.session_state["evaluation"] = {"old": "must not remain visible"}
    app.button(key="run_evaluation").click().run()
    assert len(app.exception) == 0
    assert "evaluation" not in app.session_state
    assert len(app.error) == 1


def test_ui_renders_three_plans_returned_by_the_existing_http_contract(api_client, monkeypatch):
    client, _, request = api_client
    def advisor(self, method, path, *, data=None, admin=False):
        response = client.request(method, path, json=data,
                                  headers={"X-API-Key": "synthetic-service"})
        return response.status_code, response.json(), dict(response.headers)
    monkeypatch.setattr(HttpClient, "advisor", advisor)
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    app.text_area[0].set_value(json.dumps(request))
    app.button(key="run_evaluation").click().run()
    assert len(app.exception) == 0
    assert len(app.session_state["evaluation"]["result"]["recommendations"]) == 3
    assert len(app.dataframe) >= 4
