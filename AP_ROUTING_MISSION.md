# AP Routing Mission

Before changing AP routing behavior, read [`docs/V117_LEARNED_AUTONOMY_CHARTER.md`](docs/V117_LEARNED_AUTONOMY_CHARTER.md).

The durable goal is AI-driven routing that learns Gamer Accounting's human-confirmed decisions and reviewer corrections. The AI is the primary router. Learned performance earns autonomy. Deterministic logic is only a fail-closed safety envelope and must never choose a replacement route.

Immutable promotion gate:

- 0 wrong automatic routes
- 100% automatic-route accuracy
- >=90% representative held-out automatic-route coverage
- default minimum labeled examples = 20

Frozen runtime-proven zero-wrong fallback: `6c455f1a027361115eba3ea9ecde989009bda76e`.

Do not lower the gate, self-train from unreviewed AI predictions, or recreate Square9 as vendor-specific Python templates. Continue repo-safe learned-autonomy sprint work without pausing for approval; stop only for a real execution or authorization boundary.