"""The health check of a local model server (assay.local_server): against a
real HTTP server on 127.0.0.1, and before each run of a local job of
`assay experiment` (through the CLI's `main` and the fake Harbor)."""

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from assay.local_server import check_server
from tests.test_experiment_failures import events, exception
from tests.test_experiment_run import (  # noqa: F401 (fixtures)
    AGENT, FakeHarbor, experiment, no_env_file, repo, write_experiment, write_job)

LOCAL = {**AGENT, "model_name": "laguna-s-2.1",
         "env": {"ANTHROPIC_BASE_URL": "${ASSAY_LOCAL_BASE_URL}", "ANTHROPIC_API_KEY": "dummy"}}


@pytest.fixture
def server():
    """A server whose /health answers with `server.status` (200 at first)."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(httpd.status if self.path == "/health" else 404)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    httpd.status = 200
    httpd.url = f"http://127.0.0.1:{httpd.server_port}"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def closed_port_url():
    httpd = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = httpd.server_port
    httpd.server_close()
    return f"http://127.0.0.1:{port}"


def test_a_server_whose_health_is_200_answers(server):
    assert check_server(server.url + "/") is None


def test_a_server_without_a_health_route_counts_as_up(server):
    server.status = 404
    assert check_server(server.url) is None


def test_a_server_that_loads_its_model_does_not_answer(server):
    server.status = 503
    assert check_server(server.url) == f"{server.url}/health answered HTTP 503"


def test_a_server_that_is_down_does_not_answer():
    url = closed_port_url()
    assert check_server(url).startswith(f"cannot reach {url}/health: ")


def test_a_local_job_with_its_server_down_stops_before_harbor_starts_a_trial(
        repo, monkeypatch, capsys):
    url = closed_port_url()
    monkeypatch.setenv("ASSAY_LOCAL_BASE_URL", url)
    write_experiment(repo, write_job(repo, "hosted"), write_job(repo, "local", [LOCAL]))
    harbor = FakeHarbor()

    assert experiment(harbor) == 2

    assert harbor.ran == ["hosted/slug__00"]
    [event] = events(repo, "server-unreachable")
    assert (event["job"], event["server"]) == ("local", url)
    assert event["problem"].startswith(f"cannot reach {url}/health")
    assert events(repo, "invocation-finished")[-1]["outcome"] == "error"
    assert "job local needs the local model server" in capsys.readouterr().err


def test_a_local_job_with_its_server_up_runs(repo, monkeypatch, server):
    monkeypatch.setenv("ASSAY_LOCAL_BASE_URL", server.url)
    write_experiment(repo, write_job(repo, "local", [LOCAL]))
    harbor = FakeHarbor()

    assert experiment(harbor) == 0

    assert harbor.ran == ["local/slug__00"]
    assert events(repo, "server-unreachable") == []


def test_the_server_is_checked_again_before_a_retry(repo, monkeypatch, server):
    monkeypatch.setenv("ASSAY_LOCAL_BASE_URL", server.url)
    write_experiment(repo, write_job(repo, "local", [LOCAL]))

    def server_stops(builder):
        exception("NetworkConnectionError")(builder)
        server.status = 503

    harbor = FakeHarbor(outcomes={"local/slug__00": [server_stops]})

    assert experiment(harbor, "--retries", "1") == 2

    assert harbor.ran == ["local/slug__00"]
    assert [e["trial"] for e in events(repo, "trial-discarded")] == ["slug__00"]
    assert len(events(repo, "server-unreachable")) == 1
