// test_contract.rs — Example Anchor lending pool for DeFi Guardian / verification testing
// Requires a full Anchor workspace (Cargo.toml + lib.rs entry) to compile with `anchor build`.

use anchor_lang::prelude::*;

declare_id!("4nTqA9yqL8i5N8xK2vR3mP7wQ1jF6hD0cB9sZ4eY8uA");

#[program]
pub mod lending_pool {
    use super::*;

    pub fn deposit(ctx: Context<Deposit>, amount: u64) -> Result<()> {
        let account = &mut ctx.accounts.user_account;
        account.balance = account.balance.checked_add(amount).unwrap();
        Ok(())
    }

    pub fn borrow(ctx: Context<Borrow>, amount: u64) -> Result<()> {
        let account = &mut ctx.accounts.user_account;

        // Invariant: must have sufficient collateral (value covers existing + new debt)
        require!(
            account.collateral * account.price >= account.debt + amount,
            ErrorCode::InsufficientCollateral
        );

        account.debt = account.debt.checked_add(amount).unwrap();
        Ok(())
    }
}

#[derive(Accounts)]
pub struct Deposit<'info> {
    #[account(mut)]
    pub user_account: Account<'info, UserAccount>,
}

#[derive(Accounts)]
pub struct Borrow<'info> {
    #[account(mut)]
    pub user_account: Account<'info, UserAccount>,
}

#[account]
pub struct UserAccount {
    pub balance: u64,
    pub collateral: u64,
    pub debt: u64,
    pub price: u64,
}

#[error_code]
pub enum ErrorCode {
    #[msg("Insufficient collateral for borrow")]
    InsufficientCollateral,
}
