# START_HERE.md
# Paste this into Claude Code to begin Sprint 0

---

## Prompt to Copy and Paste

```
Read these three files before doing anything else:
1. CLAUDE.md — project architecture and conventions
2. Custom_Tool_Implementation.docx — full implementation spec
3. tasks/sprint-0.md — exactly what to build and acceptance criteria

Implement Sprint 0 exactly as specified in tasks/sprint-0.md.
Use Custom_Tool_Implementation.docx as the source of truth for all rules,
templates, and specifications. Use CLAUDE.md for project conventions.

When complete:
- Run: pytest tests/ -v (all must pass)
- Run: ruff check tool/ (zero errors)
- Commit all changes with message: "Sprint 0: L1 + L2 + L4 minimum viable tool"
- Push and open PR against main

Do not ask for clarification. Everything is in the files.
Start now.
```

---

## After Sprint 0 PR Merges

Open a new Claude Code session on a new branch.
Paste this:

```
Read CLAUDE.md, Custom_Tool_Implementation.docx, and tasks/sprint-1.md.
Sprint 0 is merged. Implement Sprint 1 (SSIS Parser) as specified in tasks/sprint-1.md.
Run pytest. Commit. Open PR.
```

---

## Sprint Sequence

| Sprint | Branch | Prompt anchor |
|--------|--------|---------------|
| 0 | feature/sprint-0-mvt | tasks/sprint-0.md |
| 1 | feature/sprint-1-ssis-parser | tasks/sprint-1.md |
| 2 | feature/sprint-2-adf-parser | tasks/sprint-2.md |
| 3 | feature/sprint-3-l3-expressions | tasks/sprint-3.md |
| 4 | feature/sprint-4-l5-tests | tasks/sprint-4.md |
| 5 | feature/sprint-5-generators | tasks/sprint-5.md |
| 6 | feature/sprint-6-cicd | tasks/sprint-6.md |

Each sprint: new branch → new Claude Code session → "Read CLAUDE.md + Custom_Tool_Implementation.docx + tasks/sprint-N.md and implement"
