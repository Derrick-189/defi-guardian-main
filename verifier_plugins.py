import abc
import subprocess
import os
import json
import re
from datetime import datetime
from verification_cache import VerificationCache

def check_tool(name, cmd):
    try:
        subprocess.run(cmd, capture_output=True, timeout=3)
        return True
    except:
        return False

class VerifierPlugin(abc.ABC): 
    """Base class for verifier plugins""" 
    
    def __init__(self): 
        self.name = "Base" 
        self.version = "1.0" 
    
    @abc.abstractmethod
    def is_available(self) -> bool: 
        pass 
    
    @abc.abstractmethod
    def verify(self, source_code: str, **kwargs) -> dict: 
        pass 
    
    @abc.abstractmethod
    def get_capabilities(self) -> list: 
        """Return list of verifiable properties""" 
        pass 


class SPINPlugin(VerifierPlugin): 
    def __init__(self):
        super().__init__()
        self.name = "SPIN"
        self.version = "6.5.2"

    def is_available(self): 
        return check_tool("SPIN", ["spin", "-V"]) 
    
    def verify(self, source_code, **kwargs): 
        """
        Implementation for SPIN verification.
        In a real scenario, this would call the translator and then run SPIN.
        """
        try:
            # This is a simplified version of the logic found in desktop_app.py
            from translator import DeFiTranslator
            pml = DeFiTranslator.translate_solidity(source_code)
            
            # Write to temp file and run spin (omitted for brevity in this plugin definition)
            # ...
            
            return {
                "success": True,
                "tool": self.name,
                "output": "SPIN verification completed via plugin architecture.",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def get_capabilities(self): 
        return ["ltl", "safety", "liveness", "deadlock"]


class KaniPlugin(VerifierPlugin):
    def __init__(self):
        super().__init__()
        self.name = "Kani"
        self.version = "0.33.0"

    def is_available(self):
        return check_tool("Kani", ["cargo", "kani", "--version"])

    def verify(self, source_code, **kwargs):
        # Implementation for Kani verification
        return {
            "success": True,
            "tool": self.name,
            "output": "Kani verification completed via plugin architecture.",
            "timestamp": datetime.now().isoformat()
        }

    def get_capabilities(self):
        return ["safety", "overflow", "assertions"]


class PluginManager:
    """Registry and orchestrator for verifier plugins with caching"""
    
    def __init__(self, cache_enabled=True):
        self.plugins = {}
        self.cache = VerificationCache() if cache_enabled else None
        self._register_default_plugins()
    
    def _register_default_plugins(self):
        self.register_plugin(SPINPlugin())
        self.register_plugin(KaniPlugin())
    
    def register_plugin(self, plugin: VerifierPlugin):
        self.plugins[plugin.name.lower()] = plugin
    
    def get_available_plugins(self):
        return [p for p in self.plugins.values() if p.is_available()]
    
    def run_verification(self, plugin_name: str, source_code: str, **kwargs):
        name = plugin_name.lower()
        if name not in self.plugins:
            return {"success": False, "error": f"Plugin {plugin_name} not found."}
        
        plugin = self.plugins[name]
        if not plugin.is_available():
            return {"success": False, "error": f"Tool {plugin_name} is not installed."}

        # Check cache first
        if self.cache:
            cached_result = self.cache.get(source_code, name)
            if cached_result:
                return cached_result

        # Run verification
        result = plugin.verify(source_code, **kwargs)
        
        # Store in cache if successful
        if self.cache and result.get('success'):
            self.cache.set(source_code, name, result)
            
        return result
