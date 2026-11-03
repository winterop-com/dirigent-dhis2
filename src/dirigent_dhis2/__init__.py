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
from dirigent_dhis2.data_set_completion import (
    Dhis2DataSetCompletionConfig,
    Dhis2DataSetCompletionOperator,
    Dhis2DataSetCompletionOutput,
)
from dirigent_dhis2.data_store import Dhis2DataStoreConfig, Dhis2DataStoreOperator, Dhis2DataStoreOutput
from dirigent_dhis2.data_value import Dhis2DataValueConfig, Dhis2DataValueOperator, Dhis2DataValueOutput
from dirigent_dhis2.export import (
    Dhis2DataValueSetExportConfig,
    Dhis2DataValueSetExportOperator,
    Dhis2DataValueSetExportOutput,
)
from dirigent_dhis2.formats import DHIS2_FORMATS, is_code, is_period, is_uid
from dirigent_dhis2.imports import (
    Dhis2DataValueSetImportConfig,
    Dhis2DataValueSetImportOperator,
    Dhis2DataValueSetImportOutput,
    Dhis2ImportConflict,
    Dhis2ImportCounts,
)
from dirigent_dhis2.messages import DHIS2
from dirigent_dhis2.messaging import Dhis2MessageConfig, Dhis2MessageOperator, Dhis2MessageOutput
from dirigent_dhis2.metadata import (
    Dhis2MetadataConfig,
    Dhis2MetadataOperator,
    Dhis2MetadataOutput,
)
from dirigent_dhis2.metadata_export import (
    Dhis2MetadataExportConfig,
    Dhis2MetadataExportOperator,
    Dhis2MetadataExportOutput,
    Dhis2MetadataSelection,
)
from dirigent_dhis2.metadata_import import (
    Dhis2MetadataImportConfig,
    Dhis2MetadataImportOperator,
    Dhis2MetadataImportOutput,
)
from dirigent_dhis2.predictor_run import Dhis2PredictorRunConfig, Dhis2PredictorRunOperator, Dhis2PredictorRunOutput
from dirigent_dhis2.reads import Dhis2Pager
from dirigent_dhis2.resource_tables import (
    Dhis2ResourceTablesRunConfig,
    Dhis2ResourceTablesRunOperator,
    Dhis2ResourceTablesRunOutput,
)
from dirigent_dhis2.sql_view import Dhis2SqlViewConfig, Dhis2SqlViewOperator, Dhis2SqlViewOutput
from dirigent_dhis2.system_info import (
    Dhis2SystemInfoConfig,
    Dhis2SystemInfoOperator,
    Dhis2SystemInfoOutput,
)
from dirigent_dhis2.task_wait import Dhis2TaskWaitConfig, Dhis2TaskWaitOperator, Dhis2TaskWaitOutput
from dirigent_dhis2.tracker import (
    Dhis2TrackerConfig,
    Dhis2TrackerOperator,
    Dhis2TrackerOutput,
)
from dirigent_dhis2.tracker_import import (
    Dhis2TrackerImportConfig,
    Dhis2TrackerImportOperator,
    Dhis2TrackerImportOutput,
)
from dirigent_dhis2.validation_run import (
    Dhis2ValidationRunConfig,
    Dhis2ValidationRunOperator,
    Dhis2ValidationRunOutput,
    Dhis2Violation,
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
                Dhis2DataSetCompletionOperator(),
                Dhis2DataStoreOperator(),
                Dhis2DataValueOperator(),
                Dhis2DataValueSetExportOperator(),
                Dhis2DataValueSetImportOperator(),
                Dhis2MessageOperator(),
                Dhis2MetadataOperator(),
                Dhis2MetadataExportOperator(),
                Dhis2MetadataImportOperator(),
                Dhis2PredictorRunOperator(),
                Dhis2ResourceTablesRunOperator(),
                Dhis2SqlViewOperator(),
                Dhis2SystemInfoOperator(),
                Dhis2TaskWaitOperator(),
                Dhis2TrackerOperator(),
                Dhis2TrackerImportOperator(),
                Dhis2ValidationRunOperator(),
            ],
            sensors=[Dhis2DataSetCompleteSensor()],
            connection_kinds=[Dhis2ConnectionKind()],
            formats=DHIS2_FORMATS,
            labels=[DHIS2],
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
    "Dhis2DataSetCompletionConfig",
    "Dhis2DataSetCompletionOperator",
    "Dhis2DataSetCompletionOutput",
    "Dhis2DataStoreConfig",
    "Dhis2DataStoreOperator",
    "Dhis2DataStoreOutput",
    "Dhis2DataValueConfig",
    "Dhis2DataValueOperator",
    "Dhis2DataValueOutput",
    "Dhis2DataValueSetExportConfig",
    "Dhis2DataValueSetExportOperator",
    "Dhis2DataValueSetExportOutput",
    "Dhis2DataValueSetImportConfig",
    "Dhis2DataValueSetImportOperator",
    "Dhis2DataValueSetImportOutput",
    "Dhis2ImportConflict",
    "Dhis2ImportCounts",
    "Dhis2MessageConfig",
    "Dhis2MessageOperator",
    "Dhis2MessageOutput",
    "Dhis2MetadataConfig",
    "Dhis2MetadataExportConfig",
    "Dhis2MetadataExportOperator",
    "Dhis2MetadataExportOutput",
    "Dhis2MetadataImportConfig",
    "Dhis2MetadataImportOperator",
    "Dhis2MetadataImportOutput",
    "Dhis2MetadataOperator",
    "Dhis2MetadataOutput",
    "Dhis2MetadataSelection",
    "Dhis2Operator",
    "Dhis2Pager",
    "Dhis2Plugin",
    "Dhis2PredictorRunConfig",
    "Dhis2PredictorRunOperator",
    "Dhis2PredictorRunOutput",
    "Dhis2ResourceTablesRunConfig",
    "Dhis2ResourceTablesRunOperator",
    "Dhis2ResourceTablesRunOutput",
    "Dhis2Sensor",
    "Dhis2SqlViewConfig",
    "Dhis2SqlViewOperator",
    "Dhis2SqlViewOutput",
    "Dhis2SystemInfoConfig",
    "Dhis2SystemInfoOperator",
    "Dhis2SystemInfoOutput",
    "Dhis2TaskWaitConfig",
    "Dhis2TaskWaitOperator",
    "Dhis2TaskWaitOutput",
    "Dhis2TrackerConfig",
    "Dhis2TrackerImportConfig",
    "Dhis2TrackerImportOperator",
    "Dhis2TrackerImportOutput",
    "Dhis2TrackerOperator",
    "Dhis2TrackerOutput",
    "Dhis2ValidationRunConfig",
    "Dhis2ValidationRunOperator",
    "Dhis2ValidationRunOutput",
    "Dhis2Violation",
    "build_client",
    "classify",
    "client_for",
    "is_code",
    "is_period",
    "is_uid",
    "plugin",
]
