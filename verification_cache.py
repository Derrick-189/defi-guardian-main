import os
import json
import hashlib

class VerificationCache: 
    """Cache verification results to avoid recomputation""" 
    
    def __init__(self, cache_dir=".verification_cache"): 
        self.cache_dir = cache_dir 
        os.makedirs(cache_dir, exist_ok=True) 
    
    def get_key(self, source_code, tool): 
        """Generate a unique SHA-256 hash for code + tool combination"""
        content = source_code + str(tool) 
        return hashlib.sha256(content.encode()).hexdigest() 
    
    def get(self, source_code, tool): 
        """Retrieve cached result if it exists"""
        key = self.get_key(source_code, tool) 
        cache_file = os.path.join(self.cache_dir, f"{key}.json") 
        
        if os.path.exists(cache_file): 
            try:
                with open(cache_file, 'r') as f: 
                    result = json.load(f)
                    result['cached'] = True
                    return result
            except (json.JSONDecodeError, OSError):
                return None
        return None 
    
    def set(self, source_code, tool, result): 
        """Store result in cache"""
        key = self.get_key(source_code, tool) 
        cache_file = os.path.join(self.cache_dir, f"{key}.json") 
        
        try:
            with open(cache_file, 'w') as f: 
                json.dump(result, f, indent=2)
        except OSError:
            pass
