function withdraw(uint256 amount) public {
    require(amount <= balance, "Insufficient funds"); // LINE TO ADD
    balance = balance - amount;
}