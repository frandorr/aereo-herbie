# Contributing to aereo-plugin-template

Thank you for your interest in contributing!

## General Guidelines

Please refer to the [AER core CONTRIBUTING.md](https://github.com/<org>/aer/blob/main/CONTRIBUTING.md) for:
- Reporting issues
- Development setup with uv and Polylith
- Pull request process
- Conventional Commits
- Code style (Ruff, basedpyright)

## Plugin-Specific Development

### Using This Template

This repository is a template for creating new AER plugins. To create a new plugin:

1. Click **"Use this template"** on GitHub.
2. Rename occurrences of `aereo-plugin-template` to your plugin name.
3. Update `pyproject.toml` metadata (name, description, keywords).
4. Replace the example code in `components/` with your plugin logic.
5. Add tests in `test/`.

### Setup

```bash
git clone https://github.com/<org>/aereo-plugin-template.git
cd aereo-plugin-template
uv sync --all-extras
```

### Testing

```bash
uv run pytest
uv run ruff check .
```

### Plugin Structure

- `components/aereo_plugin_template/` — example plugin implementation
- `projects/aereo-plugin-template/` — publishable package metadata
- `test/` — unit tests
