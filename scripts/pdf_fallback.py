"""Small fixture-only PDF writer for offline development without reportlab."""
from pathlib import Path

def write_pdf(path: Path, lines: list[str], modern: bool=False) -> None:
    commands=['0.07 0.20 0.29 rg 0 690 612 102 re f', 'BT /F1 12 Tf '+('65' if modern else '35')+' 750 Td']
    for i,line in enumerate(lines):
        commands.append("1 1 1 rg" if i < 2 else "0.12 0.17 0.22 rg")
        escaped=line.replace('\\','\\\\').replace('(','\\(').replace(')','\\)')
        commands.extend([f'({escaped}) Tj','0 -32 Td'])
    commands.append('ET'); stream='\n'.join(commands).encode('latin-1')
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    result=bytearray(b'%PDF-1.4\n');offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(result));result.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    start=len(result);result.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:result.extend(f'{offset:010} 00000 n \n'.encode())
    result.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode());path.write_bytes(result)
