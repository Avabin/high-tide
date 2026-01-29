#!/bin/bash
# setup-dev.sh - Development environment setup script using uv
#
# This script sets up the development environment for High Tide using uv,
# a fast Python package installer and resolver.
#
# Usage:
#   ./setup-dev.sh           # Full setup
#   ./setup-dev.sh --help    # Show help
#   ./setup-dev.sh --deps    # Install only Python dependencies
#   ./setup-dev.sh --venv    # Create only the virtual environment
#
# Security Note:
#   The uv installation downloads a script from https://astral.sh/uv/install.sh
#   Review the script before running if you have security concerns, or install
#   uv manually: https://github.com/astral-sh/uv#installation

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

# Global flags (set by argument parsing)
CLEAN=false

# Print colored message
print_msg() {
    local color=$1
    local msg=$2
    echo -e "${color}${msg}${NC}"
}

# Print section header
print_header() {
    echo ""
    print_msg "$BLUE" "========================================"
    print_msg "$BLUE" "$1"
    print_msg "$BLUE" "========================================"
    echo ""
}

# Check if a command exists
command_exists() {
    command -v "$1" &> /dev/null
}

# Show help
show_help() {
    cat << EOF
High Tide Development Environment Setup

Usage: $(basename "$0") [OPTIONS]

Options:
    --help      Show this help message
    --deps      Install only Python dependencies (skip venv creation)
    --venv      Create only the virtual environment (skip dependencies)
    --clean     Remove existing virtual environment before setup

Note: --deps and --venv are mutually exclusive. If both are provided,
      only --deps will be executed.

System Dependencies (install manually if needed):
    - meson
    - ninja
    - pkg-config
    - blueprint-compiler
    - desktop-file-utils
    - libadwaita-1-dev
    - libportal-dev / libportal-gtk4-dev
    - libsecret-1-dev
    - gstreamer1.0-plugins-base
    - gstreamer1.0-plugins-good

Python Dependencies (installed by this script):
    - pygobject
    - tidalapi
    - requests
    - python-mpd2
    - pypresence
    - pylast (for Last.fm scrobbling)
    - ruff (for linting)

Security Note:
    The uv installation downloads a script from https://astral.sh/uv/install.sh
    Review the script before running if you have security concerns, or install
    uv manually: https://github.com/astral-sh/uv#installation

EOF
}

# Install uv if not present
install_uv() {
    if command_exists uv; then
        print_msg "$GREEN" "✓ uv is already installed"
        uv --version
        return 0
    fi

    print_header "Installing uv"
    
    print_msg "$YELLOW" "Note: This will download and run a script from https://astral.sh/uv/install.sh"
    print_msg "$YELLOW" "Press Ctrl+C within 3 seconds to cancel..."
    sleep 3
    
    if command_exists curl; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command_exists wget; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        print_msg "$RED" "Error: curl or wget is required to install uv"
        print_msg "$YELLOW" "Please install uv manually: https://github.com/astral-sh/uv"
        exit 1
    fi

    # Add to PATH for current session
    export PATH="$HOME/.cargo/bin:$PATH"
    
    if command_exists uv; then
        print_msg "$GREEN" "✓ uv installed successfully"
        uv --version
    else
        print_msg "$RED" "Error: uv installation failed"
        exit 1
    fi
}

# Find available Python version (preferring 3.11+)
find_python() {
    local python_cmd=""
    
    # Check for Python 3.11+ first (preferred for this project)
    for version in python3.13 python3.12 python3.11 python3; do
        if command_exists "$version"; then
            local ver_output=$("$version" --version 2>&1)
            if [[ "$ver_output" =~ Python\ 3\.1[1-9] ]] || [[ "$ver_output" =~ Python\ 3\.[2-9][0-9] ]]; then
                python_cmd="$version"
                break
            elif [[ "$version" == "python3" ]]; then
                # Fallback to any Python 3
                python_cmd="$version"
                break
            fi
        fi
    done
    
    if [ -z "$python_cmd" ]; then
        print_msg "$RED" "Error: Python 3 is required but not found"
        print_msg "$YELLOW" "Please install Python 3.11 or newer"
        exit 1
    fi
    
    echo "$python_cmd"
}

# Create virtual environment
create_venv() {
    print_header "Creating virtual environment"
    
    if [ -d "$VENV_DIR" ]; then
        if [ "$CLEAN" = true ]; then
            print_msg "$YELLOW" "Removing existing virtual environment..."
            rm -rf "$VENV_DIR"
        else
            print_msg "$YELLOW" "Virtual environment already exists at $VENV_DIR"
            print_msg "$YELLOW" "Use --clean to recreate it"
            return 0
        fi
    fi

    # Find available Python
    local python_cmd
    python_cmd=$(find_python)
    print_msg "$BLUE" "Using Python: $python_cmd ($($python_cmd --version))"

    # Create venv with system site packages for GTK/GObject bindings
    # This is necessary because PyGObject needs to access system GTK libraries
    uv venv "$VENV_DIR" --system-site-packages --python "$python_cmd"
    
    # Verify the virtual environment was created
    if [ ! -d "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/activate" ]; then
        print_msg "$RED" "Error: Failed to create virtual environment"
        exit 1
    fi
    
    print_msg "$GREEN" "✓ Virtual environment created at $VENV_DIR"
}

# Install Python dependencies
install_deps() {
    print_header "Installing Python dependencies"
    
    if [ ! -d "$VENV_DIR" ] || [ ! -f "$VENV_DIR/bin/activate" ]; then
        print_msg "$RED" "Error: Virtual environment not found at $VENV_DIR"
        print_msg "$YELLOW" "Run the script without --deps first to create it, or run:"
        print_msg "$YELLOW" "  ./setup-dev.sh"
        exit 1
    fi

    # Activate venv for pip operations
    source "$VENV_DIR/bin/activate"

    # Core dependencies
    print_msg "$BLUE" "Installing core dependencies..."
    uv pip install \
        tidalapi \
        requests \
        python-mpd2 \
        pypresence \
        pylast

    # Development dependencies
    print_msg "$BLUE" "Installing development dependencies..."
    uv pip install \
        ruff \
        mypy \
        pytest

    print_msg "$GREEN" "✓ Python dependencies installed"
    
    # Show installed packages
    print_msg "$BLUE" "\nInstalled packages:"
    uv pip list
}

# Check system dependencies
check_system_deps() {
    print_header "Checking system dependencies"
    
    local missing_deps=()
    
    # Check for required build tools
    if ! command_exists meson; then
        missing_deps+=("meson")
    fi
    
    if ! command_exists ninja; then
        missing_deps+=("ninja-build")
    fi
    
    if ! command_exists pkg-config; then
        missing_deps+=("pkg-config")
    fi

    if ! command_exists blueprint-compiler; then
        missing_deps+=("blueprint-compiler")
    fi
    
    if [ ${#missing_deps[@]} -gt 0 ]; then
        print_msg "$YELLOW" "Missing system dependencies:"
        for dep in "${missing_deps[@]}"; do
            print_msg "$YELLOW" "  - $dep"
        done
        echo ""
        print_msg "$YELLOW" "On Debian/Ubuntu, install with:"
        print_msg "$YELLOW" "  sudo apt install ${missing_deps[*]}"
        echo ""
        print_msg "$YELLOW" "On Fedora, install with:"
        print_msg "$YELLOW" "  sudo dnf install ${missing_deps[*]}"
        echo ""
        print_msg "$YELLOW" "On Arch Linux, install with:"
        print_msg "$YELLOW" "  sudo pacman -S ${missing_deps[*]}"
        echo ""
    else
        print_msg "$GREEN" "✓ All required build tools are installed"
    fi
}

# Print activation instructions
print_activation_instructions() {
    print_header "Setup Complete!"
    
    cat << EOF
To activate the development environment, run:

    source ${VENV_DIR}/bin/activate

To build the project:

    meson setup build
    meson compile -C build

To run the application (after building):

    meson devenv -C build
    high-tide

To run linting:

    ruff check src/

To deactivate the virtual environment:

    deactivate

EOF
}

# Main function
main() {
    local DEPS_ONLY=false
    local VENV_ONLY=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --help)
                show_help
                exit 0
                ;;
            --deps)
                DEPS_ONLY=true
                shift
                ;;
            --venv)
                VENV_ONLY=true
                shift
                ;;
            --clean)
                CLEAN=true
                shift
                ;;
            *)
                print_msg "$RED" "Unknown option: $1"
                show_help
                exit 1
                ;;
        esac
    done

    cd "$PROJECT_ROOT"

    print_msg "$GREEN" "High Tide Development Environment Setup"
    print_msg "$GREEN" "Project root: $PROJECT_ROOT"

    # Install uv
    install_uv

    if [ "$DEPS_ONLY" = true ]; then
        install_deps
        exit 0
    fi

    if [ "$VENV_ONLY" = true ]; then
        create_venv
        exit 0
    fi

    # Full setup
    check_system_deps
    create_venv
    install_deps
    print_activation_instructions
}

main "$@"
