"""Import one immutable MatrAIx persona dataset from an explicit local directory.

Run with ``python -m app.populations.import_matraix`` after configuring
``MATRAIX_PERSONA_DATASET_PATH`` and ``DATABASE_URL``. Dataset files are parsed
and content-addressed before the database transaction begins.
"""

import asyncio
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

import yaml
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken

from app.config import ConfigurationError, DatabaseUrl, parse_database_url
from app.database import normalize_async_database_url
from app.populations.contracts import StoredPersonaProfile
from app.populations.hashing import (
    calculate_persona_profile_sha256,
    canonical_persona_profile_json,
)

DATASET_SCHEMA = "matraix-persona-dataset/v1"
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
IMPORT_ADVISORY_NAMESPACE = 0x4D41545241495850
REQUIRED_TABLES = (
    "persona_datasets",
    "personas",
    "cohorts",
    "cohort_members",
)


class PopulationImportError(RuntimeError):
    """Base error for a rejected or failed persona dataset import."""


class PopulationImportConfigurationError(PopulationImportError):
    """Raised when an importer environment setting is absent or invalid."""


class PopulationDatasetError(PopulationImportError):
    """Raised when a MatrAIx manifest or persona file violates the contract."""


class PopulationImportRuntimeError(PopulationImportError):
    """Raised when the target database cannot atomically accept the dataset."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader whose mapping constructor rejects duplicate keys."""


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=False)
        if not isinstance(key, str):
            raise ConstructorError(
                None,
                None,
                "mapping keys must be strings",
                key_node.start_mark,
            )
        if key in result:
            raise ConstructorError(
                None, None, f"duplicate mapping key {key!r}", key_node.start_mark
            )
        result[key] = loader.construct_object(value_node, deep=False)
    return result


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


@dataclass(frozen=True, slots=True)
class ImportSettings:
    """Validated importer inputs with no implicit dataset location."""

    dataset_path: Path
    database_url: DatabaseUrl


@dataclass(frozen=True, slots=True)
class ParsedPersona:
    """One validated ordered persona and its canonical content address."""

    position: int
    profile: StoredPersonaProfile
    profile_json: str
    profile_sha256: str


@dataclass(frozen=True, slots=True)
class ParsedDataset:
    """One complete, validated, content-addressed MatrAIx dataset."""

    slug: str
    display_name: str
    schema_version: str
    parent_pool: str | None
    source_repository: str | None
    persona_count: int
    manifest_sha256: str
    dataset_sha256: str
    personas: tuple[ParsedPersona, ...]


@dataclass(frozen=True, slots=True)
class PopulationImportResult:
    """Non-sensitive result of one atomic dataset import attempt."""

    dataset_id: UUID
    dataset_sha256: str
    persona_count: int
    created: bool


def _required_environment_value(
    environment: Mapping[str, str],
    variable_name: str,
) -> str:
    value = environment.get(variable_name)
    if value is None or not value.strip():
        raise PopulationImportConfigurationError(f"{variable_name} must be configured")
    return value


def load_import_settings(environment: Mapping[str, str]) -> ImportSettings:
    """Load an explicit dataset directory and validated PostgreSQL target."""
    configured_path = _required_environment_value(environment, "MATRAIX_PERSONA_DATASET_PATH")
    try:
        dataset_path = Path(configured_path).expanduser().resolve(strict=True)
    except OSError as error:
        raise PopulationImportConfigurationError(
            "MATRAIX_PERSONA_DATASET_PATH must identify a readable dataset directory"
        ) from error
    if not dataset_path.is_dir():
        raise PopulationImportConfigurationError(
            "MATRAIX_PERSONA_DATASET_PATH must identify a readable dataset directory"
        )

    configured_database_url = _required_environment_value(environment, "DATABASE_URL")
    try:
        database_url = parse_database_url(configured_database_url)
    except ConfigurationError as error:
        raise PopulationImportConfigurationError(str(error)) from error
    if database_url is None:
        raise PopulationImportConfigurationError("DATABASE_URL must be configured")
    return ImportSettings(dataset_path=dataset_path, database_url=database_url)


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise PopulationDatasetError(f"manifest contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise PopulationDatasetError(f"manifest contains unsupported numeric constant {value!r}")


def _read_text(path: Path, resource_name: str) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            raise PopulationDatasetError(f"{resource_name} must be a regular file")
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise PopulationDatasetError(f"{resource_name} must be valid UTF-8") from error
    except OSError as error:
        raise PopulationDatasetError(f"{resource_name} could not be read") from error


def _parse_manifest(dataset_path: Path) -> tuple[dict[str, object], str]:
    content = _read_text(dataset_path / "manifest.json", "manifest.json")
    try:
        parsed = json.loads(
            content,
            object_pairs_hook=_strict_json_object,
            parse_constant=_reject_json_constant,
        )
    except PopulationDatasetError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        raise PopulationDatasetError("manifest.json must contain valid strict JSON") from error
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise PopulationDatasetError("manifest.json root must be an object with string keys")
    canonical = json.dumps(
        parsed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return parsed, sha256(canonical.encode("utf-8")).hexdigest()


def _parse_yaml(content: str, persona_id: str) -> dict[str, object]:
    try:
        if any(isinstance(token, (AliasToken, AnchorToken)) for token in yaml.scan(content)):
            raise PopulationDatasetError(
                f"persona {persona_id!r} must not contain YAML anchors or aliases"
            )
        parsed = yaml.load(content, Loader=_UniqueKeySafeLoader)
    except PopulationDatasetError:
        raise
    except yaml.YAMLError as error:
        raise PopulationDatasetError(
            f"persona {persona_id!r} must contain valid strict YAML"
        ) from error
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise PopulationDatasetError(f"persona {persona_id!r} YAML root must be an object")
    return parsed


def _mapping(value: object, field_name: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PopulationDatasetError(f"{field_name} must be an object with string keys")
    return value


def _list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise PopulationDatasetError(f"{field_name} must be an array")
    return value


def _required_string(
    mapping: Mapping[str, object],
    field_name: str,
    maximum_length: int,
) -> str:
    value = mapping.get(field_name)
    if not isinstance(value, str):
        raise PopulationDatasetError(f"{field_name} must be a string")
    stripped = value.strip()
    if not stripped or len(stripped) > maximum_length or "\r" in stripped or "\n" in stripped:
        raise PopulationDatasetError(
            f"{field_name} must contain 1..{maximum_length} characters on one line"
        )
    return stripped


def _optional_string(
    mapping: Mapping[str, object],
    field_name: str,
    maximum_length: int,
) -> str | None:
    value = mapping.get(field_name)
    if value is None:
        return None
    return _required_string(mapping, field_name, maximum_length)


def _required_identifier(
    mapping: Mapping[str, object],
    field_name: str,
    maximum_length: int,
) -> str:
    value = _required_string(mapping, field_name, maximum_length)
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise PopulationDatasetError(
            f"{field_name} must start with an alphanumeric character and contain only "
            "letters, digits, dot, underscore, colon, or hyphen"
        )
    return value


def _required_integer(
    mapping: Mapping[str, object],
    field_name: str,
    minimum: int,
    maximum: int,
) -> int:
    value = mapping.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PopulationDatasetError(f"{field_name} must be an integer")
    if not minimum <= value <= maximum:
        raise PopulationDatasetError(f"{field_name} must be between {minimum} and {maximum}")
    return value


def _manifest_source_repository(manifest: Mapping[str, object]) -> str | None:
    hf_repo = _optional_string(manifest, "hf_repo", 500)
    source_dataset = _optional_string(manifest, "source_dataset", 500)
    if hf_repo is not None and source_dataset is not None and hf_repo != source_dataset:
        raise PopulationDatasetError(
            "manifest hf_repo and source_dataset must agree when both are provided"
        )
    return hf_repo if hf_repo is not None else source_dataset


def _persona_filename(
    entry: Mapping[str, object],
    persona_id: str,
    dataset_slug: str,
) -> str:
    expected_filename = f"persona_{persona_id}.yaml"
    path_value = entry.get("path")
    if path_value is None:
        return expected_filename
    if not isinstance(path_value, str) or not path_value or "\\" in path_value:
        raise PopulationDatasetError(f"persona {persona_id!r} path must be a relative POSIX path")
    manifest_path = PurePosixPath(path_value)
    if manifest_path.is_absolute() or any(part in ("", ".", "..") for part in manifest_path.parts):
        raise PopulationDatasetError(f"persona {persona_id!r} path leaves the dataset boundary")
    if manifest_path.name != expected_filename:
        raise PopulationDatasetError(
            f"persona {persona_id!r} path must end with {expected_filename!r}"
        )
    if len(manifest_path.parts) > 1 and manifest_path.parts[-2] != dataset_slug:
        raise PopulationDatasetError(
            f"persona {persona_id!r} path must identify the configured dataset"
        )
    return expected_filename


def _manifest_persona_files(
    manifest: Mapping[str, object],
    dataset_slug: str,
    persona_count: int,
) -> tuple[tuple[str, str], ...]:
    entries = _list(manifest.get("personas"), "manifest personas")
    if len(entries) != persona_count:
        raise PopulationDatasetError(
            "manifest count must equal the number of manifest persona entries"
        )
    identities: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    seen_filenames: set[str] = set()
    for position, raw_entry in enumerate(entries):
        entry = _mapping(raw_entry, f"manifest persona entry {position}")
        persona_id = _required_identifier(entry, "persona_id", 128)
        filename = _persona_filename(entry, persona_id, dataset_slug)
        if persona_id in seen_ids:
            raise PopulationDatasetError(f"manifest contains duplicate persona_id {persona_id!r}")
        if filename in seen_filenames:
            raise PopulationDatasetError(f"manifest contains duplicate persona file {filename!r}")
        seen_ids.add(persona_id)
        seen_filenames.add(filename)
        identities.append((persona_id, filename))
    return tuple(identities)


def _validate_file_inventory(
    dataset_path: Path,
    identities: tuple[tuple[str, str], ...],
) -> None:
    try:
        actual_files = {
            candidate.name
            for candidate in dataset_path.iterdir()
            if candidate.name.startswith("persona_") and candidate.suffix == ".yaml"
        }
    except OSError as error:
        raise PopulationDatasetError("dataset directory could not be enumerated") from error
    expected_files = {filename for _persona_id, filename in identities}
    missing = sorted(expected_files - actual_files)
    unexpected = sorted(actual_files - expected_files)
    if missing:
        raise PopulationDatasetError(
            "dataset is missing persona files declared by the manifest: " + ", ".join(missing)
        )
    if unexpected:
        raise PopulationDatasetError(
            "dataset contains persona files absent from the manifest: " + ", ".join(unexpected)
        )


def _dimensions(value: object, persona_id: str) -> dict[str, str]:
    raw_dimensions = _mapping(value, f"persona {persona_id!r} dimensions")
    if not raw_dimensions:
        raise PopulationDatasetError(f"persona {persona_id!r} dimensions must not be empty")
    dimensions: dict[str, str] = {}
    for name, raw_value in raw_dimensions.items():
        if IDENTIFIER_PATTERN.fullmatch(name) is None or len(name) > 128:
            raise PopulationDatasetError(
                f"persona {persona_id!r} contains an invalid dimension name"
            )
        if not isinstance(raw_value, str):
            raise PopulationDatasetError(
                f"persona {persona_id!r} dimension {name!r} must be a string"
            )
        value = raw_value.strip()
        if not value or len(value) > 500 or "\r" in value or "\n" in value:
            raise PopulationDatasetError(
                f"persona {persona_id!r} dimension {name!r} must contain "
                "1..500 characters on one line"
            )
        dimensions[name] = value
    return dict(sorted(dimensions.items()))


def _provenance(value: object, persona_id: str) -> dict[str, str | int | None]:
    raw = {} if value is None else _mapping(value, f"persona {persona_id!r} provenance")
    origin_source_row_index_value = raw.get("origin_source_row_index")
    if origin_source_row_index_value is not None and (
        isinstance(origin_source_row_index_value, bool)
        or not isinstance(origin_source_row_index_value, int)
        or origin_source_row_index_value < 0
    ):
        raise PopulationDatasetError(
            f"persona {persona_id!r} provenance origin_source_row_index "
            "must be a non-negative integer or null"
        )
    return {
        "hf_repo": _optional_string(raw, "hf_repo", 500),
        "origin_persona_id": _optional_string(raw, "origin_persona_id", 128),
        "origin_source_row_index": origin_source_row_index_value,
        "parent_pool": _optional_string(raw, "parent_pool", 500),
    }


def _parse_persona(
    dataset_path: Path,
    position: int,
    expected_persona_id: str,
    filename: str,
) -> ParsedPersona:
    persona_path = dataset_path / filename
    try:
        if persona_path.resolve(strict=True).parent != dataset_path:
            raise PopulationDatasetError(
                f"persona {expected_persona_id!r} file leaves the dataset boundary"
            )
    except OSError as error:
        raise PopulationDatasetError(
            f"persona {expected_persona_id!r} file could not be resolved"
        ) from error
    content = _read_text(persona_path, f"persona {expected_persona_id!r} file")
    raw = _parse_yaml(content, expected_persona_id)
    persona_id = _required_identifier(raw, "persona_id", 128)
    if persona_id != expected_persona_id:
        raise PopulationDatasetError(
            f"persona file {filename!r} declares persona_id {persona_id!r}; "
            f"expected {expected_persona_id!r}"
        )
    profile_payload = {
        "display_name": _required_string(raw, "display_name", 200),
        "dimensions": _dimensions(raw.get("dimensions"), persona_id),
        "persona_id": persona_id,
        "provenance": _provenance(raw.get("provenance"), persona_id),
        "source": _required_identifier(raw, "source", 128),
        "version": _required_identifier(raw, "version", 32),
    }
    try:
        profile = StoredPersonaProfile.model_validate(profile_payload, strict=True)
    except ValidationError as error:
        raise PopulationDatasetError(
            f"persona {persona_id!r} does not satisfy the canonical profile contract"
        ) from error
    profile_json = canonical_persona_profile_json(profile)
    return ParsedPersona(
        position=position,
        profile=profile,
        profile_json=profile_json,
        profile_sha256=calculate_persona_profile_sha256(profile),
    )


def canonical_persona_dataset_json(dataset: ParsedDataset) -> str:
    """Serialize exact dataset metadata plus ordered persona content addresses."""
    payload = {
        "schema": DATASET_SCHEMA,
        "slug": dataset.slug,
        "display_name": dataset.display_name,
        "schema_version": dataset.schema_version,
        "parent_pool": dataset.parent_pool,
        "source_repository": dataset.source_repository,
        "persona_count": dataset.persona_count,
        "manifest_sha256": dataset.manifest_sha256,
        "personas": [
            {
                "persona_id": persona.profile.persona_id,
                "profile_sha256": persona.profile_sha256,
            }
            for persona in dataset.personas
        ],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def parse_dataset(dataset_path: Path) -> ParsedDataset:
    """Parse and validate the complete dataset without mutating external state."""
    manifest, manifest_sha256 = _parse_manifest(dataset_path)
    slug = _required_identifier(manifest, "kind", 128)
    display_name = slug
    schema_version = _required_identifier(manifest, "schema_version", 32)
    persona_count = _required_integer(manifest, "count", 1, 1_000_000)
    identities = _manifest_persona_files(manifest, slug, persona_count)
    _validate_file_inventory(dataset_path, identities)
    personas = tuple(
        _parse_persona(dataset_path, position, persona_id, filename)
        for position, (persona_id, filename) in enumerate(identities)
    )
    draft = ParsedDataset(
        slug=slug,
        display_name=display_name,
        schema_version=schema_version,
        parent_pool=_optional_string(manifest, "parent_pool", 500),
        source_repository=_manifest_source_repository(manifest),
        persona_count=persona_count,
        manifest_sha256=manifest_sha256,
        dataset_sha256="0" * 64,
        personas=personas,
    )
    dataset_sha256 = sha256(canonical_persona_dataset_json(draft).encode("utf-8")).hexdigest()
    return ParsedDataset(
        slug=draft.slug,
        display_name=draft.display_name,
        schema_version=draft.schema_version,
        parent_pool=draft.parent_pool,
        source_repository=draft.source_repository,
        persona_count=draft.persona_count,
        manifest_sha256=draft.manifest_sha256,
        dataset_sha256=dataset_sha256,
        personas=draft.personas,
    )


def _advisory_lock_key(dataset_sha256: str) -> int:
    unsigned_key = int(dataset_sha256[:16], 16) ^ IMPORT_ADVISORY_NAMESPACE
    return unsigned_key - (1 << 64) if unsigned_key >= (1 << 63) else unsigned_key


async def _validate_target_schema(connection: AsyncConnection) -> None:
    result = await connection.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ANY(:table_names)"
        ),
        {"table_names": list(REQUIRED_TABLES)},
    )
    existing = frozenset(str(row[0]) for row in result)
    missing = tuple(table_name for table_name in REQUIRED_TABLES if table_name not in existing)
    if missing:
        raise PopulationImportRuntimeError(
            "target database is missing MatrAIx population tables; run Alembic migrations first"
        )


async def _existing_import(
    connection: AsyncConnection,
    dataset: ParsedDataset,
) -> PopulationImportResult | None:
    result = await connection.execute(
        text(
            "SELECT id, persona_count, sealed_at FROM persona_datasets "
            "WHERE dataset_sha256 = :dataset_sha256"
        ),
        {"dataset_sha256": dataset.dataset_sha256},
    )
    row = result.mappings().one_or_none()
    if row is None:
        return None
    if row["sealed_at"] is None:
        raise PopulationImportRuntimeError(
            "an unsealed persona dataset already owns this content address"
        )
    if int(row["persona_count"]) != dataset.persona_count:
        raise PopulationImportRuntimeError(
            "stored persona dataset metadata disagrees with its content address"
        )
    return PopulationImportResult(
        dataset_id=UUID(str(row["id"])),
        dataset_sha256=dataset.dataset_sha256,
        persona_count=dataset.persona_count,
        created=False,
    )


async def _insert_dataset(
    connection: AsyncConnection,
    dataset: ParsedDataset,
) -> PopulationImportResult:
    dataset_id = uuid4()
    created_at = datetime.now(UTC)
    await connection.execute(
        text(
            """
            INSERT INTO persona_datasets (
                id, slug, display_name, schema_version, parent_pool,
                source_repository, persona_count, manifest_sha256,
                dataset_sha256, created_at, sealed_at
            ) VALUES (
                :id, :slug, :display_name, :schema_version, :parent_pool,
                :source_repository, :persona_count, :manifest_sha256,
                :dataset_sha256, :created_at, NULL
            )
            """
        ),
        {
            "id": dataset_id,
            "slug": dataset.slug,
            "display_name": dataset.display_name,
            "schema_version": dataset.schema_version,
            "parent_pool": dataset.parent_pool,
            "source_repository": dataset.source_repository,
            "persona_count": dataset.persona_count,
            "manifest_sha256": dataset.manifest_sha256,
            "dataset_sha256": dataset.dataset_sha256,
            "created_at": created_at,
        },
    )
    await connection.execute(
        text(
            """
            INSERT INTO personas (
                id, dataset_id, position, persona_id, display_name,
                source, profile_json, profile_sha256
            ) VALUES (
                :id, :dataset_id, :position, :persona_id, :display_name,
                :source, CAST(:profile_json AS jsonb), :profile_sha256
            )
            """
        ),
        [
            {
                "id": uuid4(),
                "dataset_id": dataset_id,
                "position": persona.position,
                "persona_id": persona.profile.persona_id,
                "display_name": persona.profile.display_name,
                "source": persona.profile.source,
                "profile_json": persona.profile_json,
                "profile_sha256": persona.profile_sha256,
            }
            for persona in dataset.personas
        ],
    )
    await connection.execute(
        text("UPDATE persona_datasets SET sealed_at = created_at WHERE id = :dataset_id"),
        {"dataset_id": dataset_id},
    )
    return PopulationImportResult(
        dataset_id=dataset_id,
        dataset_sha256=dataset.dataset_sha256,
        persona_count=dataset.persona_count,
        created=True,
    )


async def import_matraix_personas(
    settings: ImportSettings,
    dataset: ParsedDataset,
) -> PopulationImportResult:
    """Atomically insert and seal one dataset, or return its existing identity."""
    engine = create_async_engine(
        normalize_async_database_url(settings.database_url),
        pool_pre_ping=True,
    )
    try:
        async with engine.begin() as connection:
            await _validate_target_schema(connection)
            await connection.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _advisory_lock_key(dataset.dataset_sha256)},
            )
            existing = await _existing_import(connection, dataset)
            if existing is not None:
                return existing
            return await _insert_dataset(connection, dataset)
    except PopulationImportRuntimeError:
        raise
    except SQLAlchemyError as error:
        raise PopulationImportRuntimeError(
            "MatrAIx persona import failed during a database operation; "
            "verify migration state and target write access"
        ) from error
    finally:
        await engine.dispose()


async def _run() -> int:
    try:
        settings = load_import_settings(os.environ)
        dataset = parse_dataset(settings.dataset_path)
        result = await import_matraix_personas(settings, dataset)
    except PopulationImportError as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=False))
        return 2
    print(
        json.dumps(
            {
                "status": "created" if result.created else "existing",
                "dataset_id": str(result.dataset_id),
                "dataset_sha256": result.dataset_sha256,
                "persona_count": result.persona_count,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def main() -> None:
    """Run the explicit dataset importer and terminate with its process status."""
    raise SystemExit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
