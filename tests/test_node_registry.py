"""Tests for the ADR-001 node ID registry."""

from relay_server.core.node_registry import (
    NODE_ID_ALPHABET,
    NODE_ID_LENGTH,
    NodeRegistry,
    generate_node_id,
)


def test_generate_node_id_length_and_alphabet():
    node_id = generate_node_id()
    assert len(node_id) == NODE_ID_LENGTH
    assert all(ch in NODE_ID_ALPHABET for ch in node_id)


def test_node_registry_generate_unique_avoids_collision():
    registry = NodeRegistry()
    taken = {"ABCDEFGH"}
    assigned = registry.generate_unique_node_id(exists_callback=lambda c: c in taken)
    assert len(assigned) == NODE_ID_LENGTH
    assert assigned not in taken


def test_is_valid_node_id_accepts_valid_id():
    registry = NodeRegistry()
    assert registry.is_valid_node_id("ABCDEFGH") is True


def test_is_valid_node_id_rejects_invalid_characters():
    registry = NodeRegistry()
    assert registry.is_valid_node_id("ABCDEFG1") is False  # '1' not in alphabet


def test_is_valid_node_id_rejects_wrong_length():
    registry = NodeRegistry()
    assert registry.is_valid_node_id("ABCDEFG") is False
    assert registry.is_valid_node_id("ABCDEFGHI") is False
