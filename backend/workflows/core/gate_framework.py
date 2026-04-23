"""
Gate Framework — Lane C Step 2.75 (LANE_A_SIGNED_SCOPE.md §5 + §5.1).

Primitives only. Archetype modules self-register their own gates via import-time
side effects (see workflows/core/gates.py for the Step 2.75 registrations).

Contracts (verbatim from signed §5.1):

    @dataclass(frozen=True)
    class GateResult:
        gate_id: str
        gate_version: str            # sha256(evaluate source)[:12] default; manual semver override
        passed: bool
        severity: Literal["block", "warn", "info"]
        detail: str
        evidence: dict
        resolution_hint: Optional[str]

    class Gate(Protocol):
        id: str
        version: str
        archetype: Optional[str]     # None = global
        applies_to_states: Set[str]
        severity: str
        async def evaluate(self, ctx) -> GateResult: ...

Evaluation order: globals first (archetype is None), then archetype-scoped.
"""
from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Protocol, Set, runtime_checkable


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    gate_version: str
    passed: bool
    severity: Literal["block", "warn", "info"]
    detail: str
    evidence: Dict[str, Any]
    resolution_hint: Optional[str]


@dataclass
class GateContext:
    db: Any
    doc: Dict[str, Any]


@runtime_checkable
class Gate(Protocol):
    id: str
    version: str
    archetype: Optional[str]
    applies_to_states: Set[str]
    severity: str

    async def evaluate(self, ctx: GateContext) -> GateResult: ...


def hash_evaluate_source(fn) -> str:
    """Default gate_version: sha256 of the evaluate() function source, first 12 chars.

    Per signed §5.1: "Default version: content-hash of the evaluate() source.
    Override with manual semver when a threshold change is significant enough
    to warrant a human-readable bump."
    """
    try:
        src = inspect.getsource(fn)
    except (OSError, TypeError):
        src = getattr(fn, "__qualname__", str(fn))
    return hashlib.sha256(src.encode("utf-8")).hexdigest()[:12]


class GateRegistry:
    """Single-module singleton holding registered gates.

    Global gates (archetype=None) are evaluated before archetype-scoped gates.
    Registration is idempotent by id; attempting to register a second gate with
    the same id raises ValueError (helps catch accidental double-imports).
    """

    def __init__(self) -> None:
        self._gates: Dict[str, Gate] = {}

    def register(self, gate: Gate) -> None:
        if gate.id in self._gates:
            raise ValueError(
                f"Gate with id {gate.id!r} already registered. "
                f"Call unregister() first if you intend to replace it."
            )
        self._gates[gate.id] = gate

    def unregister(self, gate_id: str) -> None:
        self._gates.pop(gate_id, None)

    def list_gates(self, archetype: Optional[str] = "__ALL__") -> List[Gate]:
        """Return gates, globals first, then archetype-scoped.

        archetype="__ALL__" (default sentinel) → every gate.
        archetype=None      → only global gates.
        archetype="foo"     → globals + gates scoped to "foo".
        """
        all_gates = list(self._gates.values())
        if archetype == "__ALL__":
            return sorted(all_gates, key=lambda g: (g.archetype is not None, g.id))
        filtered = [
            g for g in all_gates
            if g.archetype is None or g.archetype == archetype
        ]
        return sorted(filtered, key=lambda g: (g.archetype is not None, g.id))

    async def evaluate_all(self, ctx: GateContext) -> List[GateResult]:
        """Run every registered gate against the context. Globals first."""
        results: List[GateResult] = []
        for gate in self.list_gates():
            try:
                result = await gate.evaluate(ctx)
            except Exception as err:
                # Never let a single gate explosion poison the whole pass.
                results.append(GateResult(
                    gate_id=gate.id,
                    gate_version=getattr(gate, "version", "unknown"),
                    passed=True,   # treat failure to evaluate as non-blocking
                    severity="info",
                    detail=f"Gate {gate.id} raised: {err!r}",
                    evidence={"error": str(err)},
                    resolution_hint=None,
                ))
            else:
                results.append(result)
        return results

    def clear(self) -> None:
        """Testing convenience — drop all registrations."""
        self._gates.clear()


# Module-level singleton — the single registry the app uses.
registry = GateRegistry()
