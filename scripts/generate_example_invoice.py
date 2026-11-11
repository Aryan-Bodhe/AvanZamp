"""A realistic manual-validation input, separate from synthetic extraction fixtures."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def generate() -> None:
    out = ROOT/'data/examples'
    out.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (1654, 2339), 'white')
    draw = ImageDraw.Draw(image)
    fonts = Path('/usr/share/fonts/truetype/dejavu')

    def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(fonts/('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf')), size)

    def text(x: int, y: int, value: str, size: int = 28, bold: bool = False, color: str = '#243746') -> None:
        draw.text((x, y), value, font=font(size, bold), fill=color)

    def right(x: int, y: int, value: str, size: int = 28, bold: bool = False) -> None:
        text(int(x-draw.textlength(value,font=font(size,bold))), y, value, size, bold)

    navy = '#143648'
    muted = '#657886'
    draw.rectangle((0,0,1654,30), fill=navy)
    draw.rounded_rectangle((110,110,190,190), radius=15, fill=navy)
    text(125,119,'N',52,True,'white')
    text(220,105,'NORTHWIND',48,True)
    text(222,168,'Office supplies & workspace essentials',23,color=muted)
    text(110,270,'Northwind Office Supplies Ltd',30,True)
    for i,line in enumerate(['22 Commerce Avenue','New York, NY 10001, United States','accounts@northwind.example','Tax registration: US-NW-024861']):
        text(110,325+i*40,line,24,color=muted)
    right(1540,265,'INVOICE',68,True)
    labels=[('Invoice no.','NW-2026-1148'),('Invoice date','2026-11-09'),('Due date','2026-12-09'),('Purchase order','PO-1001'),('Currency','USD')]
    for i,(label,value) in enumerate(labels):
        text(980,370+i*48,label,25,color=muted)
        right(1540,370+i*48,value,26,True)
    draw.line((110,670,1540,670),fill='#D9E2E8',width=2)
    text(110,720,'BILL TO',23,True,muted)
    text(110,770,'Acme Operations Inc',32,True)
    for i,line in enumerate(['Accounts Payable','410 Market Street, Suite 600','San Francisco, CA 94111','ap@acme.example']):
        text(110,824+i*39,line,25)
    text(980,720,'SHIP TO',23,True,muted)
    for i,line in enumerate(['Acme Operations Inc','Operations - Q4 workspace refresh','410 Market Street, Suite 600','San Francisco, CA 94111']):
        text(980,775+i*43,line,24)
    text(110,1060,'Office furniture - Q4 order',31,True)
    draw.rectangle((110,1130,1540,1205),fill=navy)
    for x,label in [(135,'DESCRIPTION'),(930,'QTY'),(1080,'UNIT PRICE'),(1360,'AMOUNT')]:
        text(x,1153,label,23,True,'white')
    rows=[('Ergonomic task chair','NW-CHR-204 | Charcoal fabric','4','600.00','2,400.00'),
          ('Height-adjustable desk','NW-DSK-118 | 140 cm, oak finish','3','800.00','2,400.00')]
    for i,(desc,sku,qty,unit,amount) in enumerate(rows):
        y=1235+i*130
        if i%2==0:draw.rectangle((110,y-10,1540,y+115),fill='#F4F7F9')
        text(135,y,desc,29,True)
        text(135,y+47,sku,23,color=muted)
        right(990,y,qty);right(1250,y,unit);right(1510,y,amount,29)
    for i,(label,value) in enumerate([('Subtotal','4,800.00'),('Sales tax (8%)','384.00')]):
        text(1000,1570+i*56,label,27)
        right(1510,1570+i*56,value,29)
    draw.rounded_rectangle((965,1705,1540,1810),radius=9,fill='#EAF2F5')
    text(1000,1740,'TOTAL DUE',28,True)
    right(1510,1735,'USD 5,184.00',35,True)
    text(110,1890,'Payment terms',29,True)
    text(110,1940,'Net 30 days. Please include invoice NW-2026-1148 in your remittance.',23)
    text(110,2010,'Questions about this invoice?',26,True)
    text(110,2055,'Contact accounts@northwind.example and reference your purchase order.',23)
    draw.line((110,2180,1540,2180),fill='#D9E2E8',width=2)
    text(110,2210,'SYNTHETIC SAMPLE | For InvoiceDesk extraction testing only',22,color=muted)
    right(1540,2210,'Page 1 of 1',22)
    image.save(out/'office_furniture.png')
    image.save(out/'office_furniture.pdf','PDF',resolution=200)

if __name__ == '__main__':
    generate()
