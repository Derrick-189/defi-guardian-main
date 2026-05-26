import time
import json
import os
import sys
from pathlib import Path
from datetime import datetime
from threading import Thread

# Add parent directory to path to import local modules
PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from verifier_plugins import PluginManager

BENCHMARK_CONTRACTS = [ 
    ("ERC20", "erc20.sol"), 
    ("LendingPool", "lending.sol"), 
    ("Auction", "auction.sol"), 
] 

class BenchmarkRunner:
    def __init__(self, socketio):
        self.socketio = socketio
        self.manager = PluginManager()
        self.results_file = PROJECT_DIR / "benchmarks" / "benchmark_results.json"
        self.is_running = False

    def emit(self, event, data):
        self.socketio.emit(event, data)

    def run_all(self):
        if self.is_running:
            return
        
        self.is_running = True
        Thread(target=self._run_internal).start()

    def _run_internal(self):
        try:
            self.emit('benchmark_start', {'status': 'Started', 'total': len(BENCHMARK_CONTRACTS) * 2})
            
            contracts_dir = PROJECT_DIR / "benchmarks" / "contracts"
            contracts_dir.mkdir(parents=True, exist_ok=True)
            
            new_results = []
            
            for name, filename in BENCHMARK_CONTRACTS:
                path = contracts_dir / filename
                if not path.exists():
                    with open(path, 'w') as f:
                        f.write(f"// Mock {name} contract for benchmarking\ncontract {name} {{ }}")
                
                source_code = path.read_text()
                
                for tool_name in ["spin", "kani"]:
                    self.emit('benchmark_update', {
                        'status': 'Running',
                        'tool': tool_name.upper(),
                        'contract': name,
                        'message': f"Benchmarking {name} with {tool_name.upper()}..."
                    })
                    
                    start = time.time()
                    try:
                        # Use simulation mode if binaries are missing
                        # In a real scenario, this would call actual verification
                        result = self.manager.run_verification(tool_name, source_code)
                        elapsed = time.time() - start
                        
                        passed = not result.get("counterexample_found", False)
                        
                        entry = {
                            "tool": tool_name.upper(),
                            "contract": name,
                            "filename": filename,
                            "time": round(elapsed, 4),
                            "time_seconds": round(elapsed, 4),
                            "success": passed,
                            "passed": passed,
                            "pass_rate": 100 if passed else 0,
                            "success_rate": 100 if passed else 0,
                            "states": result.get("states_stored", 0),
                            "transitions": result.get("transitions", 0),
                            "depth": result.get("depth", 0),
                            "timestamp": datetime.now().isoformat(),
                            "date": datetime.now().strftime("%Y-%m-%dT%H:%M")
                        }
                        new_results.append(entry)
                        
                        self.emit('benchmark_step_complete', entry)
                        
                    except Exception as e:
                        self.emit('benchmark_update', {
                            'status': 'Error',
                            'tool': tool_name.upper(),
                            'contract': name,
                            'message': f"Error: {str(e)}"
                        })

            # Save results
            existing = []
            if self.results_file.exists():
                try:
                    existing = json.loads(self.results_file.read_text())
                except:
                    pass
            
            # Keep last 100 results
            combined = (new_results + existing)[:100]
            self.results_file.write_text(json.dumps(combined, indent=2))
            
            self.emit('benchmark_complete', {
                'status': 'Completed',
                'results_count': len(new_results)
            })
            
        finally:
            self.is_running = False

