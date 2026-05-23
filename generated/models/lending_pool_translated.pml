/* Simple lending pool model */
#define DEPOSIT 1
#define WITHDRAW 2
#define BORROW 3
#define REPAY 4

/* User accounts */
typedef Account {
    int balance;
    int debt;
}

/* Lending pool */
byte total_liquidity = 1000;
Account users[2];  /* Two users: 0 and 1 */

/* Initialize */
init {
    atomic {
        users[0].balance = 100;
        users[1].balance = 100;
    }
    
    /* Run user processes */
    run User(0);
    run User(1);
}

/* User process */
proctype User(byte id) {
    int action;
    
    do
    :: action = DEPOSIT ->
        if
        :: users[id].balance > 0 ->
            atomic {
                users[id].balance = users[id].balance - 10;
                total_liquidity = total_liquidity + 10;
            }
        :: else -> skip
        fi
        
    :: action = WITHDRAW ->
        if
        :: total_liquidity >= 10 ->
            atomic {
                total_liquidity = total_liquidity - 10;
                users[id].balance = users[id].balance + 10;
            }
        :: else -> skip
        fi
        
    :: action = BORROW ->
        if
        :: total_liquidity >= 50 ->
            atomic {
                total_liquidity = total_liquidity - 50;
                users[id].debt = users[id].debt + 50;
            }
        :: else -> skip
        fi
        
    :: action = REPAY ->
        if
        :: users[id].debt > 0 && users[id].balance >= 55 ->
            atomic {
                users[id].balance = users[id].balance - 55;
                users[id].debt = users[id].debt - 50;
                total_liquidity = total_liquidity + 55;
            }
        :: else -> skip
        fi
    od
}
