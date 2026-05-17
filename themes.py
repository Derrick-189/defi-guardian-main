# themes.py - Complete theme system 
class DeFiThemes: 
    """Professional theme collection for DeFi Guardian""" 
    
    @staticmethod 
    def get_theme(theme_name): 
        themes = { 
            "cyber": { 
                "primary": "#00ffcc", 
                "secondary": "#ff00ff", 
                "background": "#0a0a0f", 
                "surface": "#13131a", 
                "error": "#ff0055", 
                "success": "#00ff88", 
                "warning": "#ffaa00", 
                "text_primary": "#ffffff", 
                "text_secondary": "#b0b0b0", 
                "border": "#2a2a3a", 
            }, 
            "corporate": { 
                "primary": "#2563eb", 
                "secondary": "#7c3aed", 
                "background": "#f8fafc", 
                "surface": "#ffffff", 
                "error": "#dc2626", 
                "success": "#16a34a", 
                "warning": "#ea580c", 
                "text_primary": "#1e293b", 
                "text_secondary": "#64748b", 
                "border": "#e2e8f0", 
            }, 
            "minimal": { 
                "primary": "#000000", 
                "secondary": "#666666", 
                "background": "#ffffff", 
                "surface": "#f5f5f5", 
                "error": "#cc0000", 
                "success": "#00cc00", 
                "warning": "#ccaa00", 
                "text_primary": "#000000", 
                "text_secondary": "#666666", 
                "border": "#dddddd", 
            } 
        } 
        return themes.get(theme_name, themes["cyber"]) 
    
    @staticmethod 
    def apply_streamlit_theme(theme): 
        """Generate CSS for Streamlit theme""" 
        return f""" 
        <style> 
            .stApp {{ 
                background: {theme['background']}; 
            }} 
            
            .stButton > button {{ 
                background: {theme['primary']}; 
                color: {theme['text_primary']}; 
                border: none; 
                border-radius: 8px; 
                padding: 0.5rem 1rem; 
                font-weight: 600; 
                transition: all 0.2s ease; 
            }} 
            
            .stButton > button:hover {{ 
                background: {theme['secondary']}; 
                transform: translateY(-2px); 
                box-shadow: 0 4px 12px {theme['primary']}40; 
            }} 
            
            .metric-card {{ 
                background: {theme['surface']}; 
                border: 1px solid {theme['border']}; 
                border-radius: 12px; 
                padding: 1.5rem; 
            }} 
            
            .metric-value {{ 
                color: {theme['primary']}; 
                font-size: 2rem; 
                font-weight: bold; 
            }} 
            
            .metric-label {{ 
                color: {theme['text_secondary']}; 
                font-size: 0.875rem; 
            }} 
        </style> 
        """ 
