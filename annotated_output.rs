#![feature(register_tool)]
#![register_tool(creusot)]

// user_lending.rs
pub struct DynamicLendingPool {
    pub total_deposits: u64,
    pub total_borrows: u64,
    pub base_rate: u64,        // 5% base rate
    pub slope1: u64,           // 10% slope for low utilization
    pub slope2: u64,           // 30% slope for high utilization
    pub optimal_utilization: u64, // 80% target
}

impl DynamicLendingPool {
    pub fn calculate_borrow_rate(&self) -> u64 {
        let utilization = if self.total_deposits == 0 {
            0
        } else {
            (self.total_borrows * 10000) / self.total_deposits  // basis points
        };
        
        if utilization <= self.optimal_utilization {
            self.base_rate + (self.slope1 * utilization) / 10000
        } else {
            let excess = utilization - self.optimal_utilization;
            self.base_rate + (self.slope1 * self.optimal_utilization) / 10000
                + (self.slope2 * excess) / 10000
        }
    }
}