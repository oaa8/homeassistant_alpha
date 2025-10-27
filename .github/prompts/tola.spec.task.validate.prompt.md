---
mode: agent
description: "Perform comprehensive, critical review of completed task(s) against constitution, spec alignment, and quality standards. Acts as quality gate - rejects incomplete work."
---

# Task Validation and Constitution Compliance Review

## User Input

```text
$ARGUMENTS
```

Expected format: `task_ids=T001,T002 [feature_path=specs/001-deako-hub-simulator]`

If feature_path is not provided, will use check-prerequisites.ps1 to detect it.

You **MUST** parse the user input before proceeding.

## Mission

Perform a **comprehensive, critical review** of the specified task(s) to ensure they meet all constitutional requirements, align with user outcomes, and have been completed with integrity. This is a **quality gate** - tasks that don't meet standards MUST be marked incomplete.

## Initialization

1. **Parse user input** to extract:
   - `task_ids`: Comma-separated list (e.g., T001,T002,T003) - REQUIRED
   - `feature_path`: Feature directory (e.g., specs/001-deako-hub-simulator) - OPTIONAL

2. **Resolve feature path** (if not provided):
   ```powershell
   .specify/scripts/powershell/check-prerequisites.ps1 -Json -RequireTasks -IncludeTasks
   ```
   Parse JSON output for FEATURE_DIR and use as feature_path.
   For single quotes in args like "I'm Groot", use escape syntax: e.g 'I'\''m Groot' (or double-quote if possible: "I'm Groot").

3. **Load required artifacts**:
   - Constitution: `.specify/memory/constitution.md` (for principles)
   - Tasks file: `{feature_path}/tasks.md` (for task definitions)
   - Spec file: `{feature_path}/spec.md` (for requirements and user stories)
   - Plan file: `{feature_path}/plan.md` (for architecture context, if exists)

4. **Capture original prompt**:
   - Store the full $ARGUMENTS input for inclusion in validation report

## Validation Framework

### 1. Deep Task Analysis

For each task in the provided task_ids:

**a) Understand Task Requirements**
- Read task description from tasks.md
- Identify all acceptance criteria and deliverables
- Determine which files should have been created/modified
- Understand the end-user outcome this task enables

**b) Verify Implementation Completeness**
- Locate all files mentioned in task description
- Read implementation code thoroughly
- Check if ALL requirements from task description are implemented
- Verify implementation does what task description claims
- Look for half-implementations, shortcuts, or "good enough" compromises

**c) Identify All Related Work**
- Find all files modified for this task (use git diffs if available)
- Check for related test files
- Look for configuration changes
- Verify documentation updates

### 2. Constitution Compliance (NON-NEGOTIABLE)

**Load constitution from `.specify/memory/constitution.md` and validate against ALL principles.**

**Dynamic Principle Validation Process**:
1. Read the constitution file
2. For each principle (I, II, III, etc.):
   - Extract the principle name and all MUST/SHOULD requirements
   - Check implementation against each requirement
   - Document violations with specific file:line references
3. Extract "Development Standards" section and validate against those too
4. Extract "Technology Constraints" and verify compliance

**Constitution Authority**: The constitution is non-negotiable. Any violation is an automatic CRITICAL issue requiring remediation.

**Most Common Failure Modes** (pay special attention):
1. **Missing End-User Validation**: "Code written" does not equal "task complete"
2. **Untracked TODOs/Placeholders**: Work left for later without tracking
3. **Swallowed Exceptions**: Broad exception handlers hiding errors
4. **Missing Documentation**: Headers, WHY comments, rationale

### 3. Spec Alignment

Read spec.md and verify:

**User Story Alignment**
- Identify which user story this task belongs to
- Verify implementation moves toward that user story's goal
- Confirm expected user outcomes from spec are achievable with this work

**Functional Requirements Coverage**
- Extract ALL requirement references from task description
  - Search for common patterns: FR-, REQ-, NFR-, R-, etc.
  - Also check spec.md for any numbering/labeling scheme used
- For each referenced requirement:
  - Verify it's actually implemented (not just mentioned)
  - Check for partial implementations claiming to be complete
- Look for requirements in spec.md that should be covered by this task but aren't mentioned

**Acceptance Criteria**
- If user story has acceptance criteria, verify they're met
- Check that implementation enables the user outcome described

### 3. Deception Detection

**Actively look for these anti-patterns** (common shortcuts/deceptions):

- **"Code written" without validation**: Claims task is done but no evidence of testing/validation
- **Fake tests**: Tests that execute code but don't validate requirements
- **Placeholder implementations**: Functions returning hardcoded values or stubs
- **"Good enough" compromises**: Partial implementations claiming to be complete
- **Swallowed exceptions**: Broad exception handlers (except:, except Exception) without justification
- **Untracked TODOs**: TODO/FIXME/HACK/PLACEHOLDER without corresponding task entries
- **Missing documentation**: No file headers, no WHY comments, no rationale
- **Untested error paths**: Exception handlers without corresponding tests
- **Copy-paste without adaptation**: Code reused without proper customization
- **Magic numbers**: Unexplained constants without named variables
- **Assumptions without documentation**: Implicit assumptions not called out
- **Scattered files**: Random files outside proper directory structure

### 4. Orphaned Work Audit

**Critical check - search thoroughly**:

1. **Find all TODOs/placeholders** in modified files:
   ```
   grep -r "TODO\|FIXME\|HACK\|PLACEHOLDER\|STUB\|XXX\|PENDING" {modified_files}
   ```

2. **For each found item**:
   - Check if it's tracked in tasks.md with proper format
   - Verify it has a corresponding task ID
   - Check location is documented (file:line or function name)
   - Verify acceptance criteria exists

3. **Check file organization**:
   - Are new files in proper directory structure?
   - Are research findings in `{feature_path}/research/`?
   - Are test scripts in `{feature_path}/tests/`?
   - Are there random files at repo root or arbitrary locations?

### 5. Task Dependencies and Context

- Does this task depend on other tasks that aren't complete?
- Does marking this complete unblock other tasks appropriately?
- Is the task in the right phase according to dependencies in tasks.md?
- Are there parallel tasks that should be reviewed together?

## Validation Execution Process

Execute systematically:

**Step 1: Load Context**
1. Read task description(s) from tasks.md
2. Read constitution principles
3. Read relevant user stories from spec.md
4. Read plan.md for technical context (if exists)

**Step 2: Locate Implementation**
1. Find all files created/modified for this task
2. Use grep to find TODOs, FIXMEs, placeholders
3. Use get_changed_files if working on git branch
4. Read implementation thoroughly

**Step 3: Constitution Check**
1. For each principle in constitution:
   - Validate against requirements
   - Document violations
2. Rate severity: CRITICAL (blocks completion), MAJOR (should fix), MINOR (nice to have)

**Step 4: End-User Validation Check**
1. Look for validation evidence in:
   - Commit messages
   - Task notes in tasks.md
   - Test output
   - Integration test scripts
   - Documentation
2. **If validation evidence is missing = AUTOMATIC FAILURE**

**Step 5: Orphaned Work Check**
1. Search modified files for: TODO, FIXME, HACK, PLACEHOLDER, STUB, XXX, PENDING
2. For each instance, verify it's tracked in tasks.md
3. Check for scattered files outside proper structure
4. **If untracked work exists = AUTOMATIC FAILURE**

**Step 6: Make Decision**
1. Assess whether task meets completion criteria
2. If ANY CRITICAL violations exist → task is INCOMPLETE
3. If end-user validation is missing/insufficient → task is INCOMPLETE
4. If orphaned work exists → task is INCOMPLETE

**Step 7: Create Validation Report**
1. Generate filename: `validation-{task_ids_joined_by_underscore}-{YYYY-MM-DD-HHMMSS}.md`
2. Build full path: `{feature_path}/validations/{filename}`
3. Write complete report using create_file tool with the format specified below
4. If create_file fails, try using run_in_terminal to write the file:
   - On Windows: `New-Item -ItemType File -Path "{path}" -Force | Out-Null; Set-Content -Path "{path}" -Value "{content}"`
   - On Unix: `cat > "{path}" << 'EOF'\n{content}\nEOF`
5. Verify file was created using file_search or list_dir
6. If file still doesn't exist, store report content in your response and warn user

**Step 8: Generate Concise Chat Response**
1. Format the concise response per guidelines (under 20 lines)
2. Include the full report file path (or note if file creation failed)
3. This response will be your final output to the calling agent

**Step 9: Update tasks.md**
1. Mark tasks as complete [X] or incomplete [ ] based on decision

## Output Requirements

### Validation Report Location

Create report at:
```
{feature_path}/validations/validation-{task_ids_joined_by_underscore}-{YYYY-MM-DD-HHMMSS}.md
```

Example: `specs/001-deako-hub-simulator/validations/validation-T001_T002_T003-2025-10-25-143022.md`

**You MUST actually create this file using create_file tool before providing your chat response.**

### Report Format

```markdown
# Task Validation Report

**Generated**: {current_datetime}
**Task ID(s)**: {task_ids}
**Validator**: GitHub Copilot (AI Agent)
**Feature Path**: {feature_path}

---

## Original Validation Request

{full_$ARGUMENTS_text}

---

## Validation Agent Response Summary

{Include the concise chat response that was provided to the calling agent - this shows what the calling agent received}

---

## Tasks Under Review

### Task {ID}: {Title}

{full_task_description_from_tasks_md}

### Task {ID}: {Title}

{full_task_description_from_tasks_md}

---

## Validation Results

### 1. Implementation Analysis

**Files Created/Modified**:
- {list_all_files}

**Implementation Summary**:
{brief_summary_of_what_was_implemented}

**Task Requirements Coverage**:
- [✓] Requirement 1: {description}
- [✗] Requirement 2: {description} - **MISSING/INCOMPLETE**

---

### 2. Constitution Compliance

**Constitution Version**: {note_last_modified_date_from_constitution}

For each principle found in constitution:

#### Principle {Number}: {Name}

- **Status**: PASS / FAIL / N/A
- **Findings**: {specific_details_with_file_line_references}
- **Violations** (if any):
  - {severity}: {description} - Location: {file:line}

{Repeat for all principles}

#### Development Standards

- **Status**: PASS / FAIL / N/A
- **Findings**: {details}

#### Technology Constraints

- **Status**: PASS / FAIL / N/A
- **Findings**: {details}

---

### 3. Spec Alignment

**User Story**: {which_story_from_spec}
**Functional Requirements Referenced**: {list_all_found_requirement_IDs}

**Requirement Coverage**:
| Requirement ID | Referenced in Task? | Implemented? | Notes |
|----------------|---------------------|--------------|-------|
| {req_id}       | Yes                 | Yes          | ✓     |
| {req_id}       | Yes                 | Partial      | Missing X |
| {req_id}       | No                  | N/A          | Should this be covered? |

**Alignment Assessment**:
- Does this move toward user outcomes? {YES/NO/PARTIAL}
- Details: {explanation}

---

### 4. Deception Detection

**Anti-patterns Found**:

{List each found anti-pattern with}:
- Pattern: {name}
- Location: {file:line}
- Why it's problematic: {explanation}
- Severity: CRITICAL / MAJOR / MINOR

---

### 5. Orphaned Work Audit

**TODOs/Placeholders Found**:
| Location | Content | Tracked in tasks.md? | Task ID |
|----------|---------|----------------------|---------|
| {file:line} | {snippet} | Yes/No | {T###} |

**File Organization Issues**:
- Scattered files: {list_any_files_outside_proper_structure}
- Missing organization: {any_research_test_files_not_in_proper_dirs}

**Status**: PASS / FAIL

---

### 6. Issues Summary

#### CRITICAL Issues (Block Completion)

{If none, say "None found"}

1. {issue_description}
   - Location: {file:line}
   - Principle violated: {which_constitution_principle}
   - Required action: {what_needs_to_be_done}

#### MAJOR Issues (Should Fix)

{If none, say "None found"}

1. {issue_description}
   - Location: {file:line}
   - Impact: {why_this_matters}
   - Recommendation: {suggested_fix}

#### MINOR Issues (Nice to Have)

{If none, say "None found"}

1. {issue_description}
   - Location: {file:line}
   - Suggestion: {improvement}

---

## DECISION

**Task Status**: ✅ COMPLETE / ❌ INCOMPLETE

**Rationale**:
{Clear explanation of decision based on findings above}

{If INCOMPLETE}:
**Required Actions Before Completion**:
1. {Specific, actionable item with file location}
2. {Specific, actionable item with file location}
3. ...

**Blocking Issues Count**: {number_of_CRITICAL_issues}

---

## Recommendations

**For This Task**:
- {Specific recommendation tied to findings}

**For Future Work**:
- {Pattern to avoid or adopt based on this review}

**Constitution Updates Needed?**:
- {If constitution seems outdated or missing coverage, note here}

---

## Validation Metadata

- **Review Duration**: {estimate_time_spent_on_review}
- **Files Reviewed**: {count}
- **Lines of Code Reviewed**: {estimate}
- **Constitution Principles Checked**: {count}
- **Requirements Validated**: {count}
- **Confidence Level**: HIGH / MEDIUM / LOW
  - Rationale: {explanation_of_confidence_level}

---

## References

- Constitution: `.specify/memory/constitution.md` (accessed {datetime})
- Tasks: `{feature_path}/tasks.md`
- Spec: `{feature_path}/spec.md`
- Plan: `{feature_path}/plan.md` (if exists)
```

## Post-Report Actions

After creating the validation report:

### Keep Chat Response Concise

Your chat response must be extremely concise to avoid consuming the calling agent's context window. All detailed findings, analysis, and explanations go in the validation report file only.

Your chat response should be under 20 lines and follow this format:

### If Task is COMPLETE (✅)

1. **Ensure task is checked** in `{feature_path}/tasks.md`:
   - Change `- [ ]` to `- [X]` for the task
   
2. **Provide concise success message** (example):
   ```
   ✅ VALIDATION PASSED
   
   Tasks: T001, T002
   Status: COMPLETE - All requirements met
   
   Summary:
   • Implementation complete with end-user validation
   • Constitution compliance: PASS (all principles)
   • Test coverage: 96%
   • No critical issues found
   
   Tasks marked complete in tasks.md
   
   Full report: specs/001-deako-hub-simulator/validations/validation-T001_T002-2025-10-25-143022.md
   ```

### If Task is INCOMPLETE (❌)

1. **UNCHECK the task** in `{feature_path}/tasks.md`:
   - Change `- [X]` to `- [ ]` for the task
   
2. **Provide concise failure message** (example):
   ```
   ❌ VALIDATION FAILED
   
   Tasks: T001, T002
   Status: INCOMPLETE - 3 critical issues
   
   Critical Issues:
   1. No end-user validation evidence (Principle III)
   2. 3 untracked TODOs in server.py (Principle VI)
   3. Swallowed exceptions in connection handler (Principle VIII)
   
   Tasks unmarked in tasks.md
   
   Full report: specs/001-deako-hub-simulator/validations/validation-T001_T002-2025-10-25-143022.md
   ```

### Output Guidelines

**DO**:
- Keep total response under 20 lines
- Use bullet points (•) for brevity
- Show only top 3 critical issues
- Include full report file path at the end
- State decision clearly (COMPLETE/INCOMPLETE)
- Note what action was taken on tasks.md

**DO NOT**:
- Include full analysis or detailed findings
- List all issues (only top 3 critical)
- Explain rationale (that's in the report)
- Include code snippets or file contents
- Provide remediation steps (that's in the report)
- Quote constitution principles (reference only)

**Remember**: The validation report contains ALL details. Your chat response is just a concise summary to inform the calling agent of the outcome without consuming their context window.

## Critical Reminders

⚠️ **Your job is to be the quality gate, not a rubber stamp**

**Be skeptical by default**:
- Assume tasks are incomplete until proven otherwise
- Don't take implementation claims at face value
- Demand evidence for validation, not just assertions
- Enforce constitution compliance strictly - it's non-negotiable
- Look actively for shortcuts and deceptions
- Protect quality - rejecting tasks prevents technical debt

⚠️ **Top Failure Modes** (these are AUTOMATIC failures):
1. **No end-user validation** - "Code written" ≠ "Task complete"
2. **Untracked TODOs** - Future work without tracking = forgotten work  
3. **Swallowed exceptions** - Broad exception handlers hiding errors

If you find any of these, the task is **INCOMPLETE** - no exceptions.

⚠️ **Constitution is law**:
- All MUST requirements are mandatory
- Violations are CRITICAL issues
- Don't reinterpret or dilute principles
- If constitution seems wrong, note it in "Constitution Updates Needed"

⚠️ **Be thorough, not fast**:
- Read implementation code carefully
- Search for patterns, don't just check obvious files
- Look in git history if available
- Cross-reference between files

---

## Execution

Now proceed with validation of task(s): **{parse from $ARGUMENTS}**

1. Parse $ARGUMENTS for task_ids and feature_path
2. Load all required artifacts
3. Execute validation framework systematically
4. Make COMPLETE/INCOMPLETE decision
5. Write the validation report (with error handling and verification)
6. Update tasks.md accordingly (mark complete or incomplete)
7. Provide concise chat response with report location

The validation report file is the primary output. If file creation fails after trying both create_file and run_in_terminal approaches, include a warning in your response.

**Be thorough. Be critical. Protect quality.**
