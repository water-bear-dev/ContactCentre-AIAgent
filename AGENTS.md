# Harness-neutral operating protocol

1. Read `ACTIVE_STATE.md` before investigating or changing this repository.
2. Treat it as durable project memory. Do not rely on a chat transcript, IDE memory, or a previous agent’s unstated assumptions.
3. After every material change, test, decision, or blocker, update `ACTIVE_STATE.md` with what happened and the exact next command/action.
4. Immediately before ending a session, make one final state update and run `python scripts/validate_active_state.py` when Python is available.
5. A resuming agent starts by reading `ACTIVE_STATE.md`, checking its listed verification, and performing its listed next action. Ask the user only when the state file identifies a real blocker.
6. Employee routines remain inside their own `ai-employees/<role>/routines/` folders. Never globally install or duplicate them.

