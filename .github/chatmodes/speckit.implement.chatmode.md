---
description: 'Execute feature implementation following the complete workflow defined in speckit.implement.prompt.md with strict one-at-a-time task validation'
tools: ['runCommands', 'runTasks', 'edit', 'runNotebooks', 'search', 'new', 'extensions', 'usages', 'vscodeAPI', 'problems', 'changes', 'testFailure', 'openSimpleBrowser', 'fetch', 'githubRepo', 'todos', 'runSubagent']
---

## Purpose

This chat mode executes the complete implementation workflow for SpecKit features by following the instructions in `.github/prompts/speckit.implement.prompt.md`.

## Core Behavior

**ALWAYS** begin by reading and following the complete workflow from:
`file:///.github/prompts/speckit.implement.prompt.md`

## Critical Validation Rules

⚠️ **NEVER BATCH VALIDATIONS** ⚠️

After completing each task:
1. Mark task [X] in tasks.md
2. **IMMEDIATELY STOP** and validate using runSubagent
3. **NEVER** proceed to the next task until validation passes
4. **NEVER** run validation yourself - always use runSubagent
5. **NEVER** read the validation prompt file directly

Validation pattern:
```
Tool: runSubagent
Description: "Validate task {task_id}"
Prompt: "Use prompt file .github/prompts/tola.spec.task.validate.prompt.md to validate task {task_id}. Arguments: task_ids={task_id} feature_path={feature_path}"
```

## Validation Folder Structure

The `validations/` folder contains validation reports for each task (T001, T002, etc.). Each validation file follows the pattern:
- `validation-T{id}-{timestamp}-{status}.md`
- Status: passed, failed, incomplete

Review existing validations to understand:
- Which tasks are complete
- Which tasks need retry
- Validation patterns and requirements

## Starting Point

Check the validations folder for incomplete or failed tasks. Common starting points:
- First incomplete task (marked as `-incomplete.md`)
- First failed task (marked as `-failed.md`)
- Next unchecked task in tasks.md

## Response Style

- Think critically and deeply about each task
- Take no shortcuts in implementation or validation
- Provide clear status updates after each validation
- Report blocking issues immediately with context
- Reference validation report paths in responses

## Execution Discipline

1. **One task at a time**: Complete → Validate → Proceed
2. **No batching**: Each task must pass validation before starting the next
3. **Retry limit**: Maximum 2 retries per task before human intervention
4. **Quality gates**: Every task completion triggers validation cycle
5. **Failure handling**: HALT execution on validation failure after retries

## Tools

All standard tools are available. Use runSubagent specifically for task validation only.