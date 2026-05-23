"""
Unit tests for all trace parsers.
Tests verify that parsers correctly extract rules and traces from tool logs.
"""

import pytest
import os
from datetime import datetime
from events import LTLProperty, ExecutionTrace, TraceStep
from trace_parsers import get_parser
from trace_parsers.spin_parser import SPINParser
from trace_parsers.coq_parser import CoqParser
from trace_parsers.lean_parser import LeanParser
from trace_parsers.certora_parser import CertoraParser
from trace_parsers.rust_parser import RustParser
from trace_parsers.verus_parser import VerusParser


# ============================================================================
# SPIN Parser Tests
# ============================================================================


class TestSPINParser:
    @pytest.fixture
    def parser(self):
        return SPINParser()

    @pytest.fixture
    def spin_pass_log(self, tmp_path):
        log_file = tmp_path / "spin_pass.log"
        log_file.write_text(
            """
--- LTL safety_no_overflow ---
errors: 0

--- LTL safety_reentrancy ---
errors: 0

--- LTL liveness_progress ---
errors: 0
        """
        )
        return str(log_file)

    @pytest.fixture
    def spin_fail_log(self, tmp_path):
        log_file = tmp_path / "spin_fail.log"
        log_file.write_text(
            """
--- LTL safety_no_overflow ---
errors: 1

--- LTL reentrancy ---
errors: 2

1:  proc  0 (Contract) translated_output.pml:44 (state 10)  [amount=1000000]
2:  proc  0 (Contract) translated_output.pml:45 (state 11)  [lock=1]
        """
        )
        return str(log_file)

    def test_parse_rules_pass(self, parser, spin_pass_log):
        """Test parsing passing LTL properties"""
        rules = parser.parse_rules(spin_pass_log)
        assert len(rules) == 3
        assert rules[0]["name"] == "safety_no_overflow"
        assert rules[0]["status"] == "PASS"
        assert rules[0]["errors"] == 0

    def test_parse_rules_fail(self, parser, spin_fail_log):
        """Test parsing failing LTL properties"""
        rules = parser.parse_rules(spin_fail_log)
        assert len(rules) >= 2
        failing_rule = [r for r in rules if r["errors"] > 0][0]
        assert failing_rule["status"] == "FAIL"
        assert failing_rule["errors"] > 0

    def test_parse_trace_empty(self, parser, tmp_path):
        """Test empty trace file"""
        log_file = tmp_path / "empty.log"
        log_file.write_text("")
        trace = parser.parse_trace(str(log_file))
        assert isinstance(trace, ExecutionTrace)
        assert len(trace.steps) == 0

    def test_parse_trace_with_steps(self, parser, tmp_path):
        """Test parsing trace with execution steps"""
        log_file = tmp_path / "trace.log"
        log_file.write_text(
            """
0:  proc  0 (Contract) model.pml:10 (state 1)  [x=0]
1:  proc  0 (Contract) model.pml:11 (state 2)  [x=1]
2:  proc  0 (Contract) model.pml:12 (state 3)  [assert x < 100]
        """
        )
        trace = parser.parse_trace(str(log_file))
        assert len(trace.steps) >= 1
        assert trace.steps[0].proc == "Contract"

    def test_get_parser_factory(self):
        """Test factory method returns correct parser"""
        parser = get_parser("SPIN")
        assert isinstance(parser, SPINParser)


# ============================================================================
# Coq Parser Tests
# ============================================================================


class TestCoqParser:
    @pytest.fixture
    def parser(self):
        return CoqParser()

    @pytest.fixture
    def coq_pass_log(self, tmp_path):
        log_file = tmp_path / "coq_pass.log"
        log_file.write_text(
            """
Theorem safety_invariant: forall x, x >= 0 -> x >= 0.
Proof.
  intro. assumption.
Qed.

Lemma helper: 1 + 1 = 2.
Proof.
  reflexivity.
Defined.
        """
        )
        return str(log_file)

    @pytest.fixture
    def coq_fail_log(self, tmp_path):
        log_file = tmp_path / "coq_fail.log"
        log_file.write_text(
            """
Theorem broken_invariant: forall x, x = x + 1.
Proof.
  intro.
Admitted.

Error: The term "x" has type "nat" which is not less convertible to "nat".
        """
        )
        return str(log_file)

    def test_parse_rules_pass(self, parser, coq_pass_log):
        """Test parsing passing proofs"""
        rules = parser.parse_rules(coq_pass_log)
        assert len(rules) >= 1
        passing = [r for r in rules if r["status"] == "PASS"]
        assert len(passing) > 0

    def test_parse_rules_fail(self, parser, coq_fail_log):
        """Test parsing failed proofs"""
        rules = parser.parse_rules(coq_fail_log)
        assert len(rules) >= 1
        failing = [r for r in rules if r["status"] == "FAIL"]
        assert len(failing) > 0


# ============================================================================
# Lean Parser Tests
# ============================================================================


class TestLeanParser:
    @pytest.fixture
    def parser(self):
        return LeanParser()

    @pytest.fixture
    def lean_pass_log(self, tmp_path):
        log_file = tmp_path / "lean_pass.log"
        log_file.write_text(
            """
theorem test_safety: forall x : Nat, x >= 0 := by
  intro x
  omega
        """
        )
        return str(log_file)

    @pytest.fixture
    def lean_fail_log(self, tmp_path):
        log_file = tmp_path / "lean_fail.log"
        log_file.write_text(
            """
theorem broken: False := by
  exact absurd rfl

error[E-001]: Unknown identifier 'absurd'
        """
        )
        return str(log_file)

    def test_parse_rules_pass(self, parser, lean_pass_log):
        """Test parsing passing Lean theorems"""
        rules = parser.parse_rules(lean_pass_log)
        assert len(rules) >= 1

    def test_parse_rules_fail(self, parser, lean_fail_log):
        """Test parsing failed Lean theorems"""
        rules = parser.parse_rules(lean_fail_log)
        assert len(rules) >= 1
        # Should detect error
        has_error = any("error" in str(r).lower() for r in rules)
        assert has_error or any(r["status"] == "FAIL" for r in rules)


# ============================================================================
# Certora Parser Tests
# ============================================================================


class TestCertoraParser:
    @pytest.fixture
    def parser(self):
        return CertoraParser()

    @pytest.fixture
    def certora_pass_log(self, tmp_path):
        log_file = tmp_path / "certora_pass.log"
        log_file.write_text(
            """
Rule depositIsMonotonic: PASS
Rule balanceInvariant: PASS
Rule noReentrancy: PASS
        """
        )
        return str(log_file)

    @pytest.fixture
    def certora_fail_log(self, tmp_path):
        log_file = tmp_path / "certora_fail.log"
        log_file.write_text(
            """
Rule noReentrancy: FAIL
Rule invariantMaintenance: TIMEOUT
        """
        )
        return str(log_file)

    def test_parse_rules_pass(self, parser, certora_pass_log):
        """Test parsing passing Certora rules"""
        rules = parser.parse_rules(certora_pass_log)
        assert len(rules) >= 3
        assert all(r["status"] == "PASS" for r in rules)

    def test_parse_rules_fail(self, parser, certora_fail_log):
        """Test parsing failing Certora rules"""
        rules = parser.parse_rules(certora_fail_log)
        assert len(rules) >= 1
        failing = [r for r in rules if r["status"] in ["FAIL", "TIMEOUT"]]
        assert len(failing) > 0


# ============================================================================
# Rust Parser Tests (Kani, Prusti, Creusot)
# ============================================================================


class TestRustParser:
    @pytest.fixture
    def kani_parser(self):
        return RustParser("KANI")

    @pytest.fixture
    def prusti_parser(self):
        return RustParser("PRUSTI")

    @pytest.fixture
    def kani_pass_log(self, tmp_path):
        log_file = tmp_path / "kani_pass.log"
        log_file.write_text(
            """
check 1: array_bounds PASSED
check 2: arithmetic_overflow PASSED
        """
        )
        return str(log_file)

    @pytest.fixture
    def kani_fail_log(self, tmp_path):
        log_file = tmp_path / "kani_fail.log"
        log_file.write_text(
            """
check 1: array_bounds FAILED
panicked at 'attempt to add with overflow'
        """
        )
        return str(log_file)

    def test_kani_parse_rules_pass(self, kani_parser, kani_pass_log):
        """Test parsing passing Kani checks"""
        rules = kani_parser.parse_rules(kani_pass_log)
        assert len(rules) >= 1

    def test_kani_parse_rules_fail(self, kani_parser, kani_fail_log):
        """Test parsing failing Kani checks"""
        rules = kani_parser.parse_rules(kani_fail_log)
        assert len(rules) >= 1


# ============================================================================
# Verus Parser Tests
# ============================================================================


class TestVerusParser:
    @pytest.fixture
    def parser(self):
        return VerusParser()

    @pytest.fixture
    def verus_log(self, tmp_path):
        log_file = tmp_path / "verus.log"
        log_file.write_text(
            """
proof test_safety verified
proof test_overflow verified
        """
        )
        return str(log_file)

    def test_parse_rules(self, parser, verus_log):
        """Test parsing Verus proofs"""
        rules = parser.parse_rules(verus_log)
        assert len(rules) >= 1


# ============================================================================
# Integration Tests
# ============================================================================


class TestParserIntegration:
    def test_all_parsers_importable(self):
        """Test that all parsers can be imported"""
        tools = ["SPIN", "COQ", "LEAN", "CERTORA", "KANI", "PRUSTI", "CREUSOT", "VERUS"]
        for tool in tools:
            parser = get_parser(tool)
            assert parser is not None
            assert hasattr(parser, "parse_rules")
            assert hasattr(parser, "parse_trace")

    def test_parser_returns_consistent_format(self):
        """Test that all parsers return consistent rule format"""
        parser = SPINParser()
        # Rules should have keys: name, status, formula, errors, tool_specific
        tmp_path = "/tmp"
        empty_log = "/tmp/empty_test.log"
        open(empty_log, "w").close()

        rules = parser.parse_rules(empty_log)
        # Even for empty, we should get fallback rules
        if rules:
            for rule in rules:
                assert "name" in rule
                assert "status" in rule
                assert "formula" in rule
                assert "errors" in rule

        os.remove(empty_log)
