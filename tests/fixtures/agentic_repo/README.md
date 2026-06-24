# Agentic Fixture App

A tiny, self-contained Python application used as a **crafted fixture repository**
for the `agentic-codebase-writer`'s credential-free, offline tests. The scripted
fake-agent provider explores this repo with the real `Read`/`Grep` tools (rooted at
this directory in read-only mode) and emits a grounded, `file:line`-cited body; the
cited lines must resolve to the real source here, so this content is kept stable.

## Layout

- `pyproject.toml` — the build manifest (entry point `fixture-app = "app:main"`).
- `app.py` — the entry point. Wires an `Application` to the work engine.
- `engine.py` — the `Engine` the application drives; loads configuration, then
  runs one bounded work cycle.
- `config.py` — the configuration loader (`load_config`) the engine depends on.

## How it runs

```
main()  ->  Application().run()  ->  Engine.start()  ->  load_config()
```

The entry point constructs an `Application`, whose `run` delegates to `Engine.start`.
The engine loads its configuration via `load_config` and then drives a bounded loop.

## Stability contract

The scripted body cites specific symbols by line: `Application` and `run` in
`app.py`, `start` in `engine.py`, and `load_config` in `config.py`. Do not shift
those symbols' line numbers — the fixture tests assert each cited line still holds
the symbol it claims.
