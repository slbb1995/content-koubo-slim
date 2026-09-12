"""Deterministic runtime primitives for Content V2 Slim."""

from .binding_setup import (
    BindingPlan,
    BindingSetupError,
    configure_zsk_binding,
    default_client_id,
    plan_zsk_binding,
)
from .client_manifest import (
    SUPPORTED_SPEAKER_MODES,
    ClientManifest,
    build_migration_candidate,
    load_manifest,
    resolve_asset_root,
    resolve_speaker_mode,
    validate_manifest,
)
from .client_registry import ClientLocation, load_registry, resolve_client
from .error_model import SlimRuntimeError
from .reference_prep import preflight_references, write_prepared_references
from .run_store import RunStore
from .schema_validation import (
    validate_analyzer_input,
    validate_analyzer_result,
    validate_content_context,
    validate_context_retriever_input,
    validate_writer_context,
    validate_writer_result,
)
from .state_machine import SlimStateMachine
from .vault_reader import read_method_asset, read_primary_profile
from .vault_search import search_knowledge_assets, search_method_assets

__all__ = [
    "BindingPlan",
    "BindingSetupError",
    "SUPPORTED_SPEAKER_MODES",
    "ClientLocation",
    "ClientManifest",
    "RunStore",
    "SlimRuntimeError",
    "SlimStateMachine",
    "build_migration_candidate",
    "configure_zsk_binding",
    "default_client_id",
    "load_manifest",
    "load_registry",
    "preflight_references",
    "plan_zsk_binding",
    "read_method_asset",
    "read_primary_profile",
    "resolve_asset_root",
    "resolve_client",
    "resolve_speaker_mode",
    "search_method_assets",
    "search_knowledge_assets",
    "validate_analyzer_input",
    "validate_analyzer_result",
    "validate_content_context",
    "validate_context_retriever_input",
    "validate_writer_context",
    "validate_writer_result",
    "validate_manifest",
    "write_prepared_references",
]
