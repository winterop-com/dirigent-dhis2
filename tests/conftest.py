"""Names the packaged fixtures, installs the dhis2 connection, and mocks the instance."""

import pytest
from pydantic import SecretStr

from dhis2server import BASE_URL, CONNECTION, Dhis2Server, serve
from dirigent_dhis2.connection import Dhis2ConnectionConfig
from dirigent_testing import FakeContext


def _install(context: FakeContext) -> FakeContext:
    """Give the context the dhis2 connection every block resolves its instance through."""
    context.connections[CONNECTION] = Dhis2ConnectionConfig(
        base_url=BASE_URL,
        basic_username="admin",
        basic_password=SecretStr("district"),
    )
    return context


@pytest.fixture
def ctx(block_ctx: FakeContext) -> FakeContext:
    return _install(block_ctx)


@pytest.fixture
def local_ctx(local_block_ctx: FakeContext) -> FakeContext:
    return _install(local_block_ctx)


@pytest.fixture
def dhis2(monkeypatch: pytest.MonkeyPatch) -> Dhis2Server:
    """Answer the pack's dhis2w-client from a fake instance, with the version probes scripted."""
    return serve(monkeypatch)
