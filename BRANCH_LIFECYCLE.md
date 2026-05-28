# Branch Lifecycle Policy

This policy controls branch growth, PR flow, and cleanup for this repository.

## 1) Freeze Branch Growth Immediately

Apply these repository settings in GitHub:

1. Branch protection on `main`:
   - Require a pull request before merging
   - Require status checks to pass before merging
   - Require approvals and dismiss stale approvals when new commits are pushed
   - Block direct pushes by non-admin contributors
2. Branch protection on `develop` (if used):
   - Same rules as `main`
3. Repository setting:
   - Enable **Automatically delete head branches**

### Required checks

Use these workflow gates as required checks:

- `CI`
- `CI — preflight check & lint`
- `Branch policy`
- Security workflows as needed for your environment

## 2) Branch Naming Rules

Allowed branch prefixes:

- `feature/*`
- `fix/*`
- `copilot/*`
- `chore/*`
- `docs/*`
- `refactor/*`
- `test/*`
- `release/*`
- `hotfix/*`

Branches outside this convention fail branch policy checks.

## 3) Branch TTL Rules

- Soft TTL: 30 days (review expected)
- Hard TTL: 90 days (must be merged, rebased, or closed)
- PR automation marks stale PRs after inactivity and closes after grace period

## 4) Deletion Policy

Protected namespaces (never auto-delete):

- `main`
- `develop`
- `release/*`
- `hotfix/*`

Cleanup buckets:

1. `merged`
   - Branch has a merged PR
   - Safe for deletion first
2. `stale-unmerged`
   - No open PR
   - Last commit older than stale threshold (default 90 days)
   - Candidate for staged cleanup after exception review
3. `active`
   - Open PR or recent activity

## 5) Exception and Archive Handling

Before deleting stale-unmerged branches:

1. Review open work references (issue links, incidents, release notes)
2. Label/document approved exceptions in weekly digest issue
3. Keep exceptions in protected namespaces or rehome into tracked branches

## 6) Required PR States Before Merge

Before merge:

1. PR template fields are complete (owner, purpose, risk, rollback)
2. Required checks pass
3. Required approvals obtained
4. No unresolved blocking review comments

## 7) Governance Automation

Implemented workflows:

- `.github/workflows/stale-prs.yml`
  - Marks and closes stale PRs
- `.github/workflows/branch-pr-hygiene.yml`
  - Weekly branch inventory and digest
  - Optional prune modes (`none`, `merged`, `merged_and_stale`)
- `.github/workflows/branch-policy.yml`
  - Enforces branch naming and max age on PRs
- `.github/workflows/governance-settings-audit.yml`
  - Audits branch protection and auto-delete settings

## 8) Rollout Plan

### Week 1

- Enable protection + auto-delete settings
- Run hygiene workflow in report mode (`prune_mode=none`)

### Week 2

- Run hygiene workflow with `prune_mode=merged`
- Review digest output and confirm drop in merged backlog

### Week 3

- Run hygiene workflow with `prune_mode=merged_and_stale`
- Use exception review before stale-unmerged deletion

### Week 4+

- Keep weekly hygiene and stale automation enabled
- Track trend in digest issue to maintain steady-state branch count
