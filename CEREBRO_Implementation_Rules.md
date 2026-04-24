# CEREBRO Implementation Rules – Enforced Execution Protocol

**Version:** 2.0  
**Purpose:** Ensure consistent, correct, and scalable implementation without architectural drift.

---

## 1. Pre-Execution Checklist (MANDATORY)

Before writing code, you must:

- Identify **current sprint + exact tasks**
- List **files to modify**
- Confirm **runtime target**:
  - Desktop (Python UI) **OR**
  - Web (Frontend + API split)
- Identify **state impact**:
  - What state changes?
  - What components depend on it?

Then state:

> “This change updates [state fields] and affects [components].”

No code before this.

---

## 2. State Is the Single Source of Truth

All UI must derive from state.

### Rules:
- No direct mutation of UI components with external data
- No page-to-page data passing
- No hidden internal state that conflicts with global state

### Required pattern:
```python
state → update → UI reacts
Forbidden pattern:
python
event → manually update multiple UI components
If violated, stop and refactor.

3. Controlled Execution (No Callback Sprawl)
All cross-component logic must go through:

a coordinator, OR

a state transition

Example:
Bad:

python
_on_scan_complete():
    update_results()
    update_review()
    switch_tab()
Good:

python
dispatch(SCAN_COMPLETED)
4. Sprint Discipline (Flexible but Controlled)
You must follow sprint scope, BUT:

Allowed:
Reordering tasks if:

a dependency is discovered, OR

implementation is blocked

Required:
Explain why reordering is needed

Get confirmation before proceeding

5. Handling Unclear Requirements
If ambiguity exists:

Stop

Quote the exact unclear section

Provide 1–2 interpretations

Wait for decision

No guessing.

6. Issue Tracking (Non-Optional)
Maintain:
CEREBRO_IMPLEMENTATION_ISSUES.md

Log:

blockers

platform issues

architectural conflicts

Small fixes can be auto-resolved but still logged.

7. Rendering Discipline
One render per state change

No redundant redraws

No UI updates from background threads

8. Async & Background Work Rules
No UI updates outside main thread

All async results must:

resolve → update state → trigger render

Never attach data directly to UI from workers.

9. Communication Protocol
Before coding:

list planned changes

map to sprint tasks

After coding:

list changes

explain state impact

No vague summaries.

10. Rule Deviation
If deviating:

explicitly state deviation

explain risk

get confirmation

11. Core Principle
If state is unclear, stop.
If flow is unclear, stop.
If UI updates manually in multiple places, stop.

End of rules.