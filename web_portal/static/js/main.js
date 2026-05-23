/**
 * DeFi Guardian Web Portal
 * Main JavaScript entry point
 */

document.addEventListener('DOMContentLoaded', () => {
    console.log('🛡️ DeFi Guardian Portal initialized');

    // Handle Navbar transparency on scroll
    const navbar = document.querySelector('.navbar');
    if (navbar) {
        window.addEventListener('scroll', () => {
            if (window.scrollY > 50) {
                navbar.classList.add('navbar-scrolled');
            } else {
                navbar.classList.remove('navbar-scrolled');
            }
        });
    }

    // Initialize tooltips if Bootstrap is available
    if (typeof bootstrap !== 'undefined') {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // ── Mobile Menu Toggle ──────────────────────────────────────────────────
    const mobileToggle = document.getElementById('mobile-menu-toggle');
    const sidebar = document.getElementById('sidebar');
    const backdrop = document.getElementById('sidebar-backdrop');

    if (mobileToggle && sidebar && backdrop) {
        const toggleMenu = () => {
            sidebar.classList.toggle('is-open');
            backdrop.classList.toggle('is-open');
            document.body.classList.toggle('no-scroll');
        };

        mobileToggle.addEventListener('click', toggleMenu);
        backdrop.addEventListener('click', toggleMenu);

        // Close menu when clicking a link (for single page navigation or same-page anchors)
        sidebar.querySelectorAll('.sidebar-link').forEach(link => {
            link.addEventListener('click', () => {
                sidebar.classList.remove('is-open');
                backdrop.classList.remove('is-open');
                document.body.classList.remove('no-scroll');
            });
        });
    }
});
