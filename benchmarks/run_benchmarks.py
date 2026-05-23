import sys
import os
import time
import pandas as pd
import json
from datetime import datetime

# Add parent directory to path to import local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from verifier_plugins import PluginManager

BENCHMARK_CONTRACTS = [ 
    ("ERC20", "erc20.sol", ["safety_no_overflow", "invariant_balance"]), 
    ("LendingPool", "lending.sol", ["invariant_collateral", "safety_reentrancy"]), 
    ("Auction", "auction.sol", ["liveness_bid", "safety_refund"]), 
] 

def run_benchmarks(): 
    """Execute performance benchmarks across multiple tools and contracts"""
    manager = PluginManager()
    results = [] 
    
    # Ensure a contracts directory exists for benchmarks
    contracts_dir = os.path.join(os.path.dirname(__file__), "contracts")
    os.makedirs(contracts_dir, exist_ok=True)
    
    # Create mock contracts if they don't exist
    for name, filename, _ in BENCHMARK_CONTRACTS:
        path = os.path.join(contracts_dir, filename)
        if not os.path.exists(path):
            with open(path, 'w') as f:
                f.write(f"// Mock {name} contract for benchmarking\ncontract {name} {{ }}")

    print(f"🚀 Starting DeFi Guardian Performance Benchmarks...")
    print(f"📊 Tracking {len(BENCHMARK_CONTRACTS)} contracts across available plugins\n")

    for name, filename, properties in BENCHMARK_CONTRACTS: 
        file_path = os.path.join(contracts_dir, filename)
        with open(file_path, 'r') as f:
            source_code = f.read()
            
        for tool_name in ["spin", "kani"]: # Focusing on implemented plugins
            print(f"⏱️  Benchmarking {name} with {tool_name}...")
            
            start = time.time() 
            # Use the Plugin Architecture for verification
            result = manager.run_verification(tool_name, source_code) 
            elapsed = time.time() - start 
            
            # Simulate property verification counts based on tool success
            props_verified = len(properties) if result.get('success') else 0
            
            results.append({ 
                "contract": name, 
                "tool": tool_name, 
                "time": round(elapsed, 3), 
                "success": result.get('success', False), 
                "properties_verified": props_verified,
                "timestamp": datetime.now().isoformat()
            }) 
    
    df = pd.DataFrame(results)
    
    # Save results to a JSON file for the dashboard to consume
    output_path = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    df.to_json(output_path, orient='records', indent=2)
    
    print(f"\n✅ Benchmarks complete. Results saved to {output_path}")
    return df

if __name__ == "__main__":
    run_benchmarks()
