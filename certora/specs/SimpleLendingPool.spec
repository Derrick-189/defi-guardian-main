/*
 * ============================================================
 * CERTORA SPECIFICATION: SimpleLendingPool
 * ============================================================
 * 
 * These rules are checked against the ACTUAL EVM bytecode.
 * Certora's symbolic execution explores ALL possible states.
 */

methods {
    // Declare external functions for symbolic execution
    function deposits(address) external returns (uint256) envfree;
    function borrows(address) external returns (uint256) envfree;
    function totalDeposits() external returns (uint256) envfree;
    function totalBorrows() external returns (uint256) envfree;
    function getHealthFactor(address) external returns (uint256) envfree;
    function COLLATERAL_RATIO() external returns (uint256) envfree;
    function LIQUIDATION_BONUS() external returns (uint256) envfree;
}

// ─── INVARIANT 1: Solvency ───
// Pool must never owe more than it has
rule solvencyInvariant(method f) {
    uint256 totalDepBefore = totalDeposits();
    uint256 totalBorBefore = totalBorrows();
    
    // Call ANY function with ANY arguments
    calldataarg args;
    f(e, args);
    
    uint256 totalDepAfter = totalDeposits();
    uint256 totalBorAfter = totalBorrows();
    
    assert totalDepAfter >= totalBorAfter,
        "SOLVENCY VIOLATED: pool owes more than it has";
}

// ─── INVARIANT 2: No Under-Collateralized Borrows ───
rule borrowCollateralCheck(address user, uint256 amount) {
    require user != 0;
    require amount > 0;
    
    uint256 depositBefore = deposits(user);
    uint256 borrowBefore = borrows(user);
    uint256 ratio = COLLATERAL_RATIO();
    
    // Try to borrow
    borrow@withrevert(e, amount);
    
    if (!lastReverted) {
        uint256 borrowAfter = borrows(user);
        uint256 depositAfter = deposits(user);
        
        // After successful borrow, must have sufficient collateral
        uint256 requiredCollateral = (borrowAfter * ratio) / 100;
        assert depositAfter >= requiredCollateral,
            "COLLATERAL VIOLATION: Position underwater after borrow";
    }
}

// ─── INVARIANT 3: Liquidation Only When Underwater ───
rule liquidationCheck(address user, address liquidator, uint256 debtToCover) {
    require user != liquidator;
    require user != 0;
    require liquidator != 0;
    require borrows(user) > 0;
    
    uint256 hfBefore = getHealthFactor(user);
    
    liquidate@withrevert(e, user, debtToCover);
    
    if (!lastReverted) {
        // Liquidation succeeded → position was underwater
        assert hfBefore < 100,
            "LIQUIDATION VIOLATION: Liquidated healthy position";
    }
}

// ─── INVARIANT 4: Deposit Correctness ───
rule depositCorrect(address user, uint256 amount) {
    require amount > 0;
    require user != 0;
    
    uint256 depositBefore = deposits(user);
    uint256 totalBefore = totalDeposits();
    
    deposit@withrevert(e, amount);
    
    if (!lastReverted) {
        uint256 depositAfter = deposits(user);
        uint256 totalAfter = totalDeposits();
        
        assert depositAfter == depositBefore + amount,
            "DEPOSIT ERROR: User balance not updated correctly";
        assert totalAfter == totalBefore + amount,
            "DEPOSIT ERROR: Total deposits not updated";
    }
}

// ─── INVARIANT 5: Repay Reduces Debt ───
rule repayCorrect(address user, uint256 amount) {
    require amount > 0;
    require user != 0;
    require borrows(user) >= amount;
    
    uint256 borrowBefore = borrows(user);
    uint256 totalBorBefore = totalBorrows();
    
    repay@withrevert(e, amount);
    
    if (!lastReverted) {
        uint256 borrowAfter = borrows(user);
        uint256 totalBorAfter = totalBorrows();
        
        assert borrowAfter == borrowBefore - amount,
            "REPAY ERROR: User debt not reduced correctly";
        assert totalBorAfter == totalBorBefore - amount,
            "REPAY ERROR: Total borrows not reduced";
    }
}

// ─── INVARIANT 6: Liquidation Transfers Collateral ───
rule liquidationTransferCorrect(
    address user, 
    address liquidator, 
    uint256 debtToCover
) {
    require user != liquidator;
    require user != 0;
    require liquidator != 0;
    require borrows(user) > 0;
    require debtToCover <= borrows(user);
    
    uint256 collatUserBefore = deposits(user);
    uint256 collatLiqBefore = deposits(liquidator);
    uint256 debtBefore = borrows(user);
    
    liquidate@withrevert(e, user, debtToCover);
    
    if (!lastReverted) {
        uint256 collatUserAfter = deposits(user);
        uint256 collatLiqAfter = deposits(liquidator);
        uint256 debtAfter = borrows(user);
        
        // User loses collateral
        assert collatUserAfter < collatUserBefore,
            "LIQUIDATION ERROR: User collateral not reduced";
        
        // Liquidator gains collateral
        assert collatLiqAfter > collatLiqBefore,
            "LIQUIDATION ERROR: Liquidator not compensated";
        
        // Debt is reduced
        assert debtAfter < debtBefore,
            "LIQUIDATION ERROR: Debt not reduced";
    }
}