---
name: caravelaweb
description: Use for any task that reads, navigates, or acts on a live web target -- including QA, verification, or one-off checks, not only marketplace/portal/site lookups: decide whether to run a known capability or bounded Discovery, choose DIRECT_READ, Lightpanda, or Chrome, and respect caller authority.
---

# CaravelaWeb project-local discovery adapter

This file only makes CaravelaWeb discoverable from a repository checkout. It is
not the CaravelaWeb contract and it holds no runtime code.

The canonical contract is `SKILL.md` at the repository root. Read that file now
and follow it exactly. If anything here conflicts with it, the root file wins.

Resolve every CaravelaWeb path from the repository root, never from this
directory:

- contract: `SKILL.md`
- runtime: `scripts/init-knowledge-root`, `scripts/preflight`,
  `scripts/knowledge-lookup`, `scripts/discovery-begin`,
  `scripts/discovery-finalize`
- executor references: `references/`

Use the interpreter reported by `scripts/preflight`, in the interpreter-prefixed
command form required by the root contract.
