"""Deterministic runtime primitives for Content 口播 Slim."""

from .client_manifest import (
    SUPPORTED_SPEAKER_MODES,
    ClientManifest,
    build_migration_candidate,
    load_manifest,
    resolve_asset_root,
    resolve_speaker_mode,
    validate_manifest,
)
from .client_registry import (
    ClientLocation,
    default_registry_path,
    default_runs_root,
    load_effective_registry,
    load_registry,
    resolve_client,
    select_client_id,
)
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
from .content_source import plan_obsidian_configuration, apply_obsidian_configuration
from .vault_reader import read_method_asset, read_primary_profile, read_selected_profile
from .vault_search import search_knowledge_assets, search_method_assets

__all__ = [
    "SUPPORTED_SPEAKER_MODES",
    "ClientLocation",
    "ClientManifest",
    "RunStore",
    "SlimRuntimeError",
    "SlimStateMachine",
    "build_migration_candidate",
    "default_registry_path",
    "default_runs_root",
    "load_manifest",
    "load_registry",
    "load_effective_registry",
    "preflight_references",
    "read_method_asset",
    "read_primary_profile",
    "read_selected_profile",
    "plan_obsidian_configuration",
    "apply_obsidian_configuration",
    "resolve_asset_root",
    "resolve_client",
    "resolve_speaker_mode",
    "search_method_assets",
    "search_knowledge_assets",
    "select_client_id",
    "validate_analyzer_input",
    "validate_analyzer_result",
    "validate_content_context",
    "validate_context_retriever_input",
    "validate_writer_context",
    "validate_writer_result",
    "validate_manifest",
    "write_prepared_references",
]
