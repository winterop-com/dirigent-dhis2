"""The canned answers a DHIS2 instance gives, shared by the block tests.

The pack talks to DHIS2 through ``dhis2w-client``, which opens its own ``httpx2`` clients: a
throwaway one that resolves the canonical URL, then the pooled one every call goes through.
:func:`serve` swaps ``httpx2.AsyncClient`` for one bound to an ``httpx2.MockTransport``, so
each of them answers from the scripted routes and no mocking library is involved. A fresh
client resolves the canonical URL and reads ``/api/system/info`` before its own request, so a
served instance scripts those two probes and the test adds the endpoint route it cares about.
"""

from typing import Any, Self

import httpx2
import pytest

#: The connection code the conftest installs on every context.
CONNECTION = "dhis2-test"

#: The base URL the conftest's connection points at.
BASE_URL = "http://dhis2.test"


def json(status: int, payload: Any) -> httpx2.Response:
    """Build a JSON response the block will parse."""
    return httpx2.Response(status, json=payload)


class Route:
    """One scripted endpoint: what it answers with, and the requests it has taken."""

    def __init__(self) -> None:
        """Start with nothing scripted and nothing taken."""
        self.requests: list[httpx2.Request] = []
        self._response: httpx2.Response | None = None
        self._error: Exception | None = None

    def answers(self, response: httpx2.Response) -> Self:
        """Answer every request on this route with this response."""
        self._response = response
        self._error = None
        return self

    def raises(self, error: Exception) -> Self:
        """Fail every request on this route with this error, the way a transport fails."""
        self._error = error
        self._response = None
        return self

    @property
    def last(self) -> httpx2.Request:
        """The most recent request this route took."""
        return self.requests[-1]

    def take(self, request: httpx2.Request) -> httpx2.Response:
        """Record the request and give this route's answer.

        The response is rebuilt per call: one httpx2 response carries the read state of the
        exchange it belongs to, so handing the same object to two calls is not safe.
        """
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._response is None:
            raise AssertionError(f"{request.method} {request.url} has a route but no answer")
        return httpx2.Response(
            self._response.status_code, content=self._response.content, headers=self._response.headers
        )


class Dhis2Server:
    """A fake DHIS2 instance: routes keyed by method and path, answered from memory."""

    def __init__(self) -> None:
        """Start with no routes at all."""
        self.routes: dict[tuple[str, str], Route] = {}

    def instance(self, *, base_url: str = BASE_URL, version: str = "2.42.0") -> None:
        """Script the redirect probe and ``/api/system/info`` a fresh client reads before its call."""
        self.get(f"{base_url}/").answers(httpx2.Response(200, text="<html></html>"))
        self.get(f"{base_url}/api/system/info").answers(json(200, {"version": version}))

    def get(self, url: str) -> Route:
        """The route a GET of this URL is answered from, scripting it the first time."""
        return self._route("GET", url)

    def post(self, url: str) -> Route:
        """The route a POST to this URL is answered from, scripting it the first time."""
        return self._route("POST", url)

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        """Answer one request, or fail the test naming the route nobody scripted."""
        route = self.routes.get((request.method, _key(request.url)))
        if route is None:
            raise AssertionError(f"no route scripted for {request.method} {request.url}")
        return route.take(request)

    def _route(self, method: str, url: str) -> Route:
        return self.routes.setdefault((method, _key(httpx2.URL(url))), Route())


def _key(url: httpx2.URL) -> str:
    """The origin and path a route matches on: the query string belongs to the assertions."""
    return f"{url.scheme}://{url.netloc.decode()}{url.path}"


def serve(monkeypatch: pytest.MonkeyPatch, *, base_url: str = BASE_URL, version: str = "2.42.0") -> Dhis2Server:
    """Answer every client the pack opens from a fresh fake instance, version probes scripted.

    A client built with a transport of its own keeps it, so the doubles a FakeContext installs
    go on answering for themselves.
    """
    server = Dhis2Server()
    server.instance(base_url=base_url, version=version)
    real = httpx2.AsyncClient

    def build(**kwargs: Any) -> httpx2.AsyncClient:
        kwargs.setdefault("transport", httpx2.MockTransport(server.handle))
        return real(**kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", build)
    return server


def submitted(
    *, job_type: str = "ANALYTICS_TABLE", task_uid: str = "tk123", endpoint: str | None = None
) -> dict[str, Any]:
    """The job-kickoff envelope an analytics submission gives: its task ref and notifier endpoint."""
    endpoint = endpoint or f"/api/system/tasks/{job_type}/{task_uid}"
    return {
        "httpStatus": "OK",
        "status": "OK",
        "response": {"jobType": job_type, "id": task_uid, "relativeNotifierEndpoint": endpoint},
    }


def notification(
    message: str, *, time: str, level: str = "INFO", completed: bool = False, uid: str | None = None
) -> dict[str, Any]:
    """One task notification, as the ``/api/system/tasks`` feed tells it."""
    entry: dict[str, Any] = {"level": level, "time": time, "message": message, "completed": completed}
    if uid is not None:
        entry["uid"] = uid
    return entry


def task_feed(*notifications: dict[str, Any]) -> dict[str, Any]:
    """The task-status feed answer: notifications newest first under ``data`` the way DHIS2 answers."""
    return {"data": list(notifications)}


def summary(
    status: str,
    *,
    imported: int = 0,
    updated: int = 0,
    ignored: int = 0,
    deleted: int = 0,
    conflicts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """An import's answer, with the summary wrapped in ``response`` the way DHIS2 answers.

    A taken import gets this on 200; one the instance refused gets the same body on 409.
    """
    body: dict[str, Any] = {
        "responseType": "ImportSummary",
        "status": status,
        "importCount": {"imported": imported, "updated": updated, "ignored": ignored, "deleted": deleted},
        "conflicts": conflicts or [],
    }
    return {"httpStatus": "OK", "status": "OK", "response": body}
