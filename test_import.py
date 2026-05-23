import sys
import os

# Add the project directory to sys.path
PROJECT_DIR = "/home/slade/defi_guardian"
sys.path.insert(0, PROJECT_DIR)

try:
    from translator import DeFiTranslator
    print(f"Successfully imported DeFiTranslator from translator.py")
    print(f"Has translate_rust: {hasattr(DeFiTranslator, 'translate_rust')}")
    if hasattr(DeFiTranslator, 'translate_rust'):
        print(f"translate_rust type: {type(DeFiTranslator.translate_rust)}")
except ImportError as e:
    print(f"ImportError: {e}")
except Exception as e:
    print(f"An error occurred: {e}")
