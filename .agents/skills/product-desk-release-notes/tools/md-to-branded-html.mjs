// Markdown -> Regnology-branded, self-contained HTML (fonts + logo embedded).
// Usage: node md-to-branded-html.mjs <input.md> <output.html> "<title>" "<subtitle>" <brandDir> ["<footer>"]
// Then print to PDF with headless Chrome/Edge (--print-to-pdf).
//
// Brand rules applied (regnology-branding.styleguide.yaml + COLOR_PALETTE.md):
//   - Regnology Sans only; weight 400 / 500. Bold (700) is forbidden -> <strong> renders as Medium 500.
//   - Surfaces: White #FFFFFF, Ice Grey #E1E6E6, Petrol Blue #012D3F.
//   - Accent: Regnology Green #06A74E (light). Warning: Hay Yellow #EC9D1C. Info/links: Ice Blue #1788BE.
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const [, , inPath, outPath, title = 'Release notes', subtitle = '', brandDir, footer = 'Regnology'] = process.argv;
if (!inPath || !outPath || !brandDir) {
  console.error('args: <input.md> <output.html> "<title>" "<subtitle>" <brandDir>');
  process.exit(2);
}

const b64 = (p) => existsSync(p) ? readFileSync(p).toString('base64') : null;
const fontFace = (file, family, weight, style) => {
  const d = b64(join(brandDir, 'assets', 'fonts', file));
  if (!d) return '';
  return `@font-face{font-family:'${family}';font-weight:${weight};font-style:${style};src:url(data:font/woff2;base64,${d}) format('woff2');}`;
};
const fonts = [
  fontFace('RegnologySans-Regular.woff2', 'Regnology Sans', 400, 'normal'),
  fontFace('RegnologySans-Medium.woff2', 'Regnology Sans', 500, 'normal'),
  fontFace('RegnologySans-Italic.woff2', 'Regnology Sans', 400, 'italic'),
  fontFace('RegnologySans-MediumItalic.woff2', 'Regnology Sans', 500, 'italic'),
].join('\n');
const logoB64 = b64(join(brandDir, 'assets', 'Regnology-logo-negative-PNG.png'));

// ---- minimal, structure-aware Markdown converter -------------------------
const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function inline(s) {
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^\w])_([^_]+)_(?=[^\w]|$)/g, '$1<em>$2</em>');
  s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[+i])}</code>`);
  return s;
}

const lines = readFileSync(inPath, 'utf8').replace(/\r\n/g, '\n').split('\n');
const html = [];
let i = 0;
while (i < lines.length) {
  let line = lines[i];
  if (/^\s*$/.test(line)) { i++; continue; }

  // horizontal rule
  if (/^---+\s*$/.test(line)) { html.push('<hr/>'); i++; continue; }

  // headings
  let m;
  if ((m = line.match(/^#\s+(.*)$/))) { html.push(`<h1>${inline(m[1])}</h1>`); i++; continue; }
  if ((m = line.match(/^##\s+(.*)$/))) { html.push(`<h2>${inline(m[1])}</h2>`); i++; continue; }
  if ((m = line.match(/^###\s+(.*)$/))) { html.push(`<h3>${inline(m[1])}</h3>`); i++; continue; }

  // blockquote (callout) — collect consecutive > lines
  if (/^>\s?/.test(line)) {
    const buf = [];
    while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, '')); i++; }
    html.push(`<blockquote>${inline(buf.join(' '))}</blockquote>`);
    continue;
  }

  // table — collect consecutive | ... | lines
  if (/^\s*\|.*\|\s*$/.test(line)) {
    const rows = [];
    while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
      rows.push(lines[i].trim()); i++;
    }
    const cells = (r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
    const isSep = (r) => /^\s*\|?[\s:|-]+\|?\s*$/.test(r) && r.includes('-');
    let head = null, body = [];
    if (rows.length && isSep(rows[1] || '')) { head = cells(rows[0]); body = rows.slice(2); }
    else { body = rows; }
    let t = '<table>';
    if (head) t += '<thead><tr>' + head.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr></thead>';
    t += '<tbody>' + body.map((r) => '<tr>' + cells(r).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('') + '</tbody></table>';
    html.push(t);
    continue;
  }

  // lone-bold paragraph -> label or ticket-title
  if ((m = line.match(/^\*\*(.+)\*\*\s*$/))) {
    const txt = m[1];
    const cls = /^[A-Za-z][A-Za-z ]{0,14}$/.test(txt) && !txt.includes(' ') ? 'label'
              : (txt === 'Problem' || txt === 'Solution' || txt === 'Note') ? 'label' : 'ticket-title';
    html.push(`<p class="${cls}">${inline(txt)}</p>`); i++; continue;
  }

  // paragraph — gather until blank / block start
  const buf = [];
  while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,3}\s|>|---+\s*$|\s*\|)/.test(lines[i])) {
    buf.push(lines[i]); i++;
  }
  html.push(`<p>${inline(buf.join(' '))}</p>`);
}

const today = new Date().toISOString().slice(0, 10);
const doc = `<!doctype html><html><head><meta charset="utf-8"/>
<style>
${fonts}
:root{--green:#06A74E;--green-l:#3CE55A;--petrol:#012D3F;--hay:#EC9D1C;--ice-blue:#1788BE;--stone:#747A7A;--sand:#9FA8A9;--ice:#E1E6E6;}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;}
body{font-family:'Regnology Sans',Arial,sans-serif;font-weight:400;color:#0b1f28;font-size:11pt;line-height:1.5;}
@page{size:A4;margin:16mm 16mm 18mm 16mm;}
.cover{background:var(--petrol);color:#fff;padding:26px 30px;border-radius:10px;margin-bottom:22px;display:flex;align-items:center;justify-content:space-between;gap:20px;}
.cover .logo{height:34px;}
.cover .meta{ text-align:right;}
.cover .doc-title{font-weight:500;font-size:16pt;color:#fff;margin:0 0 4px 0;}
.cover .doc-sub{color:var(--ice);font-size:10.5pt;}
.cover .doc-date{color:var(--sand);font-size:9pt;margin-top:6px;}
h1{font-weight:500;font-size:17pt;color:var(--petrol);margin:6px 0 4px;}
h2{font-weight:500;font-size:13pt;color:var(--green);margin:22px 0 6px;padding-bottom:4px;border-bottom:2px solid var(--ice);}
h3{font-weight:500;font-size:11pt;color:var(--petrol);margin:16px 0 2px;letter-spacing:.02em;}
p{margin:5px 0;}
p.ticket-title{font-weight:500;color:#0b1f28;font-size:11.5pt;margin:2px 0 8px;}
p.label{font-weight:500;color:var(--green);margin:8px 0 0;text-transform:uppercase;font-size:8.5pt;letter-spacing:.08em;}
p.label + p{margin-top:2px;}
strong{font-weight:500;}
em{font-style:italic;color:var(--stone);}
code{font-family:Consolas,'Courier New',monospace;background:var(--ice);color:var(--petrol);padding:1px 5px;border-radius:4px;font-size:9.5pt;}
hr{border:none;border-top:1px solid var(--ice);margin:16px 0;}
blockquote{background:#fff7e6;border-left:4px solid var(--hay);margin:12px 0;padding:9px 14px;color:#5b4708;border-radius:4px;}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:9.5pt;}
th{background:var(--petrol);color:#fff;font-weight:500;text-align:left;padding:7px 9px;}
td{border-bottom:1px solid var(--ice);padding:6px 9px;vertical-align:top;}
tr:nth-child(even) td{background:#f4f7f7;}
h2,h3{break-after:avoid;}
table,blockquote{break-inside:avoid;}
.footer{margin-top:24px;padding-top:8px;border-top:1px solid var(--ice);color:var(--sand);font-size:8pt;display:flex;justify-content:space-between;}
</style></head>
<body>
<div class="cover">
  ${logoB64 ? `<img class="logo" src="data:image/png;base64,${logoB64}" alt="Regnology"/>` : `<div class="doc-title">Regnology</div>`}
  <div class="meta">
    <div class="doc-title">${esc(title)}</div>
    ${subtitle ? `<div class="doc-sub">${esc(subtitle)}</div>` : ''}
    <div class="doc-date">Generated ${today}</div>
  </div>
</div>
${html.join('\n')}
<div class="footer"><span>${esc(footer)}</span><span>Confidential — for internal review</span></div>
</body></html>`;

writeFileSync(outPath, doc, 'utf8');
console.log('wrote ' + outPath);
