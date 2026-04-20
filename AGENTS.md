# AGENTS.md

Purpose: central registry for automated agents that interact with this repository. Use this file to document agent names, responsibilities, triggers, and required permissions/secrets.

## How-to register an agent
- Add an entry to this file with: name, owner, description, triggers, secrets/permissions needed, contact.
- If the agent needs to run GitHub Actions, provide steps to create a workflow and required secrets in Settings > Secrets.

---

## Existing agents

- Playwright Canary
  - owner: repo maintainers
  - description: daily and on-push browser canary tests that build the frontend, start the Flask backend, run Playwright E2E tests, and upload HTML report.
  - triggers: push to main, pull_request, scheduled daily 03:00 UTC
  - required secrets: none (tests use local test data). If external API keys are needed, add as GitHub secrets and reference them in workflows.
  - workflow: .github/workflows/playwright-canary.yml

- CI (ruff + pytest)
  - owner: repo maintainers
  - description: run ruff lint and pytest on PRs and pushes to main
  - triggers: pull_request, push to main
  - required secrets: none
  - workflow: .github/workflows/ci.yml


## Template for new agents
- name: <agent-name>
  owner: <team/person>
  description: <short description>
  triggers: <push|pull_request|schedule|webhook|manual>
  required secrets/permissions: <GH secrets, repo permissions>
  contact: <email / Slack / repo owner>
  notes: <optional operational notes>


## Notes for agents developers
- Avoid committing secrets. Use GitHub secrets store for API keys.
- For agents that call Gemini/Google GenAI, prefer hermetic testing or recorded fixtures in tests to avoid billing and flakiness.
- See CLAUDE.md for maintainer operational notes and packaging steps.
