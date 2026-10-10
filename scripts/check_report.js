// Offline smoke check for the report's real filter code and gallery assets.
const fs = require('fs'), vm = require('vm'), path = require('path');
const root = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'results/report.html'), 'utf8');
if (/__[A-Z]+__/.test(html)) throw new Error('Unreplaced report placeholder');
if ((html.match(/data:image\/png;base64,/g) || []).length !== 5) throw new Error('Missing embedded report plot');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
const elements = {
  speed: {value: 'all', addEventListener() {}},
  length: {value: 'all', addEventListener() {}},
  rows: {innerHTML: ''},
};
const context = vm.createContext({document: {getElementById: id => elements[id]}});
vm.runInContext(script, context, {timeout: 5000});
let combinations = 0;
for (const speed of ['all', 'ultrabullet', 'bullet', 'blitz', 'rapid', 'classical', 'unknown_or_correspondence']) {
  for (const length of ['all', '1-20 moves', '21-40 moves', '41-60 moves', '61+ moves']) {
    elements.speed.value = speed;
    elements.length.value = length;
    vm.runInContext('render()', context, {timeout: 5000});
    if ((elements.rows.innerHTML.match(/<tr /g) || []).length !== 7) throw new Error('Missing rating rows');
    if (/undefined|NaN/.test(elements.rows.innerHTML)) throw new Error('Invalid report values');
    combinations++;
  }
}
for (const name of ['index.html', 'graphs.html']) {
  const gallery = fs.readFileSync(path.join(root, 'results', name), 'utf8');
  if ((gallery.match(/data:image\/png;base64,/g) || []).length !== 7) throw new Error('Missing gallery graph');
  if (!gallery.includes('visual_summary.svg') || !gallery.includes('rating_length_heatmaps.svg')) throw new Error('Missing SVG export links');
}
for (const name of ['report.html', 'index.html', 'graphs.html']) {
  const content = fs.readFileSync(path.join(root, 'results', name), 'utf8');
  for (const match of content.matchAll(/href="([^"]+)"/g)) {
    if (/^(https?:|#|mailto:)/.test(match[1])) continue;
    if (!fs.existsSync(path.resolve(root, 'results', match[1]))) throw new Error(`Broken local link in ${name}: ${match[1]}`);
  }
}
console.log(JSON.stringify({filter_combinations: combinations,rows_per_filter: 7,report_figures: 5,gallery_figures: 7,local_links: 'ok'}));
