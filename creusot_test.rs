//! Creusot verification example
//! Run: creusot creusot_test.rs

// A simple function to verify
fn max(x: u64, y: u64) -> u64 {
    if x > y { x } else { y }
}

// Verification harness
#[cfg(creusot)]
#[requires(true)]
#[ensures(result >= x && result >= y)]
#[ensures(result == x || result == y)]
fn verified_max(x: u64, y: u64) -> u64 {
    max(x, y)
}

// Another example with addition
fn add(x: u64, y: u64) -> u64 {
    x + y
}

#[cfg(creusot)]
#[requires(true)]
#[ensures(result == x + y)]
fn verified_add(x: u64, y: u64) -> u64 {
    add(x, y)
}

fn main() {
    println!("Creusot verification ready!");
    println!("Test with: creusot creusot_test.rs");
}
