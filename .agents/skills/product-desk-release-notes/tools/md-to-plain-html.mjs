// Markdown -> clean semantic HTML for COPY-PASTE into Confluence Cloud.
// Open the output in a browser, Select-All (Ctrl+A), Copy (Ctrl+C), paste into the
// Confluence editor. Cloud converts pasted rich HTML into real headings/bold/tables.
// Usage: node md-to-plain-html.mjs <input.md> <output.html>
import { readFileSync, writeFileSync } from 'node:fs';

const [, , inPath, outPath] = process.argv;
if (!inPath || !outPath) { console.error('args: <input.md> <output.html>'); process.exit(2); }

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function inline(s) {
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = esc(s);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^\w])_([^_]+)_(?=[^\w]|$)/g, '$1<em>$2</em>');
  s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[i])}</code>`);
  return s;
}

const lines = readFileSync(inPath, 'utf8').replace(/\r\n/g, '\n').split('\n');
const out = [];
let i = 0;
while (i < lines.length) {
  let line = lines[i];
  if (/^\s*$/.test(line)) { i++; continue; }
  if (/^---+\s*$/.test(line)) { out.push('<hr/>'); i++; continue; }
  let m;
  if ((m = line.match(/^#\s+(.*)$/)))  { out.push(`<h1>${inline(m[1])}</h1>`); i++; continue; }
  if ((m = line.match(/^##\s+(.*)$/))) { out.push(`<h2>${inline(m[1])}</h2>`); i++; continue; }
  if ((m = line.match(/^###\s+(.*)$/))){ out.push(`<h3>${inline(m[1])}</h3>`); i++; continue; }
  if (/^>\s?/.test(line)) {
    const buf = [];
    while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, '')); i++; }
    out.push(`<blockquote>${inline(buf.join(' '))}</blockquote>`);
    continue;
  }
  if (/^\s*\|.*\|\s*$/.test(line)) {
    const rows = [];
    while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(lines[i].trim()); i++; }
    const cells = (r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
    const isSep = (r) => /^\s*\|?[\s:|-]+\|?\s*$/.test(r) && r.includes('-');
    let head = null, body = [];
    if (rows.length > 1 && isSep(rows[1])) { head = cells(rows[0]); body = rows.slice(2); }
    else { body = rows; }
    let t = '<table border="1" cellspacing="0" cellpadding="4"><tbody>';
    if (head) t += '<tr>' + head.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr>';
    t += body.map((r) => '<tr>' + cells(r).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('');
    t += '</tbody></table>';
    out.push(t);
    continue;
  }
  const buf = [];
  while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,3}\s|>|---+\s*$|\s*\|)/.test(lines[i])) {
    buf.push(lines[i]); i++;
  }
  out.push(`<p>${inline(buf.join(' '))}</p>`);
}

const doc = `<!doctype html><html><head><meta charset="utf-8"><title>Release notes</title>
<style>body{font-family:Arial,Helvetica,sans-serif;max-width:820px;margin:24px auto;line-height:1.45;color:#172b4d}
table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:4px 8px;text-align:left}
blockquote{border-left:3px solid #ffab00;background:#fffae6;margin:8px 0;padding:6px 12px}
code{background:#f4f5f7;padding:0 4px;border-radius:3px}h1,h2,h3{color:#172b4d}</style></head>
<body>\n${out.join('\n')}\n</body></html>`;
writeFileSync(outPath, doc, 'utf8');
console.log(`wrote ${outPath} (${out.length} blocks)`);
