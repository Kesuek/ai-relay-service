"""Tests for nodes.common.capability_loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from nodes.common import capability_loader as cl
from nodes.common.capability_loader import (
    ActiveProfileCache,
    CapabilityValidationError,
    current_profile_name,
    diff_profiles,
    list_profiles,
    load_active_profile,
    profile_path,
    publish_profile,
    validate_profile,
)

# ---------------------------------------------------------------------------
# Fixtures: point all module paths at a temp dir
# ---------------------------------------------------------------------------

@pytest.fixture()
def isolated_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    base = tmp_path / "relay"
    profiles_dir = base / "capabilities.d"
    active = base / "capabilities.active.yaml"
    active_name = base / "capabilities.active.profile"

    monkeypatch.setattr(cl, "BASE_DIR", base)
    monkeypatch.setattr(cl, "PROFILES_DIR", profiles_dir)
    monkeypatch.setattr(cl, "ACTIVE_PATH", active)
    monkeypatch.setattr(cl, "ACTIVE_PROFILE_NAME_PATH", active_name)
    # The module-level cache was created at import time; repoint it.
    monkeypatch.setattr(cl._active_cache, "path", active)
    profiles_dir.mkdir(parents=True, exist_ok=True)
    return base


VALID_PROFILE = textwrap.dedent("""
    capabilities:
      - name: chat.ai
        version: "1.0.0"
        auto_publish: true
        claimable: true
        handler: /opt/relay/handlers/chat-ai.sh
        max_parallel: 2
        timeout: 300

      - name: storage.archive.native
        version: "1.0.0"
        auto_publish: true
        claimable: true
        handler: /opt/relay/handlers/archive.sh
        max_parallel: 1
        timeout: 600

      - name: mflux
        version: "1.0.0"
        auto_publish: true
        claimable: false
""").strip()


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# validate_profile / load_profile
# ---------------------------------------------------------------------------

def test_load_valid_profile_returns_normalized_dicts(isolated_paths: Path):
    p = _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    caps = validate_profile(p)
    assert len(caps) == 3

    chat = caps[0]
    assert chat["name"] == "chat.ai"
    assert chat["version"] == "1.0.0"
    assert chat["auto_publish"] is True
    assert chat["claimable"] is True
    assert chat["handler"] == "/opt/relay/handlers/chat-ai.sh"
    assert chat["max_parallel"] == 2
    assert chat["timeout"] == 300

    mflux = caps[2]
    assert mflux["name"] == "mflux"
    assert mflux["claimable"] is False
    # No handler for non-claimable cap → normalized to empty string.
    assert mflux["handler"] == ""
    # Defaults applied.
    assert mflux["max_parallel"] == 1
    assert mflux["timeout"] == 300


def test_load_profile_missing_name_raises():
    bad = {"capabilities": [{"version": "1.0.0"}]}
    with pytest.raises(CapabilityValidationError, match="name.*required"):
        validate_profile(bad)


def test_load_profile_claimable_without_handler_raises():
    bad = {"capabilities": [{"name": "chat.ai", "claimable": True}]}
    with pytest.raises(CapabilityValidationError, match="'handler' is required"):
        validate_profile(bad)


def test_load_profile_duplicate_names_raises():
    bad = {"capabilities": [
        {"name": "dup"},
        {"name": "dup", "claimable": False},
    ]}
    with pytest.raises(CapabilityValidationError, match="duplicate capability name"):
        validate_profile(bad)


def test_load_profile_missing_capabilities_key_raises(isolated_paths: Path):
    p = _write(isolated_paths / "capabilities.d" / "x.yaml", "foo: bar\n")
    with pytest.raises(CapabilityValidationError, match="'capabilities' key is required"):
        validate_profile(p)


def test_load_profile_capabilities_not_a_list_raises():
    with pytest.raises(CapabilityValidationError, match="'capabilities' must be a list"):
        validate_profile({"capabilities": "not-a-list"})


def test_load_profile_max_parallel_not_positive_raises():
    bad = {"capabilities": [{"name": "x", "max_parallel": 0}]}
    with pytest.raises(
        CapabilityValidationError, match="max_parallel.*>= 1"
    ):
        validate_profile(bad)


def test_load_profile_timeout_not_integer_raises():
    bad = {"capabilities": [{"name": "x", "timeout": "abc"}]}
    with pytest.raises(CapabilityValidationError, match="timeout.*expected int"):
        validate_profile(bad)


def test_load_profile_auto_publish_not_bool_raises():
    bad = {"capabilities": [{"name": "x", "auto_publish": "yes"}]}
    with pytest.raises(CapabilityValidationError, match="auto_publish.*expected bool"):
        validate_profile(bad)


def test_load_profile_yaml_syntax_error_includes_file(isolated_paths: Path):
    p = _write(isolated_paths / "capabilities.d" / "bad.yaml", "capabilities: [unclosed\n")
    with pytest.raises(CapabilityValidationError, match="YAML syntax error"):
        validate_profile(p)


def test_load_profile_missing_file_raises(isolated_paths: Path):
    with pytest.raises(CapabilityValidationError, match="profile file not found"):
        validate_profile(isolated_paths / "capabilities.d" / "missing.yaml")


def test_validate_profile_accepts_dict_input():
    caps = validate_profile({"capabilities": [{"name": "ok"}]})
    assert caps[0]["name"] == "ok"


# ---------------------------------------------------------------------------
# JSON Schema validation
# ---------------------------------------------------------------------------


def test_schema_rejects_unknown_keys():
    """Schema catches unknown keys in capability entries."""
    with pytest.raises(CapabilityValidationError, match="unknown keys"):
        validate_profile({"capabilities": [{"name": "x", "unknown_field": "bad"}]})


def test_schema_rejects_wrong_type_for_version():
    """Schema catches type errors in optional fields."""
    with pytest.raises(CapabilityValidationError, match="version.*str"):
        validate_profile({"capabilities": [{"name": "x", "version": 123}]})


def test_schema_rejects_negative_max_parallel():
    """Schema catches range violations."""
    with pytest.raises(CapabilityValidationError, match="max_parallel.*>= 1"):
        validate_profile({"capabilities": [{"name": "x", "max_parallel": 0}]})


def test_schema_rejects_negative_timeout():
    with pytest.raises(CapabilityValidationError, match="timeout.*>= 1"):
        validate_profile({"capabilities": [{"name": "x", "timeout": -1}]})


def test_schema_rejects_capabilities_not_a_list():
    with pytest.raises(CapabilityValidationError, match="capabilities.*must be a list"):
        validate_profile({"capabilities": "not-a-list"})


def test_schema_rejects_entry_not_a_mapping():
    with pytest.raises(CapabilityValidationError, match="must be a mapping"):
        validate_profile({"capabilities": ["string-entry"]})


def test_schema_rejects_missing_name():
    with pytest.raises(CapabilityValidationError, match="name.*required"):
        validate_profile({"capabilities": [{"version": "1.0.0"}]})


def test_schema_rejects_empty_name():
    with pytest.raises(CapabilityValidationError, match="name.*required"):
        validate_profile({"capabilities": [{"name": ""}]})


def test_schema_passes_valid_profile():
    """A valid profile passes schema validation without errors."""
    caps = validate_profile({
        "capabilities": [
            {"name": "chat.ai", "version": "1.0.0", "auto_publish": True,
             "claimable": True, "handler": "/bin/true", "max_parallel": 2, "timeout": 300},
        ]
    })
    assert len(caps) == 1
    assert caps[0]["name"] == "chat.ai"


# ---------------------------------------------------------------------------
# Env-var overrides
# ---------------------------------------------------------------------------

def test_env_override_handler(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RELAY_CAPABILITY_CHAT_AI_HANDLER", "/custom/handler.sh")
    caps = validate_profile(
        {"capabilities": [{"name": "chat.ai", "claimable": True, "handler": "/orig.sh"}]}
    )
    assert caps[0]["handler"] == "/custom/handler.sh"


def test_env_override_max_parallel(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RELAY_CAPABILITY_CHAT_AI_MAX_PARALLEL", "7")
    caps = validate_profile({"capabilities": [{"name": "chat.ai"}]})
    assert caps[0]["max_parallel"] == 7


def test_env_override_max_parallel_invalid_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RELAY_CAPABILITY_CHAT_AI_MAX_PARALLEL", "not-a-number")
    with pytest.raises(CapabilityValidationError, match="is not an integer"):
        validate_profile({"capabilities": [{"name": "chat.ai"}]})


# ---------------------------------------------------------------------------
# list_profiles / profile_path / current_profile_name
# ---------------------------------------------------------------------------

def test_list_profiles_returns_sorted_yaml(isolated_paths: Path):
    _write(isolated_paths / "capabilities.d" / "beta.yaml", VALID_PROFILE)
    _write(isolated_paths / "capabilities.d" / "alpha.yaml", VALID_PROFILE)
    _write(isolated_paths / "capabilities.d" / "ignore.txt", "nope")
    names = [p.name for p in list_profiles()]
    assert names == ["alpha.yaml", "beta.yaml"]


def test_list_profiles_empty_when_dir_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(cl, "PROFILES_DIR", tmp_path / "nonexistent")
    assert list_profiles() == []


def test_profile_path_handles_bare_name_and_extension(isolated_paths: Path):
    assert profile_path("default").name == "default.yaml"
    assert profile_path("default.yaml").name == "default.yaml"
    assert profile_path("default.yml").name == "default.yml"


def test_current_profile_name_none_when_unset(isolated_paths: Path):
    assert current_profile_name() is None


# ---------------------------------------------------------------------------
# publish_profile
# ---------------------------------------------------------------------------

def test_publish_profile_creates_active_file_and_name(isolated_paths: Path):
    p = _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    active = publish_profile("default")
    assert active.exists()
    assert active.read_text() == p.read_text()
    assert current_profile_name() == "default"
    # The active file must parse as a valid profile.
    assert len(validate_profile(active)) == 3


def test_publish_profile_invalid_does_not_touch_active(isolated_paths: Path):
    _write(isolated_paths / "capabilities.d" / "bad.yaml", "capabilities: bad\n")
    # Pre-seed an active file so we can prove it was not overwritten.
    (isolated_paths / "capabilities.active.yaml").write_text("pre-existing\n")
    with pytest.raises(CapabilityValidationError):
        publish_profile("bad")
    assert (isolated_paths / "capabilities.active.yaml").read_text() == "pre-existing\n"
    assert current_profile_name() is None


def test_publish_profile_missing_profile_raises(isolated_paths: Path):
    with pytest.raises(CapabilityValidationError, match="profile not found"):
        publish_profile("does-not-exist")


# ---------------------------------------------------------------------------
# diff_profiles
# ---------------------------------------------------------------------------

def test_diff_profiles_added_removed_changed():
    old = [
        {"name": "a", "version": "1.0.0", "auto_publish": True, "claimable": False,
         "handler": "", "max_parallel": 1, "timeout": 300},
        {"name": "b", "version": "1.0.0", "auto_publish": True, "claimable": False,
         "handler": "", "max_parallel": 1, "timeout": 300},
    ]
    new = [
        {"name": "a", "version": "2.0.0", "auto_publish": True, "claimable": False,
         "handler": "", "max_parallel": 1, "timeout": 300},
        {"name": "c", "version": "1.0.0", "auto_publish": True, "claimable": False,
         "handler": "", "max_parallel": 1, "timeout": 300},
    ]
    diff = diff_profiles(old, new)
    assert [c["name"] for c in diff["added"]] == ["c"]
    assert diff["removed"] == ["b"]
    assert [c["name"] for c in diff["changed"]] == ["a"]
    assert diff["changed"][0]["old"]["version"] == "1.0.0"
    assert diff["changed"][0]["new"]["version"] == "2.0.0"


def test_diff_profiles_empty_when_identical():
    caps = [{"name": "a", "version": "1.0.0"}]
    diff = diff_profiles(caps, caps)
    assert diff == {"added": [], "removed": [], "changed": []}


def test_diff_profiles_handles_none_inputs():
    diff = diff_profiles(None, None)
    assert diff == {"added": [], "removed": [], "changed": []}


# ---------------------------------------------------------------------------
# ActiveProfileCache / load_active_profile
# ---------------------------------------------------------------------------

def test_active_profile_cache_reads_active(isolated_paths: Path):
    _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    publish_profile("default")
    caps = load_active_profile()
    assert len(caps) == 3


def test_active_profile_cache_empty_when_no_active_file(isolated_paths: Path):
    assert load_active_profile() == []


def test_active_profile_cache_mtime_cache(isolated_paths: Path, monkeypatch: pytest.MonkeyPatch):
    _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    publish_profile("default")

    cache = ActiveProfileCache()
    # Force a sentinel in the cache: break path resolution by pointing at a
    # file that does not exist, then call get() — should return [] and not
    # blow up even though our internal cached_caps is None.
    monkeypatch.setattr(cache, "path", isolated_paths / "nonexistent.yaml")
    assert cache.get() == []


def test_active_profile_cache_invalidate_forces_reread(isolated_paths: Path):
    _write(isolated_paths / "capabilities.d" / "default.yaml", VALID_PROFILE)
    publish_profile("default")

    cache = ActiveProfileCache()
    first = cache.get()
    assert len(first) == 3
    cache.invalidate()
    second = cache.get()
    assert second == first
