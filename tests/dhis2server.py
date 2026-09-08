"""The canned answers a DHIS2 instance gives, shared by the block tests.

The pack talks to DHIS2 through ``dhis2w-client``, so the tests mock at that boundary with
``respx``: every block call opens a fresh client that resolves the canonical URL and reads
``/api/system/info`` before its own request, so :func:`instance` scripts those two probes and
the test adds the endpoint route it cares about.
"""

from typing import Any

import httpx
import respx

#: The connection code the conftest installs on every context.
CONNECTION = "dhis2-test"

#: The base URL the conftest's connection points at.
BASE_URL = "http://dhis2.test"


def json(status: int, payload: Any) -> httpx.Response:
    """Build a JSON response the block will parse."""
    return httpx.Response(status, json=payload)


def instance(router: respx.Router, *, base_url: str = BASE_URL, version: str = "2.42.0") -> None:
    """Script the redirect probe and ``/api/system/info`` a fresh client reads before its call."""
    router.get(f"{base_url}/").mock(return_value=httpx.Response(200, text="<html></html>"))
    router.get(f"{base_url}/api/system/info").mock(return_value=httpx.Response(200, json={"version": version}))


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
