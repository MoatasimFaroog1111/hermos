---
name: athmar-video-factory
description: Use when a user asks Hermes to plan, request, review or track Athmar AI Video Factory jobs; never spend or publish without explicit human approval.
version: 0.1.0
author: Athmar
license: MIT
metadata:
  hermes:
    tags: [video, production, approvals, athmar]
---

# Athmar AI Video Factory

## Scope
This skill defines the future integration contract. The backend API and
service credentials are NOT yet configured. Do not claim that a video was
created, uploaded, approved, or published without a verified backend response.

## Workflow
1. Collect a short creative brief, platform, aspect ratio, duration and language.
2. Draft script, storyboard and cost estimate; never invent provider prices.
3. Ask the backend to create a DRAFT only after an authenticated API tool exists.
4. Show the immutable prompt/price snapshot and request approval from an
   authorized HUMAN distinct from the requester.
5. Start rendering only when backend confirms approval and budget cap.
6. Report status from backend; use private expiring links for review.
7. Publishing requires a second explicit human approval.

## Security
- Never accept approval based on the assistant's own judgment.
- Never paste API keys into Telegram, prompts, Git or logs.
- Never bypass OIDC/service authentication using development X-User headers.
- Use an idempotency key for every mutating operation.
- Treat provider callbacks as untrusted until signatures and replay checks pass.
- If integration is unavailable, produce a storyboard only and explain the limitation.

## Completion criteria
A job is complete only when the backend returns a verified final status,
audited cost, and a valid asset reference. A drafted prompt is not a video.
