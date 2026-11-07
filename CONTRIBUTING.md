# Contributing to VideoMentor

Thanks for helping. Bug reports, ideas and pull requests are all welcome.

## Before you start
- Open an issue first for anything bigger than a small fix, so we can agree on the approach.
- Keep VideoMentor read-only against YouTube and local-first: no new services that receive users' libraries.

## Making a change
```sh
uv sync
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
cd web && npm install && npm test && npx tsc --noEmit
```
Add or update tests with your change. Keep pull requests focused on one thing.

## Contributor license agreement
VideoMentor is licensed under the GNU AGPL-3.0. So that the project can also offer a separate commercial license (for example to an organization that needs to customize it privately), contributions need the maintainer's permission to relicense them.

By opening a pull request, you agree that:
1. You wrote the contribution, or have the right to submit it.
2. You license your contribution to the project under the GNU AGPL-3.0.
3. You also grant Christopher Larkin (and any organization he assigns the project to) a perpetual, worldwide, royalty-free license to use, change and relicense your contribution under other terms, including commercial licenses.
4. You keep the copyright in your contribution.

Add this line to each commit message to confirm (`git commit -s` adds it for you):

```
Signed-off-by: Your Name <your@email>
```

## Code of conduct
Be kind and assume good intent. Harassment or disrespect of any kind isn't welcome.
