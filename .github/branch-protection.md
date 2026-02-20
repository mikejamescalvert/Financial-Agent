# Branch Protection Setup Guide

Apply these settings in **Settings > Branches > Branch protection rules** after merging to `main`.

## Rule: `main` branch

| Setting | Value |
|---------|-------|
| **Require a pull request before merging** | Yes |
| Required approving reviews | 1 |
| Dismiss stale pull request approvals when new commits are pushed | Yes |
| Require review from Code Owners | Yes |
| **Require status checks to pass before merging** | Yes |
| Required checks | `Lint & Type Check`, `Tests`, `Security Scan` |
| Require branches to be up to date before merging | Yes |
| **Require signed commits** | Recommended |
| **Require linear history** | Yes (enforces squash/rebase) |
| **Do not allow bypassing the above settings** | Yes |
| **Restrict who can push to matching branches** | Only repo owner |
| **Allow force pushes** | No |
| **Allow deletions** | No |

## Rule: `release/*` branches

| Setting | Value |
|---------|-------|
| Require a pull request before merging | Yes |
| Required approving reviews | 1 |
| Require status checks to pass | Yes |
| Allow force pushes | No |
| Allow deletions | No |

## Recommended Branch Strategy

```
main          ← production, protected, only via PR
├── develop   ← integration branch for feature work
│   ├── feature/*   ← new features
│   ├── fix/*       ← bug fixes
│   └── refactor/*  ← code improvements
└── release/* ← release candidates
```

### Naming Conventions
- `feature/add-options-strategy` - New functionality
- `fix/stop-loss-calculation` - Bug fixes
- `refactor/broker-client` - Code improvements
- `release/v0.2.0` - Release candidates

### Merge Strategy
- Feature branches → `develop`: Squash merge
- `develop` → `main`: Merge commit (preserves history)
- Hotfixes → `main`: Squash merge (then backport to develop)
