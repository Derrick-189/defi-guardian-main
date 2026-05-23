import sys
import os

# Add the project directory to sys.path
PROJECT_DIR = "/home/slade/defi_guardian"
sys.path.insert(0, PROJECT_DIR)

try:
    from translator import DeFiTranslator
    print(f"Successfully imported DeFiTranslator from translator.py")
    
    source = """
    fn main() {
        let mut balance = 100;
        balance -= 10;
    }
    """
    
    if hasattr(DeFiTranslator, 'translate_rust'):
        print("DeFiTranslator HAS translate_rust attribute.")
        pml = DeFiTranslator.translate_rust(source)
        print("Translation successful!")
        print("PML Output preview:")
        print(pml[:100] + "...")
    else:
        print("DeFiTranslator MISSING translate_rust attribute.")
        
except Exception as e:
    print(f"An error occurred: {e}")
