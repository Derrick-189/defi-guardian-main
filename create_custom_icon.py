#!/usr/bin/env python3
"""
Create custom icon for DeFi Guardian desktop menu entry
Generates high-quality icons in multiple sizes and formats
"""

import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math

class DeFiGuardianIcon:
    def __init__(self, output_dir=None):
        self.output_dir = output_dir or os.path.dirname(os.path.abspath(__file__))
        
        # Color scheme
        self.colors = {
            'primary': '#00ffcc',      # Cyan
            'primary_dark': '#00ccaa', # Dark cyan
            'secondary': '#ff00cc',    # Magenta
            'background': '#0a0a0a',   # Dark background
            'shield_bg': '#1a1a2e',    # Dark blue-gray
            'accent': '#ffffff',       # White
        }
        
        # Icon sizes needed (for different contexts)
        self.sizes = {
            '16': 16,    # Small menu icon
            '22': 22,    # Menu icon
            '24': 24,    # Menu icon
            '32': 32,    # Taskbar
            '48': 48,    # Application menu
            '64': 64,    # Application menu
            '128': 128,  # Desktop icon
            '256': 256,  # High resolution
            '512': 512,  # Very high resolution
        }
    
    def hex_to_rgb(self, hex_color):
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def create_shield(self, size, color, background_color):
        """Create a shield shape"""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Calculate points for shield shape
        w = size
        h = size
        top = h * 0.15
        bottom = h * 0.85
        left = w * 0.2
        right = w * 0.8
        
        # Shield points (classic shield shape)
        points = [
            (w // 2, top),                    # Top point
            (right, top + h * 0.15),          # Top right
            (right, bottom - h * 0.1),        # Middle right
            (w // 2, bottom),                 # Bottom point
            (left, bottom - h * 0.1),         # Middle left
            (left, top + h * 0.15),           # Top left
        ]
        
        # Draw shield with gradient effect
        draw.polygon(points, fill=background_color)
        
        # Add inner glow
        inner_points = [
            (w // 2, top + h * 0.03),
            (right - w * 0.05, top + h * 0.18),
            (right - w * 0.05, bottom - h * 0.15),
            (w // 2, bottom - h * 0.03),
            (left + w * 0.05, bottom - h * 0.15),
            (left + w * 0.05, top + h * 0.18),
        ]
        draw.polygon(inner_points, fill=(self.hex_to_rgb(color)[0], self.hex_to_rgb(color)[1], self.hex_to_rgb(color)[2], 50))
        
        # Add border
        draw.polygon(points, outline=color, width=max(2, size // 50))
        
        return img
    
    def create_lock_icon(self, size, color):
        """Create a lock icon for the shield"""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        w = size
        h = size
        
        # Lock body
        lock_width = w * 0.5
        lock_height = h * 0.35
        lock_x = (w - lock_width) / 2
        lock_y = h * 0.45
        
        draw.rectangle(
            [lock_x, lock_y, lock_x + lock_width, lock_y + lock_height],
            fill=color,
            outline=color,
            width=1
        )
        
        # Lock shackle
        shackle_width = lock_width * 0.6
        shackle_height = lock_height * 0.5
        shackle_x = (w - shackle_width) / 2
        shackle_y = lock_y - shackle_height * 0.7
        
        draw.rectangle(
            [shackle_x, shackle_y, shackle_x + shackle_width, shackle_y + shackle_height],
            fill=color,
            outline=color,
            width=1
        )
        
        return img
    
    def create_text_logo(self, size, text, color):
        """Create text logo"""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Try to find a good font
        font_size = size // 3
        font_paths = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
            "C:\\Windows\\Fonts\\Arial.ttf",        # Windows
        ]
        
        font = None
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except:
                continue
        
        if font is None:
            font = ImageFont.load_default()
        
        # Calculate text position
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (size - text_width) / 2
        y = (size - text_height) / 2
        
        draw.text((x, y), text, fill=color, font=font)
        
        return img
    
    def create_guardian_logo(self, size):
        """Create guardian symbol (stylized 'G' with shield)"""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        w = size
        h = size
        center_x = w / 2
        center_y = h / 2
        
        # Create shield shape as background
        shield_points = [
            (center_x, h * 0.2),
            (w * 0.8, h * 0.3),
            (w * 0.8, h * 0.7),
            (center_x, h * 0.8),
            (w * 0.2, h * 0.7),
            (w * 0.2, h * 0.3),
        ]
        draw.polygon(shield_points, fill=self.hex_to_rgb(self.colors['shield_bg']))
        
        # Draw stylized 'G'
        font_size = size // 2
        font_paths = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/ubuntu/Ubuntu-Bold.ttf",
        ]
        
        font = None
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, font_size)
                break
            except:
                continue
        
        if font:
            # Draw 'G'
            bbox = draw.textbbox((0, 0), "G", font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (w - text_width) / 2
            y = (h - text_height) / 2 - h * 0.05
            draw.text((x, y), "G", fill=self.colors['primary'], font=font)
            
            # Draw small 'D' for DeFi
            small_font = ImageFont.truetype(font_path, size // 5)
            draw.text((w * 0.35, h * 0.65), "D", fill=self.colors['secondary'], font=small_font)
        
        # Add decorative elements
        # Draw hexagon pattern around the edge
        for i in range(6):
            angle = (i * 60) * math.pi / 180
            x = center_x + w * 0.4 * math.cos(angle)
            y = center_y + h * 0.4 * math.sin(angle)
            draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=self.colors['primary'], outline=None)
        
        return img
    
    def create_full_icon(self, size):
        """Create the complete DeFi Guardian icon"""
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        
        # Create shield background
        shield = self.create_shield(size, self.colors['primary'], self.hex_to_rgb(self.colors['shield_bg']))
        img.paste(shield, (0, 0), shield)
        
        # Add guardian logo
        if size >= 64:
            logo_size = int(size * 0.6)
            logo = self.create_guardian_logo(logo_size)
            logo_x = (size - logo_size) // 2
            logo_y = (size - logo_size) // 2
            img.paste(logo, (logo_x, logo_y), logo)
        
        # Add text for larger icons
        if size >= 128:
            text_img = self.create_text_logo(size, "DG", self.colors['primary'])
            img.paste(text_img, (0, 0), text_img)
        
        return img
    
    def create_all_icons(self):
        """Create icons in all required sizes"""
        icons = {}
        
        print("Creating DeFi Guardian icons...")
        print("-" * 50)
        
        for name, size in self.sizes.items():
            print(f"  Creating {size}x{size} icon...")
            icon = self.create_full_icon(size)
            icons[name] = icon
            
            # Save PNG
            png_path = os.path.join(self.output_dir, f"defi_guardian_{size}.png")
            icon.save(png_path, "PNG")
        
        # Create ICO file (Windows format)
        print("\n  Creating ICO file...")
        ico_images = []
        for size in [16, 24, 32, 48, 64, 128, 256]:
            icon = self.create_full_icon(size)
            ico_images.append(icon)
        
        ico_path = os.path.join(self.output_dir, "defi_guardian.ico")
        ico_images[0].save(ico_path, format="ICO", sizes=[(s, s) for s in [16, 24, 32, 48, 64, 128, 256]])
        
        # Create main icon (128x128)
        main_icon = self.create_full_icon(128)
        main_path = os.path.join(self.output_dir, "defi_guardian.png")
        main_icon.save(main_path, "PNG")
        
        print("\n✅ Icons created successfully!")
        print(f"   Main icon: {main_path}")
        print(f"   ICO file: {ico_path}")
        print(f"   All sizes saved in: {self.output_dir}")
        
        return icons
    
    def create_application_icons(self):
        """Create icons for application menu (Linux)"""
        # Create icon in standard sizes for Linux
        icon_sizes = {
            '16x16': 16,
            '22x22': 22,
            '24x24': 24,
            '32x32': 32,
            '48x48': 48,
            '64x64': 64,
            '128x128': 128,
            '256x256': 256,
        }
        
        for size_name, size in icon_sizes.items():
            icon = self.create_full_icon(size)
            icon_path = os.path.join(self.output_dir, f"defi_guardian_{size_name}.png")
            icon.save(icon_path, "PNG")
        
        # Create symbolic link for the main icon
        main_icon_path = os.path.join(self.output_dir, "defi_guardian.png")
        if not os.path.exists(main_icon_path):
            icon = self.create_full_icon(128)
            icon.save(main_icon_path, "PNG")
        
        print("\n✅ Application icons created for Linux menu")

def create_icon_setup_script(output_dir):
    """Create a setup script to install icons"""
    script_content = f'''#!/bin/bash
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
sudo cp {output_dir}/defi_guardian_16.png /usr/share/icons/hicolor/16x16/apps/defi-guardian.png
sudo cp {output_dir}/defi_guardian_24.png /usr/share/icons/hicolor/24x24/apps/defi-guardian.png
sudo cp {output_dir}/defi_guardian_32.png /usr/share/icons/hicolor/32x32/apps/defi-guardian.png
sudo cp {output_dir}/defi_guardian_48.png /usr/share/icons/hicolor/48x48/apps/defi-guardian.png
sudo cp {output_dir}/defi_guardian_64.png /usr/share/icons/hicolor/64x64/apps/defi-guardian.png
sudo cp {output_dir}/defi_guardian_128.png /usr/share/icons/hicolor/128x128/apps/defi-guardian.png
sudo cp {output_dir}/defi_guardian_256.png /usr/share/icons/hicolor/256x256/apps/defi-guardian.png

# Update icon cache
sudo gtk-update-icon-cache /usr/share/icons/hicolor -f

echo "✅ Icons installed successfully!"
echo "You can now use the DeFi Guardian icon in your application menu."
'''
    
    script_path = os.path.join(output_dir, "install_icons.sh")
    with open(script_path, 'w') as f:
        f.write(script_content)
    
    os.chmod(script_path, 0o755)
    print(f"✅ Created icon installation script: {script_path}")

def create_desktop_entry(output_dir):
    """Create desktop entry with correct icon paths"""
    desktop_content = f'''[Desktop Entry]
Version=1.0
Type=Application
Name=DeFi Guardian
Name[en]=DeFi Guardian
GenericName=Formal Verification Suite
GenericName[en]=Formal Verification Suite
Comment=Formal verification platform for DeFi protocols
Comment[en]=Formal verification platform for DeFi protocols
Exec=python3 {output_dir}/defi_guardian_shortcut.py
Icon={output_dir}/defi_guardian.png
Terminal=false
StartupNotify=true
Categories=Development;Security;Utility;
Keywords=formal verification;SPIN;LTL;security;audit;defi;
StartupWMClass=defi-guardian
MimeType=
X-Desktop-File-Install-Version=0.26
'''
    
    desktop_path = os.path.join(output_dir, "defi-guardian.desktop")
    with open(desktop_path, 'w') as f:
        f.write(desktop_content)
    
    print(f"✅ Created desktop entry: {desktop_path}")

if __name__ == "__main__":
    # Get the script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Create icons
    icon_creator = DeFiGuardianIcon(script_dir)
    icons = icon_creator.create_all_icons()
    icon_creator.create_application_icons()
    
    # Create installation script
    create_icon_setup_script(script_dir)
    create_desktop_entry(script_dir)
    
    print("\n" + "="*50)
    print("🎉 DeFi Guardian Icon Creation Complete!")
    print("="*50)
    print("\nNext steps:")
    print("1. Install icons system-wide:")
    print("   cd ~/defi_guardian")
    print("   ./install_icons.sh")
    print("\n2. Or use the icons directly from the application directory")
    print("\n3. The desktop entry file is ready: defi-guardian.desktop")
    print("   To install it, copy to: ~/.local/share/applications/")
    print("   cp defi-guardian.desktop ~/.local/share/applications/")