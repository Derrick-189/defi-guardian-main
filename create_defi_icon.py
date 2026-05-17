from PIL import Image, ImageDraw, ImageFont
import os

# Create a 256x256 icon
size = 256
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Draw shield shape
shield_color = (46, 125, 50)  # Green
draw.rectangle([40, 40, 216, 216], fill=shield_color, outline=(255, 255, 255), width=3)

# Draw inner shield
draw.polygon([(128, 50), (200, 90), (200, 160), (128, 200), (56, 160), (56, 90)], 
             fill=(76, 175, 80), outline=(255, 255, 255), width=2)

# Draw lock symbol
draw.rectangle([108, 120, 148, 160], fill=(255, 255, 255))
draw.ellipse([118, 100, 138, 120], fill=(255, 255, 255))
draw.rectangle([123, 140, 133, 160], fill=(46, 125, 50))

# Draw "DF" text
try:
    # Try to use a default font
    font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 80)
except:
    font = ImageFont.load_default()

draw.text((88, 70), "DF", fill=(255, 255, 255), font=font)

# Save as PNG
img.save("/home/slade/defi_guardian_icon.png")
print("Icon created: /home/slade/defi_guardian_icon.png")

# Also create a smaller 128x128 version
img_small = img.resize((128, 128), Image.Resampling.LANCZOS)
img_small.save("/home/slade/defi_guardian_icon_128.png")

# Create an ICO file (Windows format, but works on Linux too)
img_ico = img.resize((64, 64), Image.Resampling.LANCZOS)
img_ico.save("/home/slade/defi_guardian.ico", format="ICO", sizes=[(64, 64)])
print("ICO file created: /home/slade/defi_guardian.ico")
