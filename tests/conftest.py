"""Names the packaged fixtures, installs the dhis2 connection, and mocks the instance."""

from collections.abc import Iterator

import pytest
import respx
from pydantic import SecretStr

from dhis2server import BASE_URL, CONNECTION, instance
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
def dhis2() -> Iterator[respx.Router]:
    """Route the pack's dhis2w-client through respx, with the version probes already scripted."""
    with respx.mock(assert_all_called=False) as router:
        instance(router)
        yield router
