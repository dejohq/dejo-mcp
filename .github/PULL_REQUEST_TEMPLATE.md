## What this changes

<!-- What does this pull request do, and why? -->

Closes #<!-- issue number, if there is one -->

## How it was tested

- [ ] Engine tests pass (`cd engine && pytest`)
- [ ] MCP tests pass (`cd mcp && pytest`)
- [ ] `ruff check` and `ruff format --check` are clean
- [ ] A bug fix comes with a test that fails without it
- [ ] Tried on a real website (say which below)

<!-- Anything you checked by hand, and on which site. -->

## The rules Dejo keeps

- [ ] Replay still makes zero model calls and reaches no network on its own
- [ ] Every new step type still proves it landed
- [ ] `dejo forget` still really forgets
- [ ] No typed value, password or account name can reach memory or a shared route
- [ ] Nothing new is printed to stdout by the MCP server

## AI assistance

- [ ] No AI assistance
- [ ] AI-assisted or AI-written. Tool and what I checked myself:

- [ ] I can explain every line of this change.
