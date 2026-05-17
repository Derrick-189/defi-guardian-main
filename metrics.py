# metrics.py - New file
import json
import os
from datetime import datetime

class VerificationMetrics:
    def __init__(self, state_file="verification_state.json"):
        self.state_file = state_file
        self.metrics = self.load_metrics()
    
    def load_metrics(self):
        """Load metrics from verification state"""
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r') as f:
                data = json.load(f)
                return {
                    'total_properties': len(data.get('ltl_results', [])),
                    'verified_properties': sum(1 for _ in data.get('ltl_results', [])),
                    'failed_properties': 0,
                    'verification_time': data.get('verification_time', 0),
                    'states_explored': data.get('states_stored', 0),
                    'proof_depth': data.get('depth', 0),
                    'success': data.get('success', False)
                }
        return self.default_metrics()
    
    def default_metrics(self):
        return {
            'total_properties': 0,
            'verified_properties': 0,
            'failed_properties': 0,
            'verification_time': 0,
            'states_explored': 0,
            'proof_depth': 0,
            'success': False
        }
    
    def compute_score(self):
        """Compute overall verification score (0-100)"""
        if self.metrics['total_properties'] == 0:
            return 0 if not self.metrics['success'] else 50
        
        verification_rate = self.metrics['verified_properties'] / self.metrics['total_properties']
        score = verification_rate * 100
        
        if self.metrics['success']:
            score += 10
        
        score -= self.metrics['failed_properties'] * 5
        
        return max(0, min(100, score))
    
    def generate_report(self):
        """Generate detailed verification report"""
        score = self.compute_score()
        grade = "A+" if score >= 95 else "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 50 else "F"
        
        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║                    FORMAL VERIFICATION SCORECARD                 ║
║                      DeFi Guardian Suite                         ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  📊 VERIFICATION METRICS                                         ║
║  ────────────────────────────────────────────────────────────── ║
║  Total Properties:      {self.metrics['total_properties']:>6}                                   ║
║  Verified:              {self.metrics['verified_properties']:>6} ✅                              ║
║  Failed:                {self.metrics['failed_properties']:>6} ❌                              ║
║                                                                  ║
║  ⏱️ PERFORMANCE                                                  ║
║  ────────────────────────────────────────────────────────────── ║
║  Verification Time:     {self.metrics['verification_time']:>6.2f}s                               ║
║  States Explored:       {self.metrics['states_explored']:>6}                                   ║
║  Proof Depth:           {self.metrics['proof_depth']:>6}                                   ║
║                                                                  ║
║  🎯 FINAL SCORE:        {score:>6.1f}/100  Grade: {grade}                                     ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""
        return report
    
    def save_report(self, filename="verification_report.txt"):
        """Save report to file"""
        with open(filename, 'w') as f:
            f.write(self.generate_report())
        return filename

# Integration for Streamlit dashboard - add to app.py
def display_metrics_dashboard():
    """Display metrics in Streamlit"""
    from metrics import VerificationMetrics
    metrics = VerificationMetrics()
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Total Properties", metrics.metrics['total_properties'])
    with col2:
        st.metric("Verified", metrics.metrics['verified_properties'], delta="✅")
    with col3:
        st.metric("States Explored", metrics.metrics['states_explored'])
    with col4:
        st.metric("Score", f"{metrics.compute_score():.0f}/100")