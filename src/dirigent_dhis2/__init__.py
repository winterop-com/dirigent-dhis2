"""The DHIS2 adapter pack: the ``dhis2`` connection kind and the blocks for one instance."""

from collections.abc import Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable

from dirigent_dhis2.analytics import (
    Dhis2AnalyticsRunConfig,
    Dhis2AnalyticsRunOperator,
    Dhis2AnalyticsRunOutput,
)
from dirigent_dhis2.analytics_query import (
    Dhis2AnalyticsQueryConfig,
    Dhis2AnalyticsQueryOperator,
    Dhis2AnalyticsQueryOutput,
)
from dirigent_dhis2.complete import (
    Dhis2DataSetCompleteConfig,
    Dhis2DataSetCompleteOutput,
    Dhis2DataSetCompleteSensor,
)
from dirigent_dhis2.connection import (
    Dhis2ConnectionConfig,
    Dhis2ConnectionKind,
    build_client,
    client_for,
)
from dirigent_dhis2.export import (
    Dhis2DataValueSetExportConfig,
    Dhis2DataValueSetExportOperator,
    Dhis2DataValueSetExportOutput,
)
from dirigent_dhis2.formats import DHIS2_FORMATS, is_period, is_uid
from dirigent_dhis2.imports import (
    Dhis2DataValueSetImportConfig,
    Dhis2DataValueSetImportOperator,
    Dhis2DataValueSetImportOutput,
    Dhis2ImportConflict,
)
from dirigent_dhis2.metadata import (
    Dhis2MetadataConfig,
    Dhis2MetadataOperator,
    Dhis2MetadataOutput,
)
from dirigent_dhis2.tracker import (
    Dhis2TrackerConfig,
    Dhis2TrackerOperator,
    Dhis2TrackerOutput,
)
from dirigent_dhis2.web import Dhis2Operator, Dhis2Sensor, classify
from dirigent_plugin import Contribution, extension

#: The directory the pack's example shelves live in, inside this distribution.
SHELVES_DIRECTORY = "shelves"


class Dhis2Plugin:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the DHIS2 blocks and the ``dhis2`` connection kind they are configured from."""
        return Contribution(
            operators=[
                Dhis2AnalyticsRunOperator(),
                Dhis2AnalyticsQueryOperator(),
                Dhis2DataValueSetExportOperator(),
                Dhis2DataValueSetImportOperator(),
                Dhis2MetadataOperator(),
                Dhis2TrackerOperator(),
            ],
            sensors=[Dhis2DataSetCompleteSensor()],
            connection_kinds=[Dhis2ConnectionKind()],
            formats=DHIS2_FORMATS,
        )

    # optional=True keeps the pack loadable against a host whose dirigent-plugin predates the
    # examples() extension point, where an unknown implementation is a registration error.
    @extension(optional=True)
    def examples(self) -> Sequence[Traversable]:
        """Contribute the example shelves this distribution carries."""
        return [files(__package__ or "dirigent_dhis2") / SHELVES_DIRECTORY]


plugin = Dhis2Plugin()

__all__ = [
    "DHIS2_FORMATS",
    "SHELVES_DIRECTORY",
    "Dhis2AnalyticsQueryConfig",
    "Dhis2AnalyticsQueryOperator",
    "Dhis2AnalyticsQueryOutput",
    "Dhis2AnalyticsRunConfig",
    "Dhis2AnalyticsRunOperator",
    "Dhis2AnalyticsRunOutput",
    "Dhis2ConnectionConfig",
    "Dhis2ConnectionKind",
    "Dhis2DataSetCompleteConfig",
    "Dhis2DataSetCompleteOutput",
    "Dhis2DataSetCompleteSensor",
    "Dhis2DataValueSetExportConfig",
    "Dhis2DataValueSetExportOperator",
    "Dhis2DataValueSetExportOutput",
    "Dhis2DataValueSetImportConfig",
    "Dhis2DataValueSetImportOperator",
    "Dhis2DataValueSetImportOutput",
    "Dhis2ImportConflict",
    "Dhis2MetadataConfig",
    "Dhis2MetadataOperator",
    "Dhis2MetadataOutput",
    "Dhis2Operator",
    "Dhis2Plugin",
    "Dhis2Sensor",
    "Dhis2TrackerConfig",
    "Dhis2TrackerOperator",
    "Dhis2TrackerOutput",
    "build_client",
    "classify",
    "client_for",
    "is_period",
    "is_uid",
    "plugin",
]
