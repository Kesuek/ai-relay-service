"""Tests for the central status registry (T-078, phase 18)."""

from relay_server.core.status import (
    NODE_STATUSES,
    STAGE_STATUSES,
    TASK_STATUSES,
    USER_STATUSES,
    StatusCategory,
    can_transition,
    get_category,
    get_status,
    is_available,
    is_busy,
    is_offline,
    is_pending,
    is_terminal,
    node_can_claim,
    node_can_transition,
    node_claim_statuses,
    node_is_claimable,
    node_statuses_in_category,
    stage_can_transition,
    status_color,
    task_can_transition,
    user_can_transition,
)

# ── Registry completeness ───────────────────────────────────────────


def test_status_registry_has_all_node_entries():
    expected = {"offline", "pending", "approved", "online", "idle", "busy", "maintenance"}
    assert set(NODE_STATUSES) == expected


def test_status_registry_has_all_task_entries():
    expected = {
        "pending", "accepted", "running", "awaiting_subtasks", "needs_input",
        "completed", "failed", "timed_out", "cancelled",
    }
    assert set(TASK_STATUSES) == expected


def test_status_registry_has_all_stage_entries():
    expected = {"pending", "claimed", "accepted", "orphaned", "completed", "failed", "timed_out", "cancelled"}
    assert set(STAGE_STATUSES) == expected


def test_status_registry_has_all_user_entries():
    assert set(USER_STATUSES) == {"active", "inactive"}


# ── Categories ──────────────────────────────────────────────────────


def test_status_categories_node():
    assert get_category("offline") == StatusCategory.OFFLINE
    assert get_category("pending") == StatusCategory.PENDING
    assert get_category("approved") == StatusCategory.AVAILABLE
    assert get_category("online") == StatusCategory.AVAILABLE
    assert get_category("idle") == StatusCategory.AVAILABLE
    assert get_category("busy") == StatusCategory.BUSY
    assert get_category("maintenance") == StatusCategory.BUSY


def test_status_categories_task():
    assert get_category("running") == StatusCategory.BUSY
    assert get_category("completed") == StatusCategory.TERMINAL
    assert get_category("failed") == StatusCategory.TERMINAL
    assert get_category("timed_out") == StatusCategory.TERMINAL
    assert get_category("cancelled") == StatusCategory.TERMINAL
    assert get_category("awaiting_subtasks") == StatusCategory.PENDING


def test_status_categories_stage():
    assert get_category("claimed") == StatusCategory.BUSY
    assert get_category("completed") == StatusCategory.TERMINAL


def test_status_categories_user():
    assert get_category("active") == StatusCategory.AVAILABLE
    assert get_category("inactive") == StatusCategory.OFFLINE


def test_get_category_unknown_status():
    assert get_category("nonsense") is None
    assert get_status("nonsense") is None


# ── Category predicates ────────────────────────────────────────────


def test_is_terminal():
    assert is_terminal("completed")
    assert is_terminal("failed")
    assert is_terminal("timed_out")
    assert is_terminal("cancelled")
    assert not is_terminal("pending")
    assert not is_terminal("running")
    assert not is_terminal("online")


def test_is_busy():
    assert is_busy("busy")
    assert is_busy("running")
    assert is_busy("claimed")
    assert is_busy("maintenance")
    assert not is_busy("online")
    assert not is_busy("pending")


def test_is_available():
    assert is_available("online")
    assert is_available("approved")
    assert is_available("idle")
    assert is_available("active")
    assert not is_available("busy")
    assert not is_available("offline")


def test_is_pending():
    assert is_pending("pending")
    assert is_pending("accepted")
    assert not is_pending("online")


def test_is_offline():
    assert is_offline("offline")
    assert is_offline("inactive")
    assert not is_offline("online")


# ── Transitions ────────────────────────────────────────────────────


def test_transition_valid():
    # Node transitions (entity-specific because ``pending`` is shared).
    assert node_can_transition("pending", "approved")
    assert node_can_transition("approved", "online")
    assert node_can_transition("online", "busy")
    assert node_can_transition("busy", "idle")
    # Task transitions.
    assert task_can_transition("running", "completed")
    assert task_can_transition("pending", "running")
    # Stage transitions.
    assert stage_can_transition("claimed", "completed")
    assert stage_can_transition("pending", "claimed")
    # User transitions.
    assert user_can_transition("active", "inactive")
    # Generic with explicit entity_type.
    assert can_transition("online", "busy", entity_type="node")


def test_transition_invalid():
    # Terminal statuses allow no further transition.
    assert not task_can_transition("completed", "running")
    # Node offline cannot jump to online (must go via pending/approved).
    assert not node_can_transition("offline", "online")
    # Cross-entity status names must not be confused: a node in
    # ``online`` cannot go to ``completed`` (that's a task/stage status).
    assert not node_can_transition("online", "completed")
    assert not can_transition("nonsense", "online")
    # Generic lookup without entity_type is ambiguous for shared names
    # (pending) — it should NOT return the node's transition.
    assert not can_transition("pending", "approved")


# ── Node helpers ───────────────────────────────────────────────────


def test_node_can_claim():
    # AVAILABLE nodes can claim.
    assert node_can_claim("approved")
    assert node_can_claim("online")
    assert node_can_claim("idle")
    # BUSY / OFFLINE / PENDING cannot claim.
    assert not node_can_claim("busy")
    assert not node_can_claim("maintenance")
    assert not node_can_claim("offline")
    assert not node_can_claim("pending")


def test_node_is_claimable():
    assert node_is_claimable("approved")
    assert node_is_claimable("online")
    assert node_is_claimable("idle")
    assert node_is_claimable("pending")
    assert not node_is_claimable("busy")
    assert not node_is_claimable("maintenance")
    assert not node_is_claimable("offline")


def test_node_claim_statuses_contains_available_only():
    claimable = set(node_claim_statuses())
    assert {"approved", "online", "idle"} <= claimable
    assert "busy" not in claimable
    assert "pending" not in claimable
    assert "offline" not in claimable
    # Must NOT include non-node statuses (e.g. the user status "active").
    assert "active" not in claimable


def test_node_statuses_in_category_excludes_user_statuses():
    avail = node_statuses_in_category(StatusCategory.AVAILABLE)
    assert "active" not in avail  # user status, not a node status
    assert "online" in avail


# ── Dashboard colour mapping ────────────────────────────────────────


def test_status_color_overrides_for_terminal():
    assert status_color("completed") == "ok"
    assert status_color("failed") == "bad"
    assert status_color("timed_out") == "bad"
    assert status_color("cancelled") == "bad"


def test_status_color_by_category():
    assert status_color("online") == "ok"
    assert status_color("approved") == "ok"
    assert status_color("idle") == "ok"
    assert status_color("busy") == "warn"
    assert status_color("running") == "warn"
    assert status_color("claimed") == "warn"
    assert status_color("pending") == "info"
    assert status_color("accepted") == "info"
    assert status_color("offline") == "bad"
    assert status_color("inactive") == "bad"


def test_status_color_unknown():
    assert status_color("nonsense") == "muted"