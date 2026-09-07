# Candidate fix: nested User.createdAt nulls GraphQL items

When an item query asks for its author's `createdAt`, the public API can return the entire item as null. The same author queried directly has a valid creation date.

## Reproduction
POST `https://stacker.news/api/graphql` with:
```graphql
query { item(id: "1533010") { id user { name createdAt } } }
```
Observed on 2026-09-07:
```json
{"data":{"item":null},"errors":[{"message":"Cannot return null for non-nullable field User.createdAt.","path":["item","user","createdAt"]}]}
```
Removing only `createdAt` returns the item. A direct `user(name: "onlybugs05") { name createdAt }` query returns a valid date. Exact requests/results are in `live-reproduction.json`.

## Cause and fix
The item-query path uses `to_json(users.*)` / `to_jsonb(users.*)`, so joined users expose PostgreSQL's `created_at`. Prisma user lookups expose `createdAt`. The schema declares `User.createdAt: Date!`, but there is no field resolver for the raw-row spelling.

The one-line candidate resolver preserves Prisma's field and falls back to the raw SQL field:
```js
createdAt: user => user.createdAt ?? user.created_at,
```

The patch is based on upstream commit `d4aaf0ac28e3a1cd2b2b6ed0fbd3647c0e1a5422` and does not change the schema, query filters, permissions or dates stored in the database.

## Validation
`npm ci --ignore-scripts && npm test` runs a standalone GraphQL regression harness.
It parses the actual before/after source, extracts the field resolver without loading unrelated database/wallet modules, and executes nested GraphQL queries against the two data shapes.

Four checks pass: the original raw-row failure, corrected raw-row response, preserved Prisma Date/preference, and retained non-null failure for genuinely missing dates.

This is focused regression evidence. The full repository suite and a database-backed staging deployment have not been run.

## Contribution and payment status
Prepared with AI assistance by Codex for @workesfm. No human review is claimed.
Not submitted as an upstream PR, not accepted and not paid. Seeking maintainer confirmation of an eligible paid contribution and submission route under the current program.
Upstream source attribution: [Stacker News](https://github.com/stackernews/stacker.news), MIT per its README.

