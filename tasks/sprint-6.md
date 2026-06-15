# tasks/sprint-6.md
# Sprint 6: CI/CD GitHub Actions Integration

**Duration:** Week 6 (1 week)  
**Prerequisite:** Sprint 5 merged to main  
**Branch:** `feature/sprint-6-cicd`

---

## Read First

1. `CLAUDE.md`
2. `Custom_Tool_Implementation.docx` §7.1 (Automated Intake Workflow) and §7.2 (CLI)

---

## What to Build

Two GitHub Actions workflow files:
- `.github/workflows/test.yml` — CI: lint + pytest on every PR (Sprint 0 created a skeleton; Sprint 6 makes it production-ready)
- `.github/workflows/intake.yml` — Auto-trigger Stage 1+2 on commit to source-packages/

---

## Workflow 1: test.yml (Production CI)

Complete replacement of the Sprint 0 skeleton. Must:

```yaml
name: CI — Lint and Test

on:
  push:
    branches: ["**"]
  pull_request:
    branches: ["main", "develop"]

env:
  PYTHON_VERSION: "3.11"

jobs:
  lint:
    name: Lint
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - name: Install dependencies
        run: pip install ruff
      - name: Ruff lint check
        run: ruff check tool/ tests/
      - name: Ruff format check
        run: ruff format --check tool/ tests/

  test:
    name: Unit Tests
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      - name: Run tests
        run: pytest tests/ -v --tb=short --no-header
        env:
          # L3 and L5 use mocked API in tests — no real key needed in CI
          ANTHROPIC_API_KEY: "test-mock-key"
      - name: Upload test results
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: test-results
          path: "*.xml"

  security-scan:
    name: Security Scan
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
      - name: Install bandit
        run: pip install bandit
      - name: Run bandit security scan
        run: bandit -r tool/ -ll  # report medium+ severity only
```

---

## Workflow 2: intake.yml (Automated Source Intake)

This is the main intake workflow. When a developer commits a `.dtsx` or ADF `.json` file to `source-packages/`, this workflow auto-runs Stage 1, creates a PR for review, then after approval runs Stage 2.

### 8 Steps (from §7.1)

```yaml
name: ETL Migration Intake

on:
  push:
    branches: ["main", "develop"]
    paths:
      - "source-packages/**"

permissions:
  contents: write
  pull-requests: write

jobs:
  intake:
    runs-on: ubuntu-latest
    steps:
      # Step 1: Trigger — detect changed files
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Get changed source files
        id: changed-files
        run: |
          CHANGED=$(git diff --name-only HEAD~1 HEAD -- 'source-packages/**' | head -1)
          echo "source_file=$CHANGED" >> $GITHUB_OUTPUT
          echo "Changed file: $CHANGED"

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install tool
        run: pip install -e .

      # Step 2: Pre-screen
      - name: Pre-screen eligibility
        id: prescreen
        run: |
          python -m tool.cli pre-screen "${{ steps.changed-files.outputs.source_file }}" \
            --output-csv /tmp/prescreen_result.csv
          ELIGIBLE=$(python -c "
          import csv
          with open('/tmp/prescreen_result.csv') as f:
              rows = list(csv.DictReader(f))
          print(rows[0]['eligible'] if rows else 'FALSE')
          ")
          echo "eligible=$ELIGIBLE" >> $GITHUB_OUTPUT
        continue-on-error: true

      - name: Skip if not eligible
        if: steps.prescreen.outputs.eligible == 'FALSE'
        run: |
          echo "File not eligible for custom tool — manual GHCP path required"
          exit 0

      # Step 3: Stage 1
      - name: Run Stage 1 — Generate Requirements Doc
        if: steps.prescreen.outputs.eligible == 'TRUE'
        id: stage1
        run: |
          SOURCE="${{ steps.changed-files.outputs.source_file }}"
          JOB_NAME=$(python -c "
          from pathlib import Path
          print(Path('$SOURCE').stem)
          ")
          echo "job_name=$JOB_NAME" >> $GITHUB_OUTPUT
          python -m tool.cli stage1 "$SOURCE" --output requirements-docs/
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      # Step 4: Open Stage 1 PR
      - name: Create branch and open Stage 1 PR
        if: steps.stage1.outcome == 'success'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          JOB="${{ steps.stage1.outputs.job_name }}"
          BRANCH="intake/stage1-${JOB}-${{ github.run_number }}"
          git config user.email "etl-tool@migration.internal"
          git config user.name "ETL Migration Tool"
          git checkout -b "$BRANCH"
          git add requirements-docs/
          git commit -m "Stage 1: Requirements doc for ${JOB}"
          git push origin "$BRANCH"
          gh pr create \
            --title "Stage 1 Review: ${JOB}" \
            --body "$(cat << 'EOF'
          ## Requirements Document for Review
          
          Generated by custom migration tool Stage 1.
          
          **Before approving:**
          - [ ] All transformation descriptions are accurate
          - [ ] All [MANUAL INPUT REQUIRED] items have been filled
          - [ ] Business SME has confirmed business logic is correct
          - [ ] TQ-1 sign-off form completed in JIRA
          
          **To trigger Stage 2:** Apply the label `stage1-approved` to this PR.
          EOF
          )" \
            --label "needs-review,stage1" \
            --base main \
            --head "$BRANCH"

      # Step 5: Wait for TQ-1 approval
      # (Handled by the separate on: pull_request event below)

  # Step 6+: Stage 2 triggers on stage1-approved label
  stage2-on-approval:
    runs-on: ubuntu-latest
    if: |
      github.event_name == 'pull_request' &&
      github.event.action == 'labeled' &&
      github.event.label.name == 'stage1-approved'
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.ref }}
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install tool
        run: pip install -e .

      # Step 6: Run Stage 2
      - name: Run Stage 2 — Generate Code
        id: stage2
        run: |
          # Find the requirements doc in this PR's branch
          REQS_DOC=$(find requirements-docs/ -name "REQUIREMENTS.md" | head -1)
          JOB_NAME=$(python -c "
          import yaml, re
          with open('$REQS_DOC') as f:
              content = f.read()
          match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL)
          if match:
              meta = yaml.safe_load(match.group(1))
              print(meta.get('job_name', 'unknown'))
          ")
          echo "job_name=$JOB_NAME" >> $GITHUB_OUTPUT
          python -m tool.cli stage2 "$REQS_DOC" --output generated/
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}

      # Step 7: Open Stage 2 PR
      - name: Create Stage 2 PR
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          JOB="${{ steps.stage2.outputs.job_name }}"
          BRANCH="intake/stage2-${JOB}-${{ github.run_number }}"
          git config user.email "etl-tool@migration.internal"
          git config user.name "ETL Migration Tool"
          git checkout -b "$BRANCH"
          git add generated/ docs/
          git commit -m "Stage 2: Generated artifacts for ${JOB}"
          git push origin "$BRANCH"
          gh pr create \
            --title "Stage 2 Review: ${JOB}" \
            --body "$(cat << 'EOF'
          ## Generated Artefacts for Review
          
          Stage 2 code generation complete.
          
          **Before merging:**
          - [ ] GHCP PR review annotations resolved
          - [ ] Unit tests in tests/test_${JOB}.py — fill expected values, remove @xfail
          - [ ] Lint and tests passing in CI
          - [ ] ETL Lead TQ-7 sign-off completed
          EOF
          )" \
            --label "needs-review,stage2,requires-ghcp-review" \
            --base main \
            --head "$BRANCH"

      # Step 8: CI checks run automatically on the new PR (handled by test.yml)
```

---

## Secrets Required

Add to GitHub repo Settings → Secrets → Actions:
- `ANTHROPIC_API_KEY` — Claude API key for L3 and L5 (Stage 2)
- `GITHUB_TOKEN` — automatically provided by GitHub Actions (no setup needed)

---

## Tests for CI Workflow (tests/test_intake_workflow.py)

Test the Python logic that the workflow calls, not the YAML itself:

1. `test_prescreen_writes_csv` — pre-screen on test fixture → CSV with correct headers
2. `test_stage1_writes_requirements_doc` — stage1 on sample_ssis.dtsx → REQUIREMENTS.md created
3. `test_stage2_requires_stage2_permitted_true` — stage2 on doc with `stage2_permitted: false` → raises ValueError
4. `test_full_pipeline_skip_gate` — pipeline with --skip-approval-gate runs end-to-end on sample fixture

---

## Acceptance Criteria — Sprint 6 Complete When ALL Pass

- [ ] Commit a `.dtsx` file to `source-packages/ssis/` on a branch → Stage 1 PR opens automatically
- [ ] Apply `stage1-approved` label to Stage 1 PR → Stage 2 PR opens automatically
- [ ] Introduce deliberate `ruff` lint error → CI fails on `test.yml`
- [ ] Fix lint error → CI passes
- [ ] Introduce a deliberate test failure → CI fails
- [ ] Fix test → CI passes
- [ ] `ANTHROPIC_API_KEY` secret configured in repo → Stage 2 runs L3 (or mock if key is test key)
- [ ] `pytest tests/ -v` → 100% pass
- [ ] `ruff check tool/ tests/` → zero errors
- [ ] PR opened against main
