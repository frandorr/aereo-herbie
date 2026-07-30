# Examples — aer Plugin Template

This directory shows how to use the **aereo plugin template** to scaffold a new plugin.

## Quick Start

1. **Copy the template** to a new repository:
   ```bash
   cp -r aereo-plugin-template aereo-my-new-plugin
   cd aereo-my-new-plugin
   ```

2. **Run the setup script** to bootstrap your plugin:
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

   The setup script will:
   - Validate your project name follows the `aereo-` prefix rule.
   - Install `uv` (if missing) and set up workspace dependencies.
   - Create your first **Component** (logic) and **Project** (packaging).
   - Generate a pre-configured `pyproject.toml` with standard entry points.

3. **Implement your plugin logic** in the generated component:
   - For search plugins: override the `search()` method.
   - For extract plugins: override `prepare_for_extraction()` and `extract()`.
  - `prepare_for_extraction()` receives a `GridConfig` object — read tiling parameters (cell size, margin, overlap) from it rather than hard-coding defaults.
  - Domain config lives on `profile.extract_params`; the old `prepare_params` catch-all has been removed.

4. **Run tests** to verify everything is wired correctly:
   ```bash
   uv run pytest
   ```

## Reference Implementations

For production-ready examples, see:

- **Search plugin**: [aereo-search-aws-goes](https://github.com/frandorr/aereo-search-aws-goes)
- **Extract plugin**: [aereo-extract-aws-goes](https://github.com/frandorr/aereo-extract-aws-goes)

## Files

| File | Description |
|------|-------------|
| `README.md` | This file — explains how to scaffold a new plugin from the template. |
