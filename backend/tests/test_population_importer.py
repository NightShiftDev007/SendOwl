"""MatrAIx persona dataset parsing, addressing, and CLI mount tests."""

import json
from hashlib import sha256
from pathlib import Path

import pytest

from app.populations.hashing import canonical_persona_profile_json
from app.populations.import_matraix import (
    DATASET_SCHEMA,
    PopulationDatasetError,
    PopulationImportConfigurationError,
    canonical_persona_dataset_json,
    load_import_settings,
    parse_dataset,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]


def _write_dataset(root: Path) -> Path:
    dataset = root / "sample-personas"
    dataset.mkdir()
    manifest = {
        "kind": "sample-personas",
        "count": 2,
        "schema_version": "1.0",
        "parent_pool": "persona/datasets/matraix-persona-1m",
        "hf_repo": "MatrAIx2026/MatrAIx_Persona_1M_Public_Release",
        "personas": [
            {
                "persona_id": "alpha",
                "path": "persona/datasets/sample-personas/persona_alpha.yaml",
            },
            {
                "persona_id": "beta",
                "path": "persona/datasets/sample-personas/persona_beta.yaml",
            },
        ],
    }
    (dataset / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    (dataset / "persona_alpha.yaml").write_text(
        """persona_id: alpha
version: '1.0'
source: wiki
display_name: 阿尔法
dimensions:
  region: East Asia
  risk_tolerance: Balanced
provenance:
  parent_pool: persona/datasets/matraix-persona-1m
  hf_repo: MatrAIx2026/MatrAIx_Persona_1M_Public_Release
  origin_persona_id: wiki-alpha
  origin_source_row_index: 7
  ignored_private_field: not-persisted
""",
        encoding="utf-8",
    )
    (dataset / "persona_beta.yaml").write_text(
        """source: synthetic
dimensions:
  intent: Learn / explain
display_name: Beta Person
persona_id: beta
version: '1.0'
""",
        encoding="utf-8",
    )
    return dataset.resolve()


def test_import_settings_require_an_explicit_readable_dataset_path(tmp_path: Path) -> None:
    with pytest.raises(
        PopulationImportConfigurationError,
        match="MATRAIX_PERSONA_DATASET_PATH must be configured",
    ):
        load_import_settings({"DATABASE_URL": "postgresql://user:secret@db/core"})

    missing = tmp_path / "sensitive-dataset-location"
    with pytest.raises(PopulationImportConfigurationError) as raised:
        load_import_settings(
            {
                "MATRAIX_PERSONA_DATASET_PATH": str(missing),
                "DATABASE_URL": "postgresql://user:secret@db/core",
            }
        )
    assert str(missing) not in str(raised.value)
    assert "secret" not in str(raised.value)


def test_dataset_is_strictly_parsed_and_content_addressed(tmp_path: Path) -> None:
    dataset_path = _write_dataset(tmp_path)

    dataset = parse_dataset(dataset_path)

    assert dataset.slug == "sample-personas"
    assert dataset.display_name == "sample-personas"
    assert dataset.schema_version == "1.0"
    assert dataset.persona_count == 2
    assert tuple(persona.profile.persona_id for persona in dataset.personas) == (
        "alpha",
        "beta",
    )
    assert dataset.personas[0].profile.dimensions == {
        "region": "East Asia",
        "risk_tolerance": "Balanced",
    }
    assert dataset.personas[0].profile.provenance.model_dump() == {
        "hf_repo": "MatrAIx2026/MatrAIx_Persona_1M_Public_Release",
        "origin_persona_id": "wiki-alpha",
        "origin_source_row_index": 7,
        "parent_pool": "persona/datasets/matraix-persona-1m",
    }
    assert dataset.personas[1].profile.provenance.model_dump() == {
        "hf_repo": None,
        "origin_persona_id": None,
        "origin_source_row_index": None,
        "parent_pool": None,
    }
    assert dataset.personas[0].profile_json == canonical_persona_profile_json(
        dataset.personas[0].profile
    )
    canonical = canonical_persona_dataset_json(dataset)
    assert json.loads(canonical) == {
        "schema": DATASET_SCHEMA,
        "slug": "sample-personas",
        "display_name": "sample-personas",
        "schema_version": "1.0",
        "parent_pool": "persona/datasets/matraix-persona-1m",
        "source_repository": "MatrAIx2026/MatrAIx_Persona_1M_Public_Release",
        "persona_count": 2,
        "manifest_sha256": dataset.manifest_sha256,
        "personas": [
            {
                "persona_id": persona.profile.persona_id,
                "profile_sha256": persona.profile_sha256,
            }
            for persona in dataset.personas
        ],
    }
    assert dataset.dataset_sha256 == sha256(canonical.encode("utf-8")).hexdigest()
    assert parse_dataset(dataset_path).dataset_sha256 == dataset.dataset_sha256


def test_manifest_rejects_duplicate_keys(tmp_path: Path) -> None:
    dataset_path = _write_dataset(tmp_path)
    (dataset_path / "manifest.json").write_text(
        '{"kind":"first","kind":"second","count":1,"schema_version":"1.0","personas":[]}',
        encoding="utf-8",
    )

    with pytest.raises(PopulationDatasetError, match="duplicate key 'kind'"):
        parse_dataset(dataset_path)


def test_persona_yaml_rejects_duplicate_keys(tmp_path: Path) -> None:
    dataset_path = _write_dataset(tmp_path)
    (dataset_path / "persona_alpha.yaml").write_text(
        """persona_id: alpha
persona_id: replaced
version: '1.0'
source: wiki
display_name: Alpha
dimensions:
  region: East Asia
""",
        encoding="utf-8",
    )

    with pytest.raises(PopulationDatasetError, match="valid strict YAML"):
        parse_dataset(dataset_path)


def test_manifest_rejects_path_traversal(tmp_path: Path) -> None:
    dataset_path = _write_dataset(tmp_path)
    manifest_path = dataset_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["personas"][0]["path"] = "../sample-personas/persona_alpha.yaml"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(PopulationDatasetError, match="leaves the dataset boundary"):
        parse_dataset(dataset_path)


def test_manifest_and_file_inventory_must_match_exactly(tmp_path: Path) -> None:
    dataset_path = _write_dataset(tmp_path)
    (dataset_path / "persona_unlisted.yaml").write_text(
        "persona_id: unlisted\n",
        encoding="utf-8",
    )

    with pytest.raises(PopulationDatasetError, match="absent from the manifest"):
        parse_dataset(dataset_path)

    (dataset_path / "persona_unlisted.yaml").unlink()
    (dataset_path / "persona_beta.yaml").unlink()
    with pytest.raises(PopulationDatasetError, match="missing persona files"):
        parse_dataset(dataset_path)


def test_package_script_mounts_only_the_explicit_host_dataset_read_only() -> None:
    package = json.loads((REPOSITORY_DIRECTORY / "package.json").read_text(encoding="utf-8"))
    command = package["scripts"]["import:matraix-personas"]

    assert "${MATRAIX_PERSONA_DATASET_PATH:?" in command
    assert ":/matraix-personas:ro" in command
    assert "MATRAIX_PERSONA_DATASET_PATH=/matraix-personas" in command
    assert "python -m app.populations.import_matraix" in command
