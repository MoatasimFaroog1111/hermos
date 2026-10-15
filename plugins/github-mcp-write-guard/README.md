# GitHub MCP mutation guard

Read operations use an explicit allowlist. Unknown tools require human approval;
repository/file deletion and repository creation/forking remain blocked.

Before each MCP dispatch, the guard derives MCP tool namespaces from the active profile
using the same normalization, effective configuration, and environment expansion
as Hermes (including managed scope). It recognizes GitHub URLs, the official
GitHub MCP command/image, and GitHub-named connections. For private Enterprise
or proxy endpoints with another name, declare the MCP server keys explicitly:

```yaml
plugins:
  entries:
    github-mcp-write-guard:
      servers: [internal-git]
```

New aliases are picked up on the next call. Previously recognized identities
remain protected until the gateway restarts, covering cached live tools. Invalid guard
configuration blocks MCP calls until corrected; credentials are never included
in the configuration error. Other integrations remain outside this guard.

Install profile-specific versions under the active Hermes profile's
`plugins/github-mcp-write-guard/` directory; user plugins override bundled ones.
The host's existing approval choices and allowlist behavior remain in effect.
