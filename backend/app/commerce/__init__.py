"""Platform-neutral commerce domain boundaries."""

from app.commerce.contracts import (
    CommerceAnalysisMode,
    CommerceCapability,
    InteractionMode,
)
from app.commerce.snapshot import CommerceSnapshot, SnapshotState
from app.commerce.registry import CommerceDatasetRegistry, commerce_dataset_registry
from app.commerce.plan import (
    CommercePlanDraft,
    CommercePlanRequest,
    CommercePlanResponse,
    CommercePlanService,
    CommercePlanStatus,
)
from app.commerce.ingestion import (
    CommerceDataset,
    CommerceImportError,
    QualityReport,
    import_csv_package,
)
from app.commerce.metrics import (
    compare_sales_windows,
    compute_sales_report,
    discover_hot_products,
)
from app.commerce.tools import (
    COMMERCE_TALK_TOOLS,
    CommerceToolBatch,
    CommerceToolContext,
    execute_commerce_talk_tools,
)
from app.commerce.talk import (
    CommerceTalkRequest,
    CommerceTalkResponse,
    CommerceTalkService,
    route_talk_question,
)

__all__ = [
    "CommerceAnalysisMode",
    "CommerceCapability",
    "InteractionMode",
    "CommerceSnapshot",
    "SnapshotState",
    "CommerceDatasetRegistry",
    "commerce_dataset_registry",
    "CommercePlanDraft",
    "CommercePlanRequest",
    "CommercePlanResponse",
    "CommercePlanService",
    "CommercePlanStatus",
    "CommerceDataset",
    "CommerceImportError",
    "QualityReport",
    "import_csv_package",
    "compute_sales_report",
    "compare_sales_windows",
    "discover_hot_products",
    "COMMERCE_TALK_TOOLS",
    "CommerceToolBatch",
    "CommerceToolContext",
    "execute_commerce_talk_tools",
    "CommerceTalkRequest",
    "CommerceTalkResponse",
    "CommerceTalkService",
    "route_talk_question",
]
