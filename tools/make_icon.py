"""Genera assets/icon.ico: símbolo de encendido/apagado."""
from pathlib import Path

from PIL import Image, ImageDraw

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((40, 40, S - 40, S - 40), radius=210, fill=(31, 78, 120, 255))
c, r, w = S // 2, 290, 85
d.arc((c - r, c - r + 40, c + r, c + r + 40), start=-60, end=240, fill=(255, 255, 255, 255), width=w)
d.line((c, 190, c, 500), fill=(255, 95, 82, 255), width=w + 10)
d.ellipse((c - (w + 10) // 2, 190 - (w + 10) // 2, c + (w + 10) // 2, 190 + (w + 10) // 2), fill=(255, 95, 82, 255))
d.ellipse((c - (w + 10) // 2, 500 - (w + 10) // 2, c + (w + 10) // 2, 500 + (w + 10) // 2), fill=(255, 95, 82, 255))
d.arc((c - r, c - r + 40, c + r, c + r + 40), start=-60, end=-59.5, fill=(255, 255, 255, 255), width=w)

out = Path(__file__).resolve().parent.parent / "assets"
out.mkdir(exist_ok=True)
img.save(out / "icon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("icon.ico generado")
