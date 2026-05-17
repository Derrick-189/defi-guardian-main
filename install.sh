#!/bin/bash
# =============================================================================
# DeFi Guardian - Complete Installation Script
# Sets up all dependencies for formal verification suite
# Tested on: Ubuntu 22.04/24.04, Debian 12
# =============================================================================

set -e  # Exit on any error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}▶ $1${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# Check if running as root (warn but don't require)
if [ "$EUID" -eq 0 ]; then
    log_warning "Running as root. Some tools may install system-wide."
fi

# Get the actual user's home directory (even when run with sudo)
if [ -n "$SUDO_USER" ]; then
    USER_HOME=$(eval echo ~$SUDO_USER)
    ACTUAL_USER=$SUDO_USER
else
    USER_HOME=$HOME
    ACTUAL_USER=$USER
fi

log_info "Installing for user: $ACTUAL_USER"
log_info "Home directory: $USER_HOME"

# =============================================================================
# STEP 1: System Updates and Basic Dependencies
# =============================================================================
log_step "Step 1: Updating System and Installing Basic Dependencies"

sudo apt update
sudo apt upgrade -y

sudo apt install -y \
    build-essential \
    curl \
    wget \
    git \
    make \
    gcc \
    g++ \
    pkg-config \
    libssl-dev \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    python3-tk \
    graphviz \
    libgraphviz-dev \
    default-jdk \
    default-jre \
    unzip \
    software-properties-common \
    apt-transport-https \
    ca-certificates \
    gnupg \
    lsb-release

log_success "Basic dependencies installed"

# =============================================================================
# STEP 2: Install SPIN Model Checker
# =============================================================================
log_step "Step 2: Installing SPIN Model Checker"

SPIN_VERSION="6.5.2"
SPIN_DIR="/opt/spin"

if command -v spin &> /dev/null; then
    log_success "SPIN already installed: $(spin -V 2>&1 | head -1)"
else
    cd /tmp
    wget -q https://github.com/nimble-code/Spin/archive/refs/tags/version-${SPIN_VERSION}.tar.gz -O spin-${SPIN_VERSION}.tar.gz
    tar -xzf spin-${SPIN_VERSION}.tar.gz
    cd Spin-version-${SPIN_VERSION}/Src
    
    make
    sudo cp spin /usr/local/bin/
    sudo chmod +x /usr/local/bin/spin
    
    # Verify installation
    if command -v spin &> /dev/null; then
        log_success "SPIN ${SPIN_VERSION} installed successfully"
    else
        log_error "SPIN installation failed"
    fi
    
    cd /tmp
    rm -rf spin-${SPIN_VERSION}.tar.gz Spin-version-${SPIN_VERSION}
fi

# =============================================================================
# STEP 3: Install Coq Theorem Prover
# =============================================================================
log_step "Step 3: Installing Coq Theorem Prover"

if command -v coqc &> /dev/null; then
    log_success "Coq already installed: $(coqc --version 2>&1 | head -1)"
else
    # Install via OPAM (recommended method)
    if ! command -v opam &> /dev/null; then
        log_info "Installing OPAM..."
        sudo apt install -y opam
    fi
    
    # Initialize OPAM for the user
    if [ ! -d "$USER_HOME/.opam" ]; then
        sudo -u $ACTUAL_USER opam init --bare --yes
    fi
    
    # Install Coq
    sudo -u $ACTUAL_USER opam switch create coq-verification 4.14.0 --yes || true
    eval $(sudo -u $ACTUAL_USER opam env)
    
    sudo -u $ACTUAL_USER opam install -y coq
    
    # Add OPAM to bashrc if not already there
    if ! grep -q "opam init" "$USER_HOME/.bashrc"; then
        echo 'eval $(opam env)' >> "$USER_HOME/.bashrc"
    fi
    
    log_success "Coq installed successfully"
fi

# =============================================================================
# STEP 4: Install Lean 4 and Elan
# =============================================================================
log_step "Step 4: Installing Lean 4 and Elan"

if command -v lean &> /dev/null; then
    log_success "Lean already installed: $(lean --version)"
else
    log_info "Downloading and installing Elan (Lean version manager)..."
    
    cd /tmp
    curl -sSfL https://github.com/leanprover/elan/releases/download/v3.1.1/elan-x86_64-unknown-linux-gnu.tar.gz -o elan.tar.gz
    tar -xzf elan.tar.gz
    sudo mv elan /usr/local/bin/
    sudo chmod +x /usr/local/bin/elan
    
    # Install Lean stable
    sudo -u $ACTUAL_USER elan toolchain install leanprover/lean4:stable
    sudo -u $ACTUAL_USER elan default leanprover/lean4:stable
    
    # Add to PATH in bashrc
    if ! grep -q "elan" "$USER_HOME/.bashrc"; then
        echo 'export PATH="$HOME/.elan/bin:$PATH"' >> "$USER_HOME/.bashrc"
    fi
    
    # Create symlink for immediate use
    export PATH="$USER_HOME/.elan/bin:$PATH"
    
    if command -v lean &> /dev/null; then
        log_success "Lean installed successfully"
    else
        log_warning "Lean installed but not in current PATH. Please restart terminal or source ~/.bashrc"
    fi
    
    rm -f elan.tar.gz
fi

# =============================================================================
# STEP 5: Install Rust and Cargo
# =============================================================================
log_step "Step 5: Installing Rust and Cargo"

if command -v rustc &> /dev/null; then
    log_success "Rust already installed: $(rustc --version)"
else
    log_info "Installing Rust via rustup..."
    
    sudo -u $ACTUAL_USER curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | \
        sudo -u $ACTUAL_USER sh -s -- -y --default-toolchain stable
    
    # Source cargo env
    source "$USER_HOME/.cargo/env"
    
    log_success "Rust installed successfully"
fi

# Ensure Rust is in PATH for this session
export PATH="$USER_HOME/.cargo/bin:$PATH"

# =============================================================================
# STEP 6: Install Rust Verification Tools
# =============================================================================
log_step "Step 6: Installing Rust Verification Tools (Prusti, Kani, Creusot)"

# Install required Rust components
rustup component add rust-src rustc-dev llvm-tools-preview

# --- Prusti ---
log_info "Installing Prusti..."
if command -v prusti-rustc &> /dev/null; then
    log_success "Prusti already installed"
else
    cargo install prusti --locked
    prusti-rustc --setup || true
    log_success "Prusti installed"
fi

# --- Kani ---
log_info "Installing Kani Rust Verifier..."
if command -v cargo-kani &> /dev/null || cargo kani --version &> /dev/null; then
    log_success "Kani already installed"
else
    cargo install --locked kani-verifier
    cargo kani setup
    log_success "Kani installed"
fi

# --- Creusot ---
log_info "Installing Creusot..."
if command -v creusot &> /dev/null; then
    log_success "Creusot already installed"
else
    cargo install creusot
    
    # Clone and build creusot-std library
    log_info "Setting up Creusot standard library..."
    CREUSOT_DIR="$USER_HOME/creusot"
    
    if [ ! -d "$CREUSOT_DIR" ]; then
        sudo -u $ACTUAL_USER git clone https://github.com/creusot-rs/creusot.git "$CREUSOT_DIR"
        cd "$CREUSOT_DIR"
        sudo -u $ACTUAL_USER git checkout $(creusot --version | grep -oP 'creusot \K[0-9.]+' || echo "main")
    fi
    
    log_success "Creusot installed"
    log_info "Creusot std path: $CREUSOT_DIR/creusot-std"
fi

# =============================================================================
# STEP 7: Install Python Dependencies
# =============================================================================
log_step "Step 7: Installing Python Dependencies"

# Create Python virtual environment
PROJECT_DIR="$USER_HOME/defi_guardian"
if [ ! -d "$PROJECT_DIR" ]; then
    log_info "Creating project directory: $PROJECT_DIR"
    sudo -u $ACTUAL_USER mkdir -p "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    log_info "Creating Python virtual environment..."
    sudo -u $ACTUAL_USER python3 -m venv venv
fi

# Activate and install packages
source venv/bin/activate

log_info "Installing Python packages..."
pip install --upgrade pip

pip install \
    customtkinter>=5.2.0 \
    streamlit>=1.28.0 \
    plotly>=5.18.0 \
    pandas>=2.0.0 \
    numpy>=1.24.0 \
    pillow>=10.0.0 \
    graphviz>=0.20.0 \
    watchdog \
    psutil

log_success "Python dependencies installed"

# =============================================================================
# STEP 8: Install SMT Solvers (Z3 and CVC5)
# =============================================================================
log_step "Step 8: Installing SMT Solvers"

# --- Z3 ---
if command -v z3 &> /dev/null; then
    log_success "Z3 already installed: $(z3 --version)"
else
    log_info "Installing Z3..."
    sudo apt install -y z3
    log_success "Z3 installed"
fi

# --- CVC5 ---
if command -v cvc5 &> /dev/null; then
    log_success "CVC5 already installed: $(cvc5 --version)"
else
    log_info "Installing CVC5..."
    cd /tmp
    wget -q https://github.com/cvc5/cvc5/releases/download/cvc5-1.1.2/cvc5-Linux-static.zip
    unzip -q cvc5-Linux-static.zip
    sudo mv cvc5-Linux-static/bin/cvc5 /usr/local/bin/
    sudo chmod +x /usr/local/bin/cvc5
    rm -rf cvc5-Linux-static*
    log_success "CVC5 installed"
fi

# =============================================================================
# STEP 9: Create Environment Configuration
# =============================================================================
log_step "Step 9: Creating Environment Configuration"

ENV_FILE="$PROJECT_DIR/.env"

cat > "$ENV_FILE" << 'EOF'
# DeFi Guardian Environment Configuration
# Generated by install.sh

# Project paths
export DEFI_GUARDIAN_HOME="$HOME/defi_guardian"
export CREUSOT_STD_PATH="$HOME/creusot/creusot-std"

# Rust environment
source "$HOME/.cargo/env"

# OPAM/Coq environment
eval $(opam env) 2>/dev/null || true

# Lean environment
export PATH="$HOME/.elan/bin:$PATH"

# Python virtual environment
source "$HOME/defi_guardian/venv/bin/activate"

# Verification tool paths
export PATH="/usr/local/bin:$PATH"
export VIPER_HOME="$HOME/.cargo/bin/viper_tools"

# Performance settings
export RUST_BACKTRACE=1
export KANI_UNWINDING=10
EOF

chown $ACTUAL_USER:$ACTUAL_USER "$ENV_FILE"

log_success "Environment configuration created at $ENV_FILE"

# =============================================================================
# STEP 10: Create Desktop Entry and Launcher
# =============================================================================
log_step "Step 10: Creating Desktop Entry"

# Create desktop entry
DESKTOP_ENTRY="$USER_HOME/.local/share/applications/defi-guardian.desktop"
mkdir -p "$USER_HOME/.local/share/applications"

cat > "$DESKTOP_ENTRY" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=DeFi Guardian
Name[en]=DeFi Guardian
GenericName=Formal Verification Suite
Comment=Formal verification platform for DeFi protocols
Exec=bash -c "source $ENV_FILE && python3 $PROJECT_DIR/desktop_app.py"
Icon=$PROJECT_DIR/defi_guardian.png
Terminal=false
StartupNotify=true
Categories=Development;Security;Utility;
Keywords=formal verification;SPIN;LTL;security;audit;defi;
StartupWMClass=defi-guardian
EOF

chown $ACTUAL_USER:$ACTUAL_USER "$DESKTOP_ENTRY"

# Create launcher script
LAUNCHER="$PROJECT_DIR/launch.sh"
cat > "$LAUNCHER" << 'EOF'
#!/bin/bash
source "$HOME/defi_guardian/.env"
cd "$HOME/defi_guardian"
python3 desktop_app.py
EOF

chmod +x "$LAUNCHER"
chown $ACTUAL_USER:$ACTUAL_USER "$LAUNCHER"

log_success "Desktop entry and launcher created"

# =============================================================================
# STEP 11: Verification of Installation
# =============================================================================
log_step "Step 11: Verifying Installation"

verify_tool() {
    local tool=$1
    local cmd=$2
    if command -v $cmd &> /dev/null || eval "$cmd --version" &> /dev/null; then
        echo -e "${GREEN}✅${NC} $tool"
        return 0
    else
        echo -e "${RED}❌${NC} $tool"
        return 1
    fi
}

echo ""
echo "Verification Results:"
echo "─────────────────────────────────────────────────"

verify_tool "SPIN" "spin"
verify_tool "Coq" "coqc"
verify_tool "Lean" "lean"
verify_tool "Rust" "rustc"
verify_tool "Cargo" "cargo"
verify_tool "Prusti" "prusti-rustc"
verify_tool "Kani" "cargo kani"
verify_tool "Creusot" "creusot"
verify_tool "Z3" "z3"
verify_tool "CVC5" "cvc5"
verify_tool "Graphviz" "dot"
verify_tool "Python" "python3"

echo "─────────────────────────────────────────────────"

# =============================================================================
# Final Instructions
# =============================================================================
log_step "Installation Complete!"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                         🛡️  INSTALLATION COMPLETE  🛡️                         ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}Next Steps:${NC}"
echo ""
echo "1. Source the environment file:"
echo -e "   ${YELLOW}source $ENV_FILE${NC}"
echo ""
echo "2. Copy the DeFi Guardian source files to:"
echo -e "   ${YELLOW}$PROJECT_DIR/${NC}"
echo ""
echo "3. Launch the application:"
echo -e "   ${YELLOW}cd $PROJECT_DIR && python3 desktop_app.py${NC}"
echo ""
echo "   Or use the desktop shortcut from your application menu."
echo ""
echo -e "${CYAN}Tool Versions Installed:${NC}"
echo "   • SPIN Model Checker: 6.5.2"
echo "   • Coq Theorem Prover: Latest via OPAM"
echo "   • Lean 4: Stable"
echo "   • Rust: Latest stable"
echo "   • Prusti, Kani, Creusot: Latest versions"
echo "   • Z3 & CVC5: Latest stable"
echo ""
echo -e "${CYAN}Important Paths:${NC}"
echo "   • Project Directory: $PROJECT_DIR"
echo "   • Environment File: $ENV_FILE"
echo "   • Creusot STD: $USER_HOME/creusot/creusot-std"
echo ""
echo -e "${YELLOW}Note: You may need to log out and back in for desktop entry to appear.${NC}"
echo ""

# Save installation log
LOG_FILE="$PROJECT_DIR/install_$(date +%Y%m%d_%H%M%S).log"
echo "Installation completed at $(date)" > "$LOG_FILE"
echo "Installation log saved to: $LOG_FILE"