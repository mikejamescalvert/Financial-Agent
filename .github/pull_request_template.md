## Summary

<!-- Brief description of changes -->

## Type of Change

- [ ] New feature
- [ ] Bug fix
- [ ] Strategy/trading logic change
- [ ] Configuration change
- [ ] CI/CD change
- [ ] Documentation
- [ ] Refactor (no functional change)

## Trading Impact

<!-- If this changes trading behavior, describe the impact -->

- [ ] This PR changes trading logic or strategy
- [ ] This PR changes position sizing or risk parameters
- [ ] This PR changes broker integration
- [ ] This PR has NO trading impact

## Risk Assessment

<!-- For trading-related changes -->

- **Backtested:** Yes / No / N/A
- **Paper-traded:** Yes / No / N/A
- **Risk level:** Low / Medium / High

## Testing

- [ ] Unit tests pass (`pytest`)
- [ ] Lint passes (`ruff check`)
- [ ] Type check passes (`mypy`)
- [ ] Tested with paper trading account

## Checklist

- [ ] No API keys or secrets in code
- [ ] Configuration uses environment variables
- [ ] Changes are documented in code comments where non-obvious
- [ ] Dry-run mode still works correctly
