"""The per-user wait-for graph: counted edges and reachability."""

from __future__ import annotations

from vdagent_backend.runtime.waitgraph import WaitGraph


def test_an_edge_lasts_until_its_last_acceptance_is_removed() -> None:
    graph = WaitGraph()
    graph.add("orchestrator", "data")
    graph.add("orchestrator", "data")
    graph.remove("orchestrator", "data")
    assert graph.has_path("orchestrator", "data")
    graph.remove("orchestrator", "data")
    assert not graph.has_path("orchestrator", "data")
    assert not graph
    graph.remove("orchestrator", "data")  # removing a missing edge is a no-op
    assert not graph


def test_has_path_follows_multi_hop_edges_in_their_direction_only() -> None:
    graph = WaitGraph()
    for src, dst in [("a", "b"), ("b", "c"), ("c", "d"), ("x", "c")]:
        graph.add(src, dst)
    assert graph.has_path("a", "d")
    assert graph.has_path("x", "d")
    assert graph.has_path("b", "b")  # a node reaches itself
    assert not graph.has_path("d", "a")
    assert not graph.has_path("a", "x")
    graph.remove("b", "c")
    assert not graph.has_path("a", "d")
    assert graph.has_path("x", "d")
