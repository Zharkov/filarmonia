import zipfile, re, sys

path = sys.argv[1] if len(sys.argv) > 1 else 'правки.docx'
with zipfile.ZipFile(path) as z:
    xml = z.read('word/document.xml').decode('utf-8')

paras = re.findall(r'<w:p[ >].*?</w:p>', xml, re.S)
out = []
for p in paras:
    texts = re.findall(r'<w:t[^>]*>(.*?)</w:t>', p, re.S)
    line = ''.join(texts)
    line = (line.replace('&amp;', '&').replace('&lt;', '<')
             .replace('&gt;', '>').replace('&quot;', '"')
             .replace('&apos;', "'"))
    out.append(line)
print('\n'.join(out))
