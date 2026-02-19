# Standalone Agent Platform

A Python agent platform with plugin-based tool loading, per-agent permissions, LangGraph-style graph orchestration, and a CLI interface.

## Features

- **Plugin system** — Drop-in tool plugins with JSON manifests and YAML config
- **Permission enforcement** — Per-agent allow-lists checked at invocation time
- **Graph orchestration** — Directed graph execution with conditional routing
- **BM25 search** — Pure Python keyword search over project docs (no embeddings)
- **Zero AI dependencies** — Runs entirely locally, no external API calls

## Installation

```bash
cd "day_21 9.02.2026/"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Usage

### Ask a question

```bash
python -m core.cli.main ask "What is the project architecture?"
python -m core.cli.main ask "What branch am I on?" --debug
```

### List loaded plugins

```bash
python -m core.cli.main list-plugins
```

### List registered tools

```bash
python -m core.cli.main list-tools
```

## Running Tests

```bash
python -m unittest discover tests/ -v
```

## Project Structure

```
core/
  registry/        # Tool ABC, ToolRegistry, PermissionChecker, PluginLoader
  orchestration/   # Graph engine, Node ABC, concrete nodes
  agents/          # Agent definitions (project_helper)
  cli/             # CLI entry point
plugins/
  docs_rag/        # BM25 documentation search
  git_context/     # Git branch info
config/
  plugins.yaml     # Plugin enable/disable
  agents.yaml      # Agent permission allow-lists
project/docs/      # Sample documentation
tests/             # Unit tests
```

## Configuration

### plugins.yaml

Enable or disable plugins:

```yaml
plugins:
  docs_rag:
    enabled: true
  git_context:
    enabled: true
```

### agents.yaml

Define agent permissions:

```yaml
agents:
  project_helper:
    permissions:
      - "docs:read"
      - "git:read"
```

## Dependencies

- `pyyaml>=6.0`
