/**
 * DeFi Guardian - WebSocket Client
 * Listens for real-time verification events and updates the UI.
 */

(function() {
    const socket = io();

    socket.on('connect', () => {
        console.log('Connected to DeFi Guardian WebSocket');
        socket.emit('request_state');
    });

    socket.on('verification_complete', (event) => {
        console.log('Verification Complete:', event);
        
        // Ensure event data is properly formatted for the portal
        const normalizedEvent = {
            tool: event.tool || 'Unknown',
            status: (event.status || 'unknown').toUpperCase(),
            filename: event.filename || event.file || '',
            timestamp: event.timestamp || Date.now(),
            message: event.message || `Verification completed with status: ${event.status}`,
            source: event.source || 'web_portal'
        };

        // Broadcast a custom event for other components to listen to
        const customEvent = new CustomEvent('dg:verification_complete', {
            detail: normalizedEvent
        });
        document.dispatchEvent(customEvent);

        // Broadcast another one for compatibility with other components
        const customEvent2 = new CustomEvent('defi_guardian:verification_complete', {
            detail: normalizedEvent
        });
        window.dispatchEvent(customEvent2);

        // Show a notification if enabled
        if (window.DGSocket && window.DGSocket.showToast) {
            const type = ['PASS', 'VERIFIED'].includes(normalizedEvent.status) ? 'success'
                       : ['FAIL', 'VIOLATED'].includes(normalizedEvent.status) ? 'danger'
                       : normalizedEvent.status === 'TIMEOUT' ? 'warning' : 'info';
            window.DGSocket.showToast(normalizedEvent.tool, normalizedEvent.status, type);
        } else if (window.showNotification) {
            window.showNotification(
                `Verification Finished: ${normalizedEvent.tool}`,
                `${normalizedEvent.filename} - Status: ${normalizedEvent.status}`,
                normalizedEvent.status === 'PASS' ? 'success' : 'danger'
            );
        }
    });

    socket.on('verification_update', (event) => {
        console.log('Verification Update:', event);
        document.dispatchEvent(new CustomEvent('dg:state_update', { detail: event }));
    });

    socket.on('disconnect', () => {
        console.log('Disconnected from DeFi Guardian WebSocket');
    });

    // ── Public API ───────────────────────────────────────────────────────────
    window.DGSocket = {
        socket: socket
    };
})();
