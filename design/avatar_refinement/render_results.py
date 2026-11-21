"""Regenerate avatar evidence from the repository root.

Run python3 -m design.avatar_refinement.render_results with Pillow,
ImageMagick's Sixel decoder, and the Fedora Hack fonts installed.
"""

from contextlib import closing
from io import BytesIO
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw, ImageFont
from avatar import ART_COLORS, OPERATORS, STAGES, portrait
from learning import Learning
from model import THEMES
from ops import Dashboard
from verify import verify

results = Path(__file__).with_name('results')
font_dir = Path('/usr/share/fonts/source-foundry-hack-fonts')
fonts = tuple(ImageFont.truetype(str(font_dir / f'Hack-{style}.ttf'), 12)
              for style in ('Regular', 'Bold'))
tokens = re.compile(r'\x1bP.*?\x1b\\|\x1b\[([0-9;?]*)([@-~])|[^\x1b]+', re.S)


def render(raw, columns, rows, cell):
    width, height = cell
    canvas = Image.new('RGB', (columns * width, rows * height))
    draw = ImageDraw.Draw(canvas)
    x = y = 0
    fg, bg = '#eeeeee', '#000000'
    bold = False
    for token in tokens.finditer(raw):
        s = token[0]
        if s.startswith('\x1bP'):
            with TemporaryDirectory() as directory:
                six = Path(directory) / 'frame.six'
                six.write_text(s)
                png = subprocess.check_output(['magick', str(six), 'png:-'])
            with Image.open(BytesIO(png)) as image:
                canvas.paste(image.convert('RGB'), (x*width, y*height))
        elif token[2] == 'H':
            y, x = (int(i) - 1 for i in token[1].split(';'))
        elif token[2] == 'J':
            draw.rectangle((0, 0, canvas.width, canvas.height), fill=bg)
        elif token[2] == 'm':
            args = token[1].split(';')
            if args[0] in ('38', '48'):
                ink = '#' + ''.join(f'{int(i):02x}' for i in args[2:])
                if args[0] == '38':
                    fg = ink
                else:
                    bg = ink
            elif args[0] in ('1', '22'):
                bold = args[0] == '1'
        elif not s.startswith('\x1b'):
            for character in s:
                if not 0 <= x < columns or not 0 <= y < rows:
                    break
                left, top = x * width, y * height
                draw.rectangle((left, top, left+width-1, top+height-1), fill=bg)
                if character in '▄▀█':
                    upper = top + (height // 2 if character == '▄' else 0)
                    lower = top + (height // 2 - 1 if character == '▀' else height - 1)
                    draw.rectangle((left, upper, left+width-1, lower), fill=fg)
                elif character != ' ':
                    draw.text((left, top + 1), character, font=fonts[bold], fill=fg)
                x += 1
    return canvas


def capture(name, raw):
    if name[-1] in '14':
        render(raw.decode(), 140, 45, (7, 17)).save(results / f'{name}-sixel.png')


def contact_sheet():
    sheet = Image.new('RGB', (928, 512), '#101b20')
    label = ImageDraw.Draw(sheet)
    palette = [tuple(bytes.fromhex(c)) for c in ART_COLORS]
    for i, operator in enumerate(OPERATORS):
        for j, stage in enumerate(STAGES):
            sprite = portrait(j, i)
            art = Image.new('RGBA', (len(sprite[0]), len(sprite)))
            art.putdata([(*palette[v], 255 if v else 0) for row in sprite for v in row])
            large = art.resize((208, 220), Image.Resampling.NEAREST)
            x, y = 12 + 232*j, 10 + 256*i
            sheet.paste(large, (x, y), large)
            label.text((x, y + 225), f'{operator} / {j+1} {stage}', font=fonts[1], fill='#e8f8fb')
    sheet.save(results / 'contact-sheet.png')


def main():
    results.mkdir(exist_ok=True)
    contact_sheet()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'ccna-network-ops').mkdir()
        (root / 'ccna-network-ops' / 'theme').write_text('Mint Circuit\n')
        verify('sixel', root, graphics_reply=True, capture=capture)
        with closing(Learning(root / 'render.sqlite')) as learning:
            app = Dashboard(root / 'ccna-network-ops' / 'theme', learning, root / 'inbox')
            for _ in STAGES:
                app.key('e')
            app.key('a')
            render(app.frame(80, 24), 80, 24, (8, 19)).save(results / 'relay-4-unicode-80x24.png')
            panel_width, panel_height = 287, 494
            heading = 22
            sheet = Image.new('RGB', (len(THEMES) * panel_width, 2 * panel_height + heading), '#101b20')
            labels = ImageDraw.Draw(sheet)
            for index, theme in enumerate(THEMES):
                x = index * panel_width
                labels.text((x + 6, 4), theme.name, font=fonts[1], fill="#e8f8fb")
                app.theme_index = index
                for operator in range(2):
                    app.preview_operator = operator
                    image = render(app.frame(140, 45, (7, 17)), 140, 45, (7, 17))
                    sheet.paste(image.crop((14, 102, 301, 596)), (x, heading + operator * panel_height))
            sheet.save(results / 'themes-sixel.png')


if __name__ == "__main__":
    main()
