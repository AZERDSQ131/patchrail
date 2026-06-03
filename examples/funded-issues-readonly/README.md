# Funded Issues Read-Only Demo

This fixture shows the future funded issue scout boundary:

```bash
patchrail funded-issues list --source examples/funded-issues-readonly/issues.json
patchrail funded-issues explain example/project#42 --source examples/funded-issues-readonly/issues.json
```

The command reads local JSON only. It does not claim rewards, post comments,
open pull requests, contact maintainers, or rank work by funding alone.
