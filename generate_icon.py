"""Generate Happy Vision app icon — modern camera lens + AI eye design."""

import subprocess
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import math


def create_icon(size=1024):
    """Create a modern dark icon with a stylized lens/eye."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded square background with gradient
    margin = int(size * 0.08)
    radius = int(size * 0.22)

    # Draw dark gradient background (top-left lighter, bottom-right darker)
    for y in range(size):
        for x in range(size):
            # Check if inside rounded rect
            in_rect = True
            corners = [
                (margin + radius, margin + radius, margin, margin),
                (size - margin - radius, margin + radius, size - margin, margin),
                (margin + radius, size - margin - radius, margin, size - margin),
                (size - margin - radius, size - margin - radius, size - margin, size - margin),
            ]
            for cx, cy, ex, ey in corners:
                if (x < margin + radius and y < margin + radius and x >= margin and y >= margin):
                    if (x - (margin + radius))**2 + (y - (margin + radius))**2 > radius**2:
                        in_rect = False
                elif (x > size - margin - radius and y < margin + radius and x <= size - margin and y >= margin):
                    if (x - (size - margin - radius))**2 + (y - (margin + radius))**2 > radius**2:
                        in_rect = False
                elif (x < margin + radius and y > size - margin - radius and x >= margin and y <= size - margin):
                    if (x - (margin + radius))**2 + (y - (size - margin - radius))**2 > radius**2:
                        in_rect = False
                elif (x > size - margin - radius and y > size - margin - radius and x <= size - margin and y <= size - margin):
                    if (x - (size - margin - radius))**2 + (y - (size - margin - radius))**2 > radius**2:
                        in_rect = False
                elif x < margin or x > size - margin or y < margin or y > size - margin:
                    in_rect = False

            if in_rect:
                # Gradient: deep purple-black
                t = (x + y) / (2 * size)
                r = int(18 + t * 12)
                g = int(14 + t * 8)
                b = int(30 + t * 20)
                img.putpixel((x, y), (r, g, b, 255))

    # Now draw the lens/eye design on top
    draw = ImageDraw.Draw(img)
    cx, cy = size // 2, size // 2

    # Outer ring — violet glow
    for ring_w in range(8, 0, -1):
        alpha = int(60 + (8 - ring_w) * 24)
        r_outer = int(size * 0.32)
        color = (139, 92, 246, min(255, alpha))  # violet
        draw.ellipse(
            [cx - r_outer - ring_w, cy - r_outer - ring_w,
             cx + r_outer + ring_w, cy + r_outer + ring_w],
            outline=color, width=2,
        )

    # Main lens ring
    r_outer = int(size * 0.32)
    draw.ellipse(
        [cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer],
        outline=(139, 92, 246, 255), width=int(size * 0.025),
    )

    # Aperture blades (6 blades)
    blade_r_outer = int(size * 0.29)
    blade_r_inner = int(size * 0.14)
    num_blades = 6
    rotation = math.pi / 6  # 30 degree offset

    for i in range(num_blades):
        angle1 = (2 * math.pi * i / num_blades) + rotation
        angle2 = (2 * math.pi * (i + 0.5) / num_blades) + rotation

        x1 = cx + blade_r_outer * math.cos(angle1)
        y1 = cy + blade_r_outer * math.sin(angle1)
        x2 = cx + blade_r_inner * math.cos(angle2)
        y2 = cy + blade_r_inner * math.sin(angle2)
        x3 = cx + blade_r_outer * math.cos(angle2 + (angle2 - angle1) * 0.1)
        y3 = cy + blade_r_outer * math.sin(angle2 + (angle2 - angle1) * 0.1)

        draw.line([(x1, y1), (x2, y2)], fill=(139, 92, 246, 180), width=int(size * 0.012))

    # Inner circle (lens center) — gradient fill
    r_inner = int(size * 0.13)
    for r in range(r_inner, 0, -1):
        t = r / r_inner
        cr = int(80 + (1 - t) * 60)
        cg = int(40 + (1 - t) * 52)
        cb = int(180 + (1 - t) * 76)
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(cr, cg, cb, 255),
        )

    # AI "pupil" — bright dot in center
    r_pupil = int(size * 0.04)
    for r in range(r_pupil + 4, 0, -1):
        t = r / (r_pupil + 4)
        alpha = int(255 * (1 - t * t))
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(255, 255, 255, alpha),
        )

    # Small highlight reflection (top-right of lens)
    hx = cx + int(size * 0.08)
    hy = cy - int(size * 0.10)
    hr = int(size * 0.025)
    for r in range(hr + 3, 0, -1):
        t = r / (hr + 3)
        alpha = int(200 * (1 - t))
        draw.ellipse(
            [hx - r, hy - r, hx + r, hy + r],
            fill=(255, 255, 255, alpha),
        )

    return img


def build_icns(icon_img: Image.Image, output: Path):
    """Create .icns from a PIL image using iconutil."""
    iconset = output.parent / "HappyVision.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir()

    sizes = [16, 32, 64, 128, 256, 512]
    for s in sizes:
        icon_img.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
        icon_img.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")

    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(output)], check=True)
    shutil.rmtree(iconset)
    print(f"Created {output}")


if __name__ == "__main__":
    project = Path(__file__).parent
    icon = create_icon(1024)

    # Save PNG preview
    png_path = project / "assets" / "icon.png"
    png_path.parent.mkdir(exist_ok=True)
    icon.save(png_path)
    print(f"Saved PNG: {png_path}")

    # Build .icns
    icns_path = project / "assets" / "HappyVision.icns"
    build_icns(icon, icns_path)
