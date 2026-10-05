const ls = Number(localStorage.getItem('visits') || 0) + 1;
localStorage.setItem('visits', ls);
document.getElementById('ls').textContent = ls;
const ck = Number((document.cookie.match(/visits=(\d+)/) || [0, 0])[1]) + 1;
document.cookie = `visits=${ck}; max-age=31536000; path=/`;
document.getElementById('ck').textContent = ck;

window.addEventListener('message', (e) => { document.getElementById('msg').textContent = JSON.stringify(e.data); });

function openPayPopup() { window.open('gateway.html?popup=1&return=return.html', 'pay'); }

function locate() {
  const out = document.getElementById('perm');
  out.textContent = 'locating…';
  navigator.geolocation.getCurrentPosition(
    (p) => out.textContent = `lat ${p.coords.latitude.toFixed(4)}, lng ${p.coords.longitude.toFixed(4)}`,
    (e) => out.textContent = `location error: ${e.message}`,
    { enableHighAccuracy: true, timeout: 15000 });
}

async function media(constraints) {
  const out = document.getElementById('perm');
  try {
    const stream = await navigator.mediaDevices.getUserMedia(constraints);
    out.textContent = `granted: ${stream.getTracks().map(t => t.kind).join(', ')}`;
    stream.getTracks().forEach(t => t.stop());
  } catch (e) { out.textContent = `media error: ${e.name}`; }
}

document.querySelectorAll('input[type=file]').forEach((input) => input.addEventListener('change', () => {
  document.getElementById('files').textContent = [...input.files].map(f => `${f.name} (${f.type || '?'}, ${f.size} B)`).join(', ') || 'cancelled';
}));

document.getElementById('datalink').href = 'data:text/plain;base64,' + btoa('Anar lab invoice\n');

function blobDownload() {
  const url = URL.createObjectURL(new Blob(['blob download'], { type: 'text/plain' }));
  const a = Object.assign(document.createElement('a'), { href: url, download: 'blob.txt' });
  document.body.appendChild(a); a.click(); a.remove();
}
