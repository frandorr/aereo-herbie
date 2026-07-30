#!/usr/bin/env bash
set -e

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color
BOLD='\033[1m'

echo -e "${BLUE}${BOLD}========================================================${NC}"
echo -e "${BLUE}${BOLD}      Welcome to the aereo-plugin setup wizard!           ${NC}"
echo -e "${BLUE}${BOLD}========================================================${NC}"
echo ""

# 1- Project name should start with aereo-
echo -e "${BOLD}1. Project Configuration${NC}"
read -p "Enter your project name (e.g., aereo-search-earthaccess): " PROJECT_NAME
if [[ ! $PROJECT_NAME =~ ^aereo- ]]; then
    echo -e "${RED}Error: Project name must start with 'aereo-'${NC}"
    exit 1
fi

read -p "Enter Author Name: " AUTHOR_NAME
if [ -z "$AUTHOR_NAME" ]; then
    echo -e "${RED}Author Name cannot be empty.${NC}"
    exit 1
fi

read -p "Enter GitHub username/organization: " GITHUB_ORG
if [ -z "$GITHUB_ORG" ]; then
    echo -e "${RED}GitHub username/organization cannot be empty.${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}🚀 Setting up project: $PROJECT_NAME...${NC}"

# Basic variables
PLUGIN_PART=${PROJECT_NAME/aereo-/}
COMPONENT_NAME=$(echo "$PLUGIN_PART" | tr '-' '_')

# Update root pyproject.toml name
if [[ "$OSTYPE" == "darwin"* ]]; then
    sed -i '' "s/^name = .*/name = \"$PROJECT_NAME-workspace\"/" pyproject.toml
else
    sed -i "s/^name = .*/name = \"$PROJECT_NAME-workspace\"/" pyproject.toml
fi


# Install uv if missing
echo -e "\n${BOLD}2. Environment Check${NC}"
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
else
    echo -e "${GREEN}✓ uv is already installed.${NC}"
fi

# Add polylith-cli as a dev dependency and sync
echo -e "\n${BOLD}3. Installing Dependencies${NC}"
uv add polylith-cli python-semantic-release pytest --dev
uv sync

# 4- Create component and project
echo -e "\n${BOLD}4. Scaffolding Polylith Bricks${NC}"
echo -e "Creating component: ${BLUE}$COMPONENT_NAME${NC}..."
uv run poly create component --name "$COMPONENT_NAME"

echo -e "Creating project: ${BLUE}$PROJECT_NAME${NC}..."
uv run poly create project --name "$PROJECT_NAME"

# 5- Add corresponding plugin entrypoint to the created project pyproject.toml
PROJECT_PYPROJECT="projects/$PROJECT_NAME/pyproject.toml"

echo -e "Customizing ${BLUE}$PROJECT_PYPROJECT${NC}..."

# Generate Class Name and Base Class Info
CLASS_NAME=$(echo "$PLUGIN_PART" | awk -F'-' '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2))} 1' OFS='')
if [[ "$PLUGIN_PART" == search-* ]]; then
    BASE_CLASS="SearchProvider"
    IMPORT_STMT="from aereo.interfaces import SearchProvider"
elif [[ "$PLUGIN_PART" == extract-* ]]; then
    BASE_CLASS="Extractor"
    IMPORT_STMT="from aereo.interfaces import Extractor"
else
    BASE_CLASS="Plugin"
    IMPORT_STMT="from aereo.interfaces import Plugin"
fi

cat <<EOF > "$PROJECT_PYPROJECT"
[build-system]
requires = ["hatchling", "hatch-polylith-bricks"]
build-backend = "hatchling.build"

[project]
name = "$PROJECT_NAME"
version = "0.1.0"
description = "Polylith project for the $PLUGIN_PART plugin"
readme = "README.md"
authors = [{ name = "$AUTHOR_NAME" }]

requires-python = ">=3.12"

dependencies = [
    "aereo",
]

[project.urls]
Homepage = "https://github.com/$GITHUB_ORG/$PROJECT_NAME"
Issues = "https://github.com/$GITHUB_ORG/$PROJECT_NAME/issues"
Repository = "https://github.com/$GITHUB_ORG/$PROJECT_NAME"

[project.entry-points."aereo.plugins"]
$COMPONENT_NAME = "aereo.$COMPONENT_NAME.core:$CLASS_NAME"

[tool.hatch]
build.dev-mode-dirs = [ "../../components", "../../bases", "../../development", "." ]
build.hooks.polylith-bricks = {}
build.targets.wheel.packages = ["aereo"]

[tool.polylith]
bricks."../../components/aereo/$COMPONENT_NAME" = "aereo/$COMPONENT_NAME"
EOF

# 6- Overwrite component files with new class-based structure
CORE_PY="components/aereo/$COMPONENT_NAME/core.py"
echo -e "Scaffolding ${BLUE}$CORE_PY${NC} class..."

cat <<EOF > "$CORE_PY"
$IMPORT_STMT

class $CLASS_NAME($BASE_CLASS, plugin_abstract=False):
    """$BASE_CLASS plugin for $PROJECT_NAME.

    Implementation notes:
    - Grid configuration is passed via ``grid_config`` (GridConfig) to
      ``prepare_for_extraction()``. Plugins should read cell size, margin,
      and overlap from ``extraction_task.grid_config`` rather than defining
      their own defaults.
    - Domain-specific extraction parameters belong in
      ``profile.extract_params``. The ambiguous ``prepare_params`` dict has
      been removed.
    """
    pass
EOF

INIT_PY="components/aereo/$COMPONENT_NAME/__init__.py"
cat <<EOF > "$INIT_PY"
from .core import $CLASS_NAME

__all__ = ["$CLASS_NAME"]
EOF

# Install prek tool
echo -e "\n${BOLD}6. Finalizing Setup${NC}"
echo "Installing prek hooks..."
uv tool install prek || true

echo ""
echo -e "${GREEN}${BOLD}========================================================${NC}"
echo -e "${GREEN}${BOLD}Setup complete! Project $PROJECT_NAME is ready.      ${NC}"
echo -e "Created component: ${BLUE}components/aereo/$COMPONENT_NAME${NC}"
echo -e "Created project:   ${BLUE}projects/$PROJECT_NAME${NC}"
echo ""
echo -e "Next steps:"
echo -e "  1. Add your logic to ${BLUE}components/aereo/$COMPONENT_NAME/core.py${NC}"
echo -e "  2. Run ${BLUE}uv run pytest${NC} to verify the setup"
echo -e "  3. Use ${BLUE}uv run poly info${NC} to see your workspace"
echo -e "${GREEN}${BOLD}========================================================${NC}"

