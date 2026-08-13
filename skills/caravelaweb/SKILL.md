---
name: caravelaweb
description: Use for any task that reads, navigates, or acts on a live web target -- including QA, verification, or one-off checks, not only marketplace/portal/site lookups: decide whether to run a known capability or bounded Discovery, choose DIRECT_READ, Lightpanda, or Chrome, and respect caller authority.
---

# CaravelaWeb plugin discovery adapter

This file exposes CaravelaWeb from an installed plugin. It is not the
CaravelaWeb contract and holds no runtime code.

The canonical contract is `SKILL.md` at the plugin root: `../..` from the
directory holding this adapter. Derive that root from this file's location,
never from the current working directory. Read the canonical file now and
follow it exactly. If anything here conflicts with it, the root file wins.

Resolve every CaravelaWeb path from that root, never from this directory:

- contract: `SKILL.md`
- runtime: `scripts/init-knowledge-root`, `scripts/preflight`,
  `scripts/knowledge-lookup`, `scripts/discovery-finalize`
- executor references: `references/`

Use the interpreter reported by `scripts/preflight`, in the interpreter-prefixed
command form required by the root contract.
