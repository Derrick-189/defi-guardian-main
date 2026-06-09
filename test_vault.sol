// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract SimpleVault {
    mapping(address => uint256) public balances;
    uint256 public totalVaultBalance = 1000;

    function withdraw(uint256 amount) public {
        require(balances[msg.sender] >= amount);
        
        // Potential Re-entrancy point
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success);
        
        balances[msg.sender] -= amount;
    }
}