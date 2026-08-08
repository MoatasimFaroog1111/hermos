# SOLID Agent Platform Architecture v1

Status: Accepted baseline for incremental implementation
Branch: `agent/solid-agent-platform-v1`

## 1. Objective

Evolve the existing Hermes architecture into a cleaner, explicitly layered agent platform built around six architectural capabilities:

- orchestration
- specialized agents
- tool gateway
- sandbox execution
- permissions
- memory

The implementation must preserve Hermes' existing strengths instead of replacing them. The work is therefore an incremental refactor of the current system, not a second agent framework living beside it.

The design also adopts the strongest general patterns from the reviewed agent systems: iterative agent loops, explicit planning, specialized execution roles, verified tool use, source-grounded research, sandboxed execution, approval boundaries, provider abstraction, context control, and result verification.

## 2. Non-negotiable invariants

The following existing Hermes invariants must survive every phase:

1. The system prompt remains byte-stable for the lifetime of a conversation except for explicit supported operations such as compression or model changes.
2. Message role alternation remains valid; orchestration must not inject synthetic user messages into the middle of the agent loop.
3. The platform-agnostic core remains shared by CLI, gateway, ACP, batch, cron, API server, and Python-library entry points.
4. New capabilities are implemented at the narrowest possible footprint. Existing tools, skills, plugins, and provider abstractions are extended before new core model tools are considered.
5. Every tool invocation remains observable and interruptible.
6. Security boundaries are preserved or strengthened. No refactor may silently bypass existing approval, credential, environment, or sandbox controls.
7. Existing provider and tool contracts remain backward compatible during migration.
8. Refactoring is performed in small independently testable increments.

## 3. Current-to-target architecture map

Hermes already contains most of the required capabilities. The target architecture therefore formalizes responsibilities and dependency boundaries around existing implementations.

| Target capability | Existing implementation | v1 direction |
| --- | --- | --- |
| Orchestrator | `AIAgent` in `run_agent.py` | Extract orchestration contracts and narrow responsibilities incrementally; do not create a competing agent loop. |
| Planner | `tools/todo_tool.py`, model reasoning, delegation workflows | Introduce a planner contract and plan state model only where a concrete consumer exists; preserve optional planning. |
| Specialized agents | `tools/delegate_tool.py`, subagents, skills, provider/runtime modes | Model specialization as policies/profiles over the same core agent runtime, not separate duplicated runtimes. |
| Tool gateway | `tools/registry.py` + `model_tools.py` | Introduce a stable execution facade around discovery, authorization, dispatch, and result normalization. |
| Sandbox | `tools/environments/`, `tools/code_execution_tool.py`, terminal backends | Define a sandbox capability contract implemented by existing environment backends. |
| Permissions | `tools/approval.py`, CLI callbacks, gateway authorization/pairing | Separate policy decisions from UI approval transport and tool execution. |
| Memory | `agent/memory_manager.py`, `agent/memory_provider.py`, memory plugins, session storage | Keep provider ABC; formalize working/project/user-memory boundaries and retrieval context. |
| Context management | prompt builder, compressor, prompt caching | Preserve stable/volatile prompt tiers and expose context selection through narrow interfaces. |
| LLM providers | runtime provider resolution + adapters | Keep existing provider resolution; agents depend on a provider-facing port rather than vendor-specific clients. |
| Verification | existing tests/build checks, tool results, agent loop retries | Add explicit verifier hooks without forcing every task through a heavyweight pipeline. |
| Observability | callbacks, logging, trajectories | Normalize execution events and correlation IDs without adding mandatory external telemetry. |

## 4. Target logical architecture

```text
Entry Points
CLI / Gateway / ACP / Cron / API / Batch
                    |
                    v
          +-------------------+
          |   Orchestrator    |
          +---------+---------+
                    |
        +-----------+-----------+
        |           |           |
        v           v           v
     Planner       Router   Context Manager
        |           |           |
        +-----------+-----------+
                    |
                    v
          Specialized Agent Policy
      coding / research / browser / data / general
                    |
                    v
             +-------------+
             | Tool Gateway|
             +------+------+ 
                    |
          +---------+----------+
          |         |          |
          v         v          v
      Permission  Sandbox   Tool Registry
        Engine      Port      / MCP / Plugins
          |         |          |
          +---------+----------+
                    |
                    v
               Tool Result
                    |
                    v
                Verifier
                    |
                    v
               Orchestrator
                    |
          Memory / Audit Events
```

This is a logical architecture. It does not require one class or package for every box. Existing Hermes components remain the concrete implementations wherever they already satisfy the responsibility.

## 5. SOLID rules

### Single Responsibility Principle

- Orchestration coordinates a task; it does not implement browser, shell, memory, or provider behavior.
- Planning creates and updates execution plans; it does not dispatch tools.
- Routing selects a specialization; it does not execute that specialization.
- Permission policy decides whether an action is allowed, denied, or requires approval; it does not prompt the user itself.
- Approval transport asks the user through CLI/gateway/UI; it does not decide policy.
- Tool execution runs a tool; it does not decide whether the caller is permitted.
- Memory stores and retrieves information; it does not mutate prompts directly.

### Open/Closed Principle

Adding a new specialized agent, provider, memory backend, sandbox backend, verifier, or tool source must normally require a new implementation/registration rather than modification of orchestration logic.

### Liskov Substitution Principle

Any implementation registered behind a platform contract must preserve the contract's result and failure semantics. For example, a Docker sandbox and an SSH sandbox may differ operationally but must be substitutable from the orchestration layer's point of view.

### Interface Segregation Principle

Avoid a universal `AgentServices` or `ToolContext` object with every possible capability. Prefer small ports such as:

- `ToolExecutor`
- `PermissionEvaluator`
- `ApprovalRequester`
- `SandboxExecutor`
- `MemoryReader`
- `MemoryWriter`
- `PlanStore`
- `TaskRouter`
- `Verifier`

### Dependency Inversion Principle

High-level orchestration depends on contracts. Concrete dependencies such as OpenAI clients, Playwright/browser backends, SQLite, Docker, SSH, or specific memory vendors remain behind adapters.

## 6. Domain model

The orchestration layer will use explicit task/result models instead of unstructured dictionaries where practical.

### AgentTask

Required concepts:

- task ID
- conversation/session ID
- user objective
- execution scope
- specialization hint
- available capabilities
- relevant context references
- risk/permission context
- cancellation state

### Plan

Required concepts:

- plan ID
- ordered steps
- current step
- status per step
- dependencies
- optional verifier criteria
- revision history

Planning remains optional for simple one-step work.

### AgentAction

Represents an intended action before execution:

- action ID
- task ID
- actor/specialization
- tool/capability
- normalized arguments
- risk classification
- reason metadata suitable for audit

### ActionDecision

One of:

- allow
- deny
- require approval

The decision must be separate from the mechanism used to obtain approval.

### ToolResult

Normalized concepts:

- success/failure
- output
- structured error
- retryability
- side-effect metadata
- artifacts
- timing

### VerificationResult

One of:

- passed
- failed
- inconclusive
- not_applicable

A verifier may return remediation guidance to the orchestrator, but it must not silently perform unrelated fixes.

## 7. Specialized agents

Specialization is implemented as policy/configuration over the common core unless a genuinely different runtime is required.

Initial specializations:

### General

Default task handling and coordination.

### Coding

Strongest behavioral rules:

1. inspect repository conventions before changing code
2. verify dependencies instead of assuming them
3. understand relevant code and tests first
4. plan when the change is non-trivial
5. make the smallest coherent change
6. test the changed behavior
7. run the project-specific formatter/linter/type checks where applicable
8. avoid unrelated fixes
9. preserve Git history and user changes

### Research

Strongest behavioral rules:

1. classify the information need
2. prioritize authoritative structured sources when available
3. inspect original sources, not snippets alone
4. cross-check material claims
5. distinguish source-derived facts from inference
6. produce citations/artifacts appropriate to the requested output

### Browser

Focused on stateful browser interaction. It uses the existing browser tooling and permission system; it does not receive a separate browser runtime unless required by the configured backend.

### Data

Focused on structured/unstructured data transformation, validation, analysis, and artifact generation. Complex calculations are performed through executable tools rather than mental arithmetic.

Specializations do not automatically add tools to the core schema. Tool availability continues to follow Hermes toolsets, service gates, plugins, and MCP.

## 8. Tool Gateway

The gateway is an application-facing facade over the existing registry and dispatch system.

Responsibilities:

1. resolve a requested tool/capability
2. normalize the invocation
3. classify risk
4. ask the permission engine for a decision
5. request approval when policy requires it
6. choose the configured execution backend
7. execute
8. normalize the result
9. emit observable lifecycle events

The gateway must not duplicate `tools/registry.py`. The registry remains the source of tool discovery and schema registration.

Proposed lifecycle:

```text
requested
  -> resolved
  -> permission_evaluated
  -> approval_requested? 
  -> executing
  -> succeeded | failed | cancelled
  -> verified?
```

## 9. Permission architecture

Permission logic is divided into two concerns.

### Policy

Pure decision logic that can be tested without a CLI, gateway, or browser:

- operation class
- target resource
- sandbox mode
- network mode
- user/profile policy
- configured allow/deny patterns
- destructive side effects
- credential access

### Approval transport

Mechanism used to ask the user:

- CLI confirmation
- gateway message
- ACP/UI request
- non-interactive policy

No tool adapter may bypass the policy engine merely because a different entry point invoked it.

Initial risk capabilities:

- read
- write
- execute
- network
- deploy
- credential_access
- destructive

These capabilities may be combined instead of forcing every tool into one mutually-exclusive bucket.

## 10. Sandbox architecture

The sandbox layer is a capability interface over the existing environment backends.

A sandbox execution request should be able to express:

- working directory
- command/program
- environment allowlist
- mounted paths
- network policy
- timeout
- resource limits where supported
- cancellation token

Existing backends remain authoritative for backend-specific behavior:

- local
- Docker
- SSH
- Daytona
- Modal
- Singularity

Security principle: orchestration asks for capabilities; adapters decide how those capabilities are implemented on the selected backend.

## 11. Memory architecture

The existing memory provider ABC remains the extension boundary. v1 formalizes four scopes:

### Working memory

Ephemeral state required to execute the current task or plan.

### Conversation memory

Conversation/session history and derived state required for continuity.

### Project memory

Durable project facts such as architecture decisions, repository conventions, important paths, and prior verified outcomes.

### User memory

Durable user preferences and user-specific facts that are appropriate to retain.

Retrieval is explicit. Memory results are selected by a context manager and inserted through the existing prompt/context tiers without mutating prior conversation turns.

Sensitive data and secrets are never persisted merely because they appeared in tool output.

## 12. Context manager

The context manager is responsible for selecting relevant context, not for changing historical messages.

Inputs may include:

- current user objective
- current plan step
- recent tool results
- project context files
- retrieved memory
- specialization policy
- available tool guidance

Outputs feed the existing prompt builder and compression/caching system.

Prompt caching remains a hard compatibility constraint: context tiers must be stable in ordering and only expected volatile sections may change.

## 13. Verification layer

Verification is capability-specific and opt-in by task type.

Examples:

- coding: targeted tests -> broader relevant tests -> lint/type/build as configured
- research: source completeness, citation support, conflicting evidence
- data: schema validation, totals/invariants, reproducibility checks
- browser: confirm page state/result after side-effecting interaction

Verification does not mean running every possible check after every action. The orchestrator selects the narrowest useful verifier based on task and risk.

## 14. Event and audit model

Introduce a normalized internal execution event envelope that can be consumed by existing callbacks/logging/trajectory systems.

Suggested fields:

- event ID
- task ID
- conversation/session ID
- parent action ID
- timestamp
- event type
- actor/specialization
- capability/tool name
- status
- duration
- retry count
- permission decision metadata
- artifact references

Never log raw secrets or credentials.

No new external telemetry is introduced by this architecture.

## 15. Dependency rules

The intended dependency direction is:

```text
entry points
    -> orchestration/application contracts
        -> domain models
        -> ports/interfaces
            <- adapters (tools, providers, memory, sandbox, approvals)
```

Rules:

1. domain/orchestration contracts do not import CLI/gateway UI code
2. orchestration does not import vendor SDKs
3. permission policy does not import approval UI
4. specializations do not directly instantiate tools
5. tool adapters do not mutate agent plans
6. memory providers do not directly rebuild the system prompt
7. adapters may depend on infrastructure; high-level policies may not

## 16. Proposed incremental code structure

This is a migration target, not a requirement to move all existing files immediately.

```text
agent/
  orchestration/
    contracts.py
    models.py
    events.py
    router.py
    verification.py

  specializations/
    base.py
    general.py
    coding.py
    research.py
    browser.py
    data.py

  memory_manager.py           # existing
  memory_provider.py          # existing
  prompt_builder.py           # existing
  context_engine.py           # existing

tools/
  gateway.py                  # facade over registry/dispatch
  permission_policy.py        # pure permission decisions
  approval.py                 # existing detection/adapters migrated gradually
  registry.py                 # existing source of truth
  environments/               # existing sandbox backends
```

Files are introduced only when a concrete first consumer exists. No empty speculative abstraction is added solely to match the diagram.

## 17. Migration phases

### Phase 0 - Baseline and characterization

- identify existing behavior contracts around `AIAgent`, tool dispatch, approval, memory, and environment selection
- identify existing tests that protect those contracts
- add characterization tests only where a refactor lacks a safety net

Exit condition: we can refactor without guessing current behavior.

### Phase 1 - Shared contracts and domain models

- add minimal orchestration task/action/result models
- add narrow Protocol/ABC contracts only for immediate existing consumers
- no runtime behavior change

Exit condition: new contracts pass tests and can wrap existing execution paths.

### Phase 2 - Tool execution facade

- wrap existing registry/dispatch behind a tool-execution facade
- preserve tool schemas and prompt caching
- route one existing internal execution path through the facade

Exit condition: behavior parity with existing tool execution.

### Phase 3 - Permission separation

- extract pure permission decision logic from approval transport
- keep CLI/gateway approval UX unchanged
- exercise destructive/non-destructive E2E paths

Exit condition: the same action receives the same decision independent of entry point.

### Phase 4 - Sandbox port

- define sandbox execution capability around existing environment backends
- migrate one terminal/code execution path
- retain backend-specific behavior in adapters

Exit condition: local and at least one isolated backend pass behavioral contract tests.

### Phase 5 - Orchestration extraction

- move coherent orchestration responsibilities out of the `run_agent.py` god-file in mechanical, reviewable slices
- preserve `AIAgent` as the compatibility facade while internals become composable

Exit condition: entry points still construct/use `AIAgent` without breaking changes while orchestration dependencies are explicit.

### Phase 6 - Specialized policies

- formalize coding/research/browser/data policies
- reuse skills/toolsets/delegation instead of growing core model tools
- route specialization without changing prompt history

Exit condition: specialization changes policy/context/tool availability safely, not core loop semantics.

### Phase 7 - Memory/context boundaries

- formalize memory scopes and retrieval requests
- connect project/user memory through the existing memory provider/context mechanisms
- add secret filtering and context-budget tests

Exit condition: memory improves continuity without cache-breaking prompt mutation.

### Phase 8 - Verification and observability

- add verifier contracts with concrete coding/research/data consumers
- normalize execution lifecycle events into existing logging/callback/trajectory systems

Exit condition: verification failures are actionable and observable without external telemetry requirements.

## 18. Test strategy

The refactor follows behavior contracts, not snapshot-heavy change detectors.

Required test categories as affected code moves:

- unit tests for pure policy and domain transitions
- contract tests shared by interchangeable adapters
- characterization tests for legacy behavior before extraction
- integration tests for registry -> permission -> execution -> normalized result
- E2E tests for security/config propagation and environment backends where feasible
- prompt-cache stability tests when prompt/context code is touched
- cancellation/interruption tests for long-running actions

Tests should assert invariants such as relationships and state transitions rather than fixed counts of tools/providers/config values.

## 19. Definition of done for each increment

An increment is complete only when:

1. the change has one clear architectural responsibility
2. existing project conventions were inspected first
3. relevant tests pass
4. relevant lint/type/build checks pass when configured and applicable
5. no unrelated code is changed
6. no new secret exposure is introduced
7. tool schema footprint does not grow without a concrete justification
8. prompt caching and role alternation remain valid
9. the change is committed to the feature branch before the next increment begins

## 20. First implementation slice

The first code slice after this specification will be deliberately small:

1. inspect the current tool dispatch, approval, environment, memory, and agent-loop tests
2. introduce the minimal orchestration domain contracts needed by one existing path
3. add tests proving those contracts are behavior-neutral
4. commit before starting the next slice

This sequence establishes a SOLID seam without forcing a large rewrite and gives every subsequent change a stable dependency boundary.
