	switch (t->back) {
	default: Uerror("bad return move");
	case  0: goto R999; /* nothing to undo */

		 /* CLAIM reachability_liquidation */
;
		;
		;
		;
		
	case 5: // STATE 13
		;
		p_restor(II);
		;
		;
		goto R999;

		 /* CLAIM fairness */
;
		;
		;
		;
		
	case 8: // STATE 13
		;
		p_restor(II);
		;
		;
		goto R999;

		 /* CLAIM stability */
;
		;
		;
		;
		
	case 11: // STATE 13
		;
		p_restor(II);
		;
		;
		goto R999;

		 /* CLAIM response_price_drop */
;
		;
		;
		;
		
	case 14: // STATE 13
		;
		p_restor(II);
		;
		;
		goto R999;

		 /* CLAIM invariant_collateral */
;
		
	case 15: // STATE 1
		goto R999;

	case 16: // STATE 10
		;
		p_restor(II);
		;
		;
		goto R999;

		 /* CLAIM liveness_progress */
;
		;
		
	case 18: // STATE 6
		;
		p_restor(II);
		;
		;
		goto R999;

		 /* CLAIM safety_reentrancy */
;
		
	case 19: // STATE 1
		goto R999;

	case 20: // STATE 10
		;
		p_restor(II);
		;
		;
		goto R999;

		 /* CLAIM safety_no_overflow */
;
		
	case 21: // STATE 1
		goto R999;

	case 22: // STATE 10
		;
		p_restor(II);
		;
		;
		goto R999;

		 /* CLAIM never_0 */
;
		;
		;
		;
		;
		;
		
	case 26: // STATE 10
		;
		p_restor(II);
		;
		;
		goto R999;

		 /* PROC Contract */

	case 27: // STATE 2
		;
		now.state = trpt->bup.oval;
		;
		goto R999;
;
		;
		
	case 29: // STATE 8
		;
		now.health_factor = trpt->bup.oval;
		;
		goto R999;

	case 30: // STATE 18
		;
		now.state = trpt->bup.ovals[2];
		now.state = trpt->bup.ovals[1];
		now.liquidation_executed = trpt->bup.ovals[0];
		;
		ungrab_ints(trpt->bup.ovals, 3);
		goto R999;

	case 31: // STATE 18
		;
		now.state = trpt->bup.oval;
		;
		goto R999;

	case 32: // STATE 18
		;
		now.state = trpt->bup.oval;
		;
		goto R999;
;
		;
		;
		
	case 34: // STATE 21
		goto R999;

	case 35: // STATE 27
		;
		p_restor(II);
		;
		;
		goto R999;
	}

