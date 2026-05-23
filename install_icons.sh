#!/bin/bash
# Install DeFi Guardian icons to system locations

echo "Installing DeFi Guardian icons..."

# Create icon directories
sudo mkdir -p /usr/share/icons/hicolor/16x16/apps
sudo mkdir -p /usr/share/icons/hicolor/22x22/apps
sudo mkdir -p /usr/share/icons/hicolor/24x24/apps
sudo mkdir -p /usr/share/icons/hicolor/32x32/apps
sudo mkdir -p /usr/share/icons/hicolor/48x48/apps
sudo mkdir -p /usr/share/icons/hicolor/64x64/apps
sudo mkdir -p /usr/share/icons/hicolor/128x128/apps
sudo mkdir -p /usr/share/icons/hicolor/256x256/apps
sudo mkdir -p /usr/share/icons/hicolor/scalable/apps

# Copy icons
sudo cp /home/slade/defi_guardian/defi_guardian_16.png /usr/share/icons/hicolor/16x16/apps/defi-guardian.png
sudo cp /home/slade/defi_guardian/defi_guardian_24.png /usr/share/icons/hicolor/24x24/apps/defi-guardian.png
sudo cp /home/slade/defi_guardian/defi_guardian_32.png /usr/share/icons/hicolor/32x32/apps/defi-guardian.png
sudo cp /home/slade/defi_guardian/defi_guardian_48.png /usr/share/icons/hicolor/48x48/apps/defi-guardian.png
sudo cp /home/slade/defi_guardian/defi_guardian_64.png /usr/share/icons/hicolor/64x64/apps/defi-guardian.png
sudo cp /home/slade/defi_guardian/defi_guardian_128.png /usr/share/icons/hicolor/128x128/apps/defi-guardian.png
sudo cp /home/slade/defi_guardian/defi_guardian_256.png /usr/share/icons/hicolor/256x256/apps/defi-guardian.png

# Update icon cache
sudo gtk-update-icon-cache /usr/share/icons/hicolor -f

echo "✅ Icons installed successfully!"
echo "You can now use the DeFi Guardian icon in your application menu."
