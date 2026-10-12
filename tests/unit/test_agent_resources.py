import json

import pytest
import yaml

from tickwork_cli.app.agent_resources.repository.agent_resource_repository import (
    AgentResourceRepository,
)
from tickwork_cli.app.agent_resources.service.agent_resource_service import AgentResourceService
from tickwork_cli.common.application_errors import TickworkError
from tickwork_cli.common.operation_error import OperationError


@pytest.fixture
def store(tmp_path):
    return AgentResourceService(
        AgentResourceRepository("tickwork-cli", "tickwork", tmp_path / "state")
    )


def apply(store, **targets):
    preview = store.sync(**targets)
    return store.sync(True, preview["expected_plan"], **targets)


def test_install_preserves_user_bytes_and_retry_does_not_write(store, tmp_path):
    skills = tmp_path / "space path" / "skills"
    hint = tmp_path / "AGENTS.md"
    original = "# 用户规则\r\n保留正文\r\n".encode()
    hint.write_bytes(original)
    preview = store.sync(skills_dir=skills, hint_file=hint)
    assert not store.state_root.exists()
    assert not skills.exists()
    assert hint.read_bytes() == original
    result = store.sync(True, preview["expected_plan"], skills, hint)
    assert result["write_performed"]
    assert hint.read_bytes().startswith(original)
    reference = skills / "tickwork-task-management/references/platform-notes.md"
    assert reference.exists()
    before = {path: path.stat().st_mtime_ns for path in [hint, reference, store.registry_path]}
    result = apply(store)
    assert not result["operations"]
    assert not result["write_performed"]
    assert before == {path: path.stat().st_mtime_ns for path in before}


def test_preview_cannot_overwrite_concurrent_changes(store, tmp_path):
    hint = tmp_path / "hint.md"
    preview = store.sync(hint_file=hint)
    hint.write_text("User edit", encoding="utf-8")
    with pytest.raises(OperationError, match="Preview changed"):
        store.sync(True, preview["expected_plan"], hint_file=hint)
    assert hint.read_text(encoding="utf-8") == "User edit"
    assert not store.state_root.exists()


@pytest.mark.parametrize("markers", ["start", "end", "end-start", "start-start-end"])
def test_invalid_hint_markers_are_rejected_without_writing(store, tmp_path, markers):
    hint = tmp_path / "hint.md"
    content = "\n".join(
        f"<!-- TICKWORK:{'BEGIN' if marker == 'start' else 'END'} -->"
        for marker in markers.split("-")
    )
    hint.write_text(content, encoding="utf-8")
    with pytest.raises(OperationError, match="markers"):
        store.sync(hint_file=hint)
    assert hint.read_text(encoding="utf-8") == content
    assert not store.state_root.exists()


def test_registered_skill_and_hint_follow_package_without_historical_hashes(store, tmp_path):
    skills, hint = tmp_path / "skills", tmp_path / "hint.md"
    apply(store, skills_dir=skills, hint_file=hint)
    skill = skills / "tickwork-task-management/SKILL.md"
    original_skill, original_hint = skill.read_bytes(), hint.read_bytes()
    skill.write_bytes(original_skill + b"local change")
    hint.write_bytes(
        b"before\r\n" + original_hint.replace(b"tickwork", b"Local change") + b"after\r\n"
    )
    preview = store.sync()
    assert preview["conflicts"] == []
    assert skill.read_bytes() != original_skill
    apply(store)
    assert skill.read_bytes() == original_skill
    assert hint.read_bytes() == b"before\r\n" + original_hint + b"after\r\n"
    registry = yaml.safe_load(store.registry_path.read_bytes())
    assert all("sha256" not in item for item in registry["agent_resource_files"])
    assert store.sync()["operations"] == []


@pytest.mark.parametrize("target_kind", ["skill", "hint"])
def test_registered_resource_changes_after_preview_still_require_replanning(
    store, tmp_path, target_kind
):
    skills, hint = tmp_path / "skills", tmp_path / "hint.md"
    apply(store, skills_dir=skills, hint_file=hint)
    target = skills / "tickwork-task-management/SKILL.md" if target_kind == "skill" else hint
    target.write_bytes(
        target.read_bytes().replace(b"tickwork", b"Local output")
        if target_kind == "hint"
        else target.read_bytes() + b"first local change"
    )
    preview = store.sync()
    assert preview["conflicts"] == []
    before_registry = store.registry_path.read_bytes()
    changed = target.read_bytes() + b"another change after preview"
    target.write_bytes(changed)
    with pytest.raises(OperationError, match="Preview changed"):
        store.sync(True, preview["expected_plan"])
    assert target.read_bytes() == changed
    assert store.registry_path.read_bytes() == before_registry


def test_deleted_packaged_files_are_cleaned_without_deleting_user_files(
    store, tmp_path, monkeypatch
):
    skills = tmp_path / "skills"
    apply(store, skills_dir=skills)
    reference = skills / "tickwork-task-management/references/platform-notes.md"
    user_file = skills / "tickwork-task-management/user.md"
    user_file.write_text("user", encoding="utf-8")
    assets = store.assets()
    del assets["tickwork-task-management/references/platform-notes.md"]
    monkeypatch.setattr(store, "assets", lambda: assets)
    result = apply(store)
    assert any(op["action"] == "delete" for op in result["operations"])
    assert not reference.exists()
    assert user_file.read_text(encoding="utf-8") == "user"
    assert not store.sync()["operations"]


def test_modified_deleted_managed_resource_is_cleaned(store, tmp_path, monkeypatch):
    skills = tmp_path / "skills"
    apply(store, skills_dir=skills)
    reference = skills / "tickwork-task-management/references/platform-notes.md"
    reference.write_text("custom", encoding="utf-8")
    assets = store.assets()
    del assets["tickwork-task-management/references/platform-notes.md"]
    monkeypatch.setattr(store, "assets", lambda: assets)
    assert store.sync()["conflicts"] == []
    apply(store)
    assert not reference.exists()
    assert store.sync()["operations"] == []


def test_hint_upgrade_keeps_text_outside_block(store, tmp_path, monkeypatch):
    hint = tmp_path / "hint.md"
    apply(store, hint_file=hint)
    hint.write_bytes(b"before\r\n" + hint.read_bytes() + b"after\r\n")
    monkeypatch.setattr(store, "hint", lambda: b"New version hint")
    apply(store)
    assert hint.read_bytes().startswith(b"before\r\n")
    assert hint.read_bytes().endswith(b"after\r\n")
    assert b"New version hint" in hint.read_bytes()


def test_unregistered_file_is_not_overwritten(store, tmp_path):
    skills = tmp_path / "skills"
    skill = skills / "tickwork-task-management/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("someone else's skill", encoding="utf-8")
    preview = store.sync(skills_dir=skills)
    assert preview["conflicts"][0]["code"] == "unmanaged-target"
    with pytest.raises(OperationError, match="Unregistered targets"):
        store.sync(True, preview["expected_plan"], skills_dir=skills)
    assert skill.read_text(encoding="utf-8") == "someone else's skill"
    assert not store.state_root.exists()


def test_symlink_target_is_rejected(store, tmp_path):
    link, real = tmp_path / "link", tmp_path / "real"
    real.mkdir()
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symlinks")
    with pytest.raises(OperationError, match="Symbolic"):
        store.sync(skills_dir=link)


def test_optional_resources_can_be_removed_without_breaking_core(store, monkeypatch):
    monkeypatch.setattr(store, "assets", lambda: {})
    monkeypatch.setattr(store, "hint", lambda: b"")
    assert store.check()["files"] == 0
    assert store.list_skills()["skills"] == []
    assert store.sync()["operations"] == []


def test_registry_cannot_be_used_as_hint_target(store):
    with pytest.raises(OperationError, match="internal CLI state"):
        store.sync(hint_file=store.registry_path)
    assert not store.state_root.exists()


def test_corrupt_registry_is_not_silently_reset(store):
    store.state_root.mkdir()
    store.registry_path.write_bytes(b"")
    with pytest.raises(OperationError, match="registry is invalid"):
        store.sync()
    assert store.registry_path.read_bytes() == b""


def test_shared_target_lock_blocks_other_product(store, tmp_path, monkeypatch):
    hint = tmp_path / "shared.md"
    preview = store.sync(hint_file=hint)
    other = AgentResourceService(
        AgentResourceRepository("tickwork-cli", "other-cli", tmp_path / "other-state")
    )
    monkeypatch.setattr(other, "hint", lambda: b"Other hint")
    other_preview = other.sync(hint_file=hint)
    with store.repository.lock([hint]):
        with pytest.raises(TickworkError, match="lock"):
            other.sync(True, other_preview["expected_plan"], hint_file=hint)
    assert not hint.exists()
    store.sync(True, preview["expected_plan"], hint_file=hint)


def test_binary_attachments_are_installed_without_text_decoding(store, tmp_path, monkeypatch):
    assets = store.assets()
    assets["tickwork-task-management/references/image.bin"] = b"\xff\x00\x80"
    monkeypatch.setattr(store, "assets", lambda: assets)
    apply(store, skills_dir=tmp_path / "skills")
    assert (
        tmp_path / "skills/tickwork-task-management/references/image.bin"
    ).read_bytes() == b"\xff\x00\x80"
    with pytest.raises(OperationError, match="binary"):
        store.show("tickwork-task-management", "references/image.bin")


def test_existing_local_registration_and_owned_files_keep_targets(store, tmp_path):
    skills, hint = tmp_path / "skills", tmp_path / "AGENTS.md"
    skill = skills / "tickwork-task-management/SKILL.md"
    removed = skill.parent / "removed.md"
    marker = skill.parent / ".tickwork-owned.json"
    skill.parent.mkdir(parents=True)
    skill.write_bytes(b"Local edit of registered resource")
    removed.write_bytes(b"old package attachment")
    user = skill.parent / "user.md"
    user.write_bytes(b"Keep user file")
    marker.write_text(json.dumps({str(skill): "historical-hash", str(removed): "old-hash"}))
    hint.write_bytes(b"before\r\n<!-- TICKWORK:BEGIN -->\nold\n<!-- TICKWORK:END -->\r\nafter")
    store.state_root.mkdir()
    store.registry_path.write_text(
        yaml.safe_dump({"agent_resources": [{"agents_file": str(hint), "skills_dir": str(skills)}]})
    )
    preview = store.sync()
    assert not preview["conflicts"]
    assert marker.exists() and removed.exists()
    apply(store)
    assert skill.read_bytes() == store.assets()["tickwork-task-management/SKILL.md"]
    assert not removed.exists() and not marker.exists()
    assert user.read_bytes() == b"Keep user file"
    assert hint.read_bytes().startswith(b"before\r\n") and hint.read_bytes().endswith(b"\r\nafter")
    registry = yaml.safe_load(store.registry_path.read_bytes())
    assert {tuple(item.items())[0] for item in registry["agent_resources"]} == {
        ("skills_dir", str(skills)),
        ("agents_file", str(hint)),
    }
    assert not store.sync()["operations"]


def test_owned_record_cannot_escape_explicit_registered_root(store, tmp_path):
    skills = tmp_path / "skills"
    apply(store, skills_dir=skills)
    foreign = tmp_path / "foreign.txt"
    foreign.write_bytes(b"protected")
    marker = skills / "tickwork-task-management/.tickwork-owned.json"
    marker.write_text(json.dumps({str(foreign): "hash"}))
    with pytest.raises(OperationError, match="outside registered locations"):
        store.sync()
    assert foreign.read_bytes() == b"protected"
