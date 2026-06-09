import streamlit as st
import pandas as pd
import plotly.express as px
from core.audit_engine import ProfessionalAuditEngine
import sys
import os

# Add parent directory to path to allow importing from defi-guardian root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

st.set_page_config(page_title="Analytics Suite | DeFi Guardian", layout="wide", page_icon="🛡️")

def load_dummy_data():
    return {
        "states_explored": 1450394,
        "estimated_state_space": 1500000,
        "violations": [
            {"property": "No Reentrancy in withdraw()", "type": "reentrancy", "depth": 14, "description": "State variable updated after external call."}
        ]
    }

def render_dashboard():
    st.title("🛡️ Professional Formal Verification Analytics")
    st.markdown("---")
    
    # Initialize Core Audit Engine
    data = load_dummy_data()
    engine = ProfessionalAuditEngine(data)
    summary = engine.generate_audit_summary()
    
    # --- Top Level Metrics ---
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(label="Security Score", value=f"{summary['security_score']}/100", delta="-15" if summary['security_score'] < 100 else "0")
    with col2:
        st.metric(label="Audit Grade", value=summary['audit_grade'])
    with col3:
        st.metric(label="State Coverage", value=f"{summary['coverage']['coverage_percentage']}%")
    with col4:
        st.metric(label="Critical Issues", value=summary['critical_issues'], delta_color="inverse")
        
    st.markdown("---")
    
    # --- Detailed Analysis ---
    tab1, tab2, tab3 = st.tabs(["📊 State Space Profiling", "🐛 Vulnerability Matrix", "📑 Executive Report"])
    
    with tab1:
        st.subheader("State Space Exploration Profiling")
        # Example Plotly chart representing state discovery over time
        df = pd.DataFrame({
            "Time (s)": range(1, 11),
            "States Explored": [1000, 5000, 20000, 55000, 120000, 300000, 600000, 950000, 1300000, 1450394]
        })
        fig = px.area(df, x="Time (s)", y="States Explored", title="Verification State Explosion Curve")
        st.plotly_chart(fig, use_container_width=True)
        
    with tab2:
        st.subheader("Detected Invariant Violations")
        violations = engine.analyze_invariant_violations()
        if not violations:
            st.success("No violations detected. Smart contract meets formal specifications.")
        else:
            for v in violations:
                with st.expander(f"[{v['severity']}] {v['property']} (Depth: {v['trace_length']})"):
                    st.write(f"**Description:** {v['description']}")
                    st.write("**Remediation:** Review state transitions ensuring invariants hold across atomic boundaries.")
                    st.button("Replay Counterexample Trace", key=f"replay_{v['property']}")
                    
    with tab3:
        st.subheader("Final Audit Status")
        if summary['is_safe_to_deploy']:
            st.success("✅ Certified Safe for Mainnet Deployment")
        else:
            st.error("❌ NOT Safe for Deployment. Resolve Critical/High vulnerabilities first.")
            
        st.button("Download Institutional PDF Report")

if __name__ == "__main__":
    render_dashboard()
