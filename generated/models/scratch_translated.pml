function withdraw(uint256 amount) public {
    // BUG: No check if amount <= balance
    balance = balance - amount; 
}
