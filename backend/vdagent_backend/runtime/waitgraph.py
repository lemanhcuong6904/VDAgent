"""Per-user wait-for graph over agents (the acyclic wait graph invariant).

Edge `a → b` exists while a running invocation of agent `a` has an accepted, unresolved call to
`b`. Parallel calls from one step to the same target are separate acceptances, so edges are
counted; an edge disappears when its last acceptance is resolved. A call is rejected when its
target already reaches the caller, so the graph never has a cycle.
"""

from __future__ import annotations

from collections import Counter


class WaitGraph:
    def __init__(self) -> None:
        self._out: dict[str, Counter[str]] = {}

    def add(self, src: str, dst: str) -> None:
        self._out.setdefault(src, Counter())[dst] += 1

    def remove(self, src: str, dst: str) -> None:
        targets = self._out.get(src)
        if targets is None or dst not in targets:
            return
        targets[dst] -= 1
        if targets[dst] <= 0:
            del targets[dst]
            if not targets:
                del self._out[src]

    def has_path(self, src: str, dst: str) -> bool:
        """True if `dst` is reachable from `src` following edges (a node reaches itself)."""
        seen = {src}
        todo = [src]
        while todo:
            node = todo.pop()
            if node == dst:
                return True
            for nxt in self._out.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return False

    def __bool__(self) -> bool:
        return bool(self._out)
