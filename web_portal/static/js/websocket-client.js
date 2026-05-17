/**
 * DeFi Guardian - WebSocket Client
 * Listens for real-time verification events and updates the UI.
 */

(function() {
    const socket = io();

    socket.on('connect', () => {
        console.log('Connected to DeFi Guardian WebSocket');
    });

    socket.on('verification_complete', (event) => {
        console.log('Verification Complete:', event);
        
        // Broadcast a custom event for other components to listen to
        const customEvent = new CustomEvent('defi_guardian:verification_complete', {
            detail: event
        });
        window.dispatchEvent(customEvent);

        // Show a notification if enabled
        if (window.showNotification) {
            window.showNotification(
                `Verification Finished: ${event.tool}`,
                `${event.filename} - Status: ${event.status}`,
                event.status === 'PASS' ? 'success' : 'danger'
            );
        }
    });

    socket.on('disconnect', () => {
        console.log('Disconnected from DeFi Guardian WebSocket');
    });
})();
