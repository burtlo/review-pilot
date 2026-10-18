---
name: create-bug
description: >-
  Create a DOTNETIOT Jira Bug from write-bug ticket text in chat via
  New-DotnetIotBug.ps1 and acli; link to a related issue. Use when the user
  runs /create-bug or asks to file the written bug in Jira.
disable-model-invocation: true
---

# Create bug (Jira)

Create a **DOTNETIOT** Bug in Jira from a **write-bug** ticket already in this chat (or pasted in the same message). Do **not** delegate to subagents.

## User hint

Text **after** `/create-bug` on the same message (e.g. `and link it to DOTNETIOT2103`). Parse a related issue key from that hint when present.

If no related key is found, ask once: “Which DOTNETIOT ticket should this relate to (e.g. DOTNETIOT-2103)?”

## Label: NeedsTechCertify

Jira Cloud labels are **plain strings** (no separate label ID). Confirm the name exists on the instance:

```powershell
acli jira workitem search --jql 'project = DOTNETIOT AND labels = NeedsTechCertify' --limit 1 --fields "key,labels" --json
```

Always pass label **`NeedsTechCertify`** exactly (case-sensitive). Example reference issue: `DOTNETIOT-2576`.

## Source ticket in chat

Use the most recent write-bug output in the thread (`## Title` through **Team Notes**). If missing, ask the user to run `/write-bug` first or paste the ticket.

| write-bug section | Jira field |
|-------------------|------------|
| `## Title` | `summary` (title line only, no `## Title` heading) |
| `## Issue` through **Team Notes** | `description` (keep markdown headings and lists) |

Do not repeat the title in the description unless it already appears in **Issue**.

## Normalize related issue key

From user hint, extract `DOTNETIOT` + digits and normalize to `DOTNETIOT-<number>`:

- `DOTNETIOT2103` → `DOTNETIOT-2103`
- `dotnetiot-2103` → `DOTNETIOT-2103`

## Run (you must execute)

1. Build a JSON file (temp path is fine), e.g.:

```json
{
  "projectKey": "DOTNETIOT",
  "type": "Bug",
  "summary": "<from Title>",
  "description": "<markdown body sections>",
  "relatedIssueKey": "<normalized key>",
  "linkType": "1 Relates",
  "labels": ["NeedsTechCertify"]
}
```

2. Run the script (no `-DryRun` unless the user asks for a dry run):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\.cursor\scripts\jira\New-DotnetIotBug.ps1" -InputFile "<path-to-json>" -Confirm:$false
```

Script path: `~/.cursor/scripts/jira/New-DotnetIotBug.ps1`

3. On success, reply briefly with:
   - New issue key (script stdout)
   - Related issue and link type `1 Relates`
   - Optional: `acli jira workitem view <KEY> --web` if the user wants the link opened

4. On failure, show the acli error. If create fails for required custom fields, inspect a sibling bug (`acli jira workitem view DOTNETIOT-2576 --fields "*all" --json`), add needed values under `additionalAttributes` in the JSON, and retry once.

## Description formatting

- **Only** use `New-DotnetIotBug.ps1` for create + description. Do **not** follow up with `acli jira workitem edit --description-file` and a `.md` file — Jira stores plain text, so `##` and `**` show up literally and content can stack on the default bug template instead of replacing it.
- The script converts markdown to Jira ADF (headings, lists, bold), writes UTF-8 JSON without BOM, and **replaces** the full Description field after create.

## Do not

- Create duplicate bugs if the user only asked whether creation is possible
- Skip `NeedsTechCertify`
- Use a skill or subagent instead of running the script
- Change the write-bug ticket wording when copying into Jira (minor formatting for markdown is OK)
- Patch description with `edit --description-file` markdown
