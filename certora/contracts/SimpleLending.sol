// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

/**
 * @title Simple DeFi Lending Protocol
 * @dev A basic lending contract for demonstration of formal verification
 * @notice This contract demonstrates common DeFi patterns that need verification
 */
contract SimpleLending {
    // State variables
    mapping(address => uint256) public balances;
    mapping(address => uint256) public debts;
    uint256 public totalSupply;
    uint256 public totalBorrowed;
    address public owner;
    bool public paused;

    // Events
    event Deposit(address indexed user, uint256 amount);
    event Withdraw(address indexed user, uint256 amount);
    event Borrow(address indexed user, uint256 amount);
    event Repay(address indexed user, uint256 amount);

    // Modifiers
    modifier onlyOwner() {
        require(msg.sender == owner, "Only owner can call this");
        _;
    }

    modifier notPaused() {
        require(!paused, "Contract is paused");
        _;
    }

    modifier validAmount(uint256 amount) {
        require(amount > 0, "Amount must be greater than 0");
        _;
    }

    constructor() {
        owner = msg.sender;
        paused = false;
    }

    /**
     * @dev Deposit tokens into the lending pool
     * @param amount Amount of tokens to deposit
     */
    function deposit(uint256 amount)
        external
        notPaused
        validAmount(amount)
    {
        balances[msg.sender] += amount;
        totalSupply += amount;

        emit Deposit(msg.sender, amount);
    }

    /**
     * @dev Withdraw tokens from the lending pool
     * @param amount Amount of tokens to withdraw
     */
    function withdraw(uint256 amount)
        external
        notPaused
        validAmount(amount)
    {
        require(balances[msg.sender] >= amount, "Insufficient balance");

        balances[msg.sender] -= amount;
        totalSupply -= amount;

        emit Withdraw(msg.sender, amount);
    }

    /**
     * @dev Borrow tokens from the pool
     * @param amount Amount of tokens to borrow
     */
    function borrow(uint256 amount)
        external
        notPaused
        validAmount(amount)
    {
        require(totalSupply >= totalBorrowed + amount, "Insufficient liquidity");

        debts[msg.sender] += amount;
        totalBorrowed += amount;

        emit Borrow(msg.sender, amount);
    }

    /**
     * @dev Repay borrowed tokens
     * @param amount Amount of tokens to repay
     */
    function repay(uint256 amount)
        external
        notPaused
        validAmount(amount)
    {
        require(debts[msg.sender] >= amount, "Repay amount exceeds debt");

        debts[msg.sender] -= amount;
        totalBorrowed -= amount;

        emit Repay(msg.sender, amount);
    }

    /**
     * @dev Get user's collateral ratio
     * @param user Address of the user
     * @return Collateral ratio (basis points)
     */
    function getCollateralRatio(address user) external view returns (uint256) {
        if (debts[user] == 0) return 0;

        // Simplified: assume 150% collateral requirement
        uint256 requiredCollateral = (debts[user] * 150) / 100;
        uint256 userCollateral = balances[user];

        if (userCollateral >= requiredCollateral) {
            return (userCollateral * 10000) / debts[user]; // Return in basis points
        } else {
            return 0; // Under-collateralized
        }
    }

    /**
     * @dev Emergency pause function
     */
    function pause() external onlyOwner {
        paused = true;
    }

    /**
     * @dev Resume operations
     */
    function unpause() external onlyOwner {
        paused = false;
    }

    /**
     * @dev Get contract health status
     * @return Health factor (0 = insolvent, >100 = healthy)
     */
    function getHealthFactor() external view returns (uint256) {
        if (totalBorrowed == 0) return 10000; // Max health when no debt

        // Simplified health calculation
        if (totalSupply >= totalBorrowed) {
            return (totalSupply * 10000) / totalBorrowed;
        } else {
            return 0; // Insolvent
        }
    }
}