---
sidebar_position: 9
title: SOLID architecture boundaries
---

# SOLID architecture boundaries

Hermes is being migrated incrementally toward explicit application ports and
infrastructure adapters. The goal is to improve maintainability without a risky
rewrite of the agent loop or breaking provider plugins.

## Dependency direction

The intended dependency flow is:

```text
Presentation / CLI / Gateway
            ↓
Application orchestration
            ↓
Ports and domain policies
            ↑
Infrastructure adapters
```

Application code may depend on protocols and value objects. Concrete HTTP,
WebSocket, database, filesystem, and provider SDK implementations must remain
in adapter modules and be wired at composition roots.

## Enforced provider boundary

`providers.base.ProviderProfile` is a declarative provider value object. It may
describe endpoints, authentication type, capabilities, headers, and request
policy, but it must not perform HTTP access directly.

Live model discovery uses:

- `ModelCatalogRequest`: immutable request value.
- `ModelCatalogClient`: application port.
- `UrllibModelCatalogClient`: default infrastructure adapter.
- `ProviderProfile.catalog_client`: optional injection seam for tests and
  alternate composition roots.

The public `ProviderProfile.fetch_models()` method remains for compatibility,
but it delegates all I/O to the port. Architecture tests prevent network
imports from returning to `providers/base.py`.

## Refactor sequence

The remaining core migration should proceed in small, behavior-preserving
steps:

1. **Provider runtime** — move credential refresh, client construction, headers,
   API-mode selection, and provider-specific recovery behind a
   `ProviderRuntimeStrategy` port.
2. **Session persistence** — extract SQLite and JSON transcript writes behind a
   `SessionRepository` port.
3. **Agent events** — replace the large callback collection with a focused
   `AgentEventSink` interface and adapters for CLI, gateway, and tests.
4. **Tool execution** — keep orchestration dependent on `ToolExecutor`, not the
   global registry or concrete terminal/browser modules.
5. **Resource lifecycle** — move client, browser, process, and sandbox cleanup to
   a dedicated lifecycle service.
6. **AIAgent facade** — retain `AIAgent` as a compatibility facade while the
   application service becomes the real orchestration unit.

Each phase must include contract tests and architecture tests before the next
responsibility is extracted.

## Rules for new code

- Do not add new provider-name branches to `AIAgent` when the behavior belongs
  to a provider strategy or profile.
- Do not open network connections from profile/value-object modules.
- Do not import gateway, CLI presentation, or web UI code into the agent domain.
- Prefer constructor injection at composition roots.
- Keep optional capability interfaces narrow rather than expanding one large
  base class.
- Preserve existing public methods during migration and implement them as thin
  compatibility delegates.
