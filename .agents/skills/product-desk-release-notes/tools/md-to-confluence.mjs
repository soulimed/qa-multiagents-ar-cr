// Markdown -> Confluence storage-format XHTML (customer-publishable body only).
// Usage: node md-to-confluence.mjs <input.md> <output.xml>
// - Drops the H1 title (the Confluence page already has a title).
// - Drops any section from an "## Internal" / "## Excluded" heading onward
//   (internal sign-off content must NOT be published).
// - Blockquote -> Confluence "info" panel macro.
import { readFileSync, writeFileSync } from 'node:fs';

const [, , inPath, outPath] = process.argv;
if (!inPath || !outPath) { console.error('args: <input.md> <output.xml>'); process.exit(2); }

const xml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function inline(s) {
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => { codes.push(c); return `\u0000${codes.length - 1}\u0000`; });
  s = xml(s);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[^\w])_([^_]+)_(?=[^\w]|$)/g, '$1<em>$2</em>');
  s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${xml(codes[i])}</code>`);
  return s;
}

const lines = readFileSync(inPath, 'utf8').replace(/\r\n/g, '\n').split('\n');
const out = [];
let i = 0, stop = false;
while (i < lines.length && !stop) {
  let line = lines[i];
  if (/^\s*$/.test(line)) { i++; continue; }
  if (/^---+\s*$/.test(line)) { i++; continue; }          // drop horizontal rules

  let m;
  if ((m = line.match(/^#\s+/))) { i++; continue; }        // drop H1 (page title)
  if ((m = line.match(/^##\s+(.*)$/))) {
    if (/^(internal|excluded)\b/i.test(m[1].trim())) { stop = true; break; }  // stop before internal section
    out.push(`<h2>${inline(m[1])}</h2>`); i++; continue;
  }
  if ((m = line.match(/^###\s+(.*)$/))) { out.push(`<h3>${inline(m[1])}</h3>`); i++; continue; }

  if (/^>\s?/.test(line)) {                                 // blockquote -> info panel
    const buf = [];
    while (i < lines.length && /^>\s?/.test(lines[i])) { buf.push(lines[i].replace(/^>\s?/, '')); i++; }
    out.push(`<ac:structured-macro ac:name="info"><ac:rich-text-body><p>${inline(buf.join(' '))}</p></ac:rich-text-body></ac:structured-macro>`);
    continue;
  }

  if (/^\s*\|.*\|\s*$/.test(line)) {                        // table
    const rows = [];
    while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) { rows.push(lines[i].trim()); i++; }
    const cells = (r) => r.replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
    const isSep = (r) => /^\s*\|?[\s:|-]+\|?\s*$/.test(r) && r.includes('-');
    let head = null, body = [];
    if (rows.length > 1 && isSep(rows[1])) { head = cells(rows[0]); body = rows.slice(2); }
    else { body = rows; }
    let t = '<table><tbody>';
    if (head) t += '<tr>' + head.map((c) => `<th>${inline(c)}</th>`).join('') + '</tr>';
    t += body.map((r) => '<tr>' + cells(r).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>').join('');
    t += '</tbody></table>';
    out.push(t);
    continue;
  }

  // paragraph
  const buf = [];
  while (i < lines.length && !/^\s*$/.test(lines[i]) && !/^(#{1,3}\s|>|---+\s*$|\s*\|)/.test(lines[i])) {
    buf.push(lines[i]); i++;
  }
  out.push(`<p>${inline(buf.join(' '))}</p>`);
}

writeFileSync(outPath, out.join('\n'), 'utf8');
console.log(`wrote ${outPath} (${out.length} blocks)`);
