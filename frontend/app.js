
var clusterer = null;
var map, allPois = [], markers = [], filterLevel, filterType, filterKeyword;
var API_BASE = location.origin + location.pathname.replace(/\/$/, '').replace(/\/index\.html$/, '');
var AMAP_KEY = '38fba823c8d8df93203578dfbfb14cd2';
var AMAP_SECRET = 'e9222e15bcfca7750536ca497e767bda';
window._AMapSecurityConfig = { securityJsCode: AMAP_SECRET };
var amapRetries = 0, amapMaxRetries = 3, mapInitialized = false;

function showPL() {
  var el = document.getElementById('pl');
  if (el) el.style.display = 'flex';
}
function hidePL() {
  var el = document.getElementById('pl');
  if (el) el.style.display = 'none';
}
function showError(msg) {
  var el = document.getElementById('pl');
  if (el) { el.style.display = 'flex'; el.innerHTML = '<div class=loading style=color:#c0392b>'+msg+'<br><button onclick=location.reload() style=margin-top:8px;padding:6px 16px;border:1px solid #c0392b;background:#fff;color:#c0392b;border-radius:4px;cursor:pointer>\u91cd\u8bd5</button></div>'; }
  status(msg);
}
function status(msg) {
  var el = document.getElementById('status');
  if (el) el.textContent = msg;
}

function loadAmap() {
  showPL();
  var el = document.getElementById('pl');
  if (el) el.innerHTML = '<div class=loading><div class=spinner></div>\u6b63\u5728\u52a0\u8f7d\u5730\u56fe...</div>';
  var s = document.createElement('script');
  s.src = 'https://webapi.amap.com/maps?v=2.0&key=' + AMAP_KEY + '&callback=_onAmapLoad&t=' + Date.now();
  s.onerror = function() {
    amapRetries++;
    if (amapRetries < amapMaxRetries) {
      status('\u5730\u56fe\u52a0\u8f7d\u5931\u8d25 ('+amapRetries+'/'+amapMaxRetries+')\uff0c\u6b63\u5728\u91cd\u8bd5...');
      setTimeout(loadAmap, 2000);
    } else {
      showError('\u5730\u56fe\u52a0\u8f7d\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u540e\u91cd\u8bd5');
    }
  };
  document.head.appendChild(s);
}

window._onAmapLoad = function() {
  if (mapInitialized) return;
  mapInitialized = true;
  hidePL();
  status('\u5730\u56fe\u52a0\u8f7d\u6210\u529f\uff0c\u6b63\u5728\u83b7\u53d6\u6570\u636e...');
  try {
    map = new AMap.Map('map', {
      center: [109.5, 36.5], zoom: 7,
      mapStyle: 'amap://styles/light',
      features: ['bg','road','building','point']
    });
    setupFilters();
    loadData();
  } catch(e) {
    showError('\u5730\u56fe\u521d\u59cb\u5316\u5931\u8d25: ' + e.message);
  }
};
loadAmap();

function loadData() {
  status('\u6b63\u5728\u52a0\u8f7d\u6570\u636e...');
  try {
    var controller, timeoutId;
    if (typeof AbortController !== 'undefined') {
      controller = new AbortController();
      timeoutId = setTimeout(function() {
        try { controller.abort(); } catch(e) {}
      }, 15000);
    }
    var opts = {};
    if (controller) opts.signal = controller.signal;

    fetch(API_BASE + '/api/pois?page_size=1000', opts)
      .then(function(r) {
        if (timeoutId) clearTimeout(timeoutId);
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function(d) {
        allPois = d.results || [];
        status('\u52a0\u8f7d\u5b8c\u6210: ' + allPois.length + ' \u4e2a\u5730\u70b9');
        renderMap();
      })
      .catch(function(e) {
        if (timeoutId) clearTimeout(timeoutId);
        if (e.name === 'AbortError') {
          showError('\u6570\u636e\u52a0\u8f7d\u8d85\u65f6\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u540e\u91cd\u8bd5');
        } else {
          showError('\u6570\u636e\u52a0\u8f7d\u5931\u8d25: ' + e.message);
        }
      });
  } catch(e) {
    showError('\u6570\u636e\u52a0\u8f7d\u5f02\u5e38: ' + e.message);
  }
}

function getIconStyle(p) {
  if (p.rating && p.rating.indexOf('\u8857\u533a') >= 0) return { color: '#9b59b6', label: '\u8857', size: 28 };
  if (p.type === 'food') return { color: '#e67e22', label: 'F', size: 26 };
  if (p.rating === '5A') return { color: '#c0392b', label: '5', size: 32 };
  if (p.rating === '4A') return { color: '#e74c3c', label: '4', size: 28 };
  if (p.rating === '3A') return { color: '#e67e22', label: '3', size: 24 };
  if (p.rating === '2A') return { color: '#3498db', label: '2', size: 22 };
  if (p.type === 'scenic') return { color: '#4361ee', label: '\u666f', size: 26 };
  return { color: '#4361ee', label: 'S', size: 26 };
}

function renderMap() {
  if (clusterer) { clusterer.setMap(null); clusterer = null; }
  if (markers.length) { map.remove(markers); markers = []; }
  var arr = filterData();
  arr.forEach(function(p) {
    var st = getIconStyle(p);
    var m = new AMap.Marker({
      position: [p.lng, p.lat],
      content: '<div style=background:#fff;border-radius:50%;border:2px solid '+st.color+';width:'+st.size+'px;height:'+st.size+'px;text-align:center;line-height:'+(st.size-4)+'px;font-weight:700;font-size:'+(st.size>28?13:11)+'px;color:'+st.color+';box-shadow:0 2px 6px rgba(0,0,0,.3);cursor:pointer>'+st.label+'</div>',
      offset: new AMap.Pixel(-st.size/2, -st.size/2),
      title: p.name
    });
    (function(marker, poi) {
      var info = '<div style=min-width:220px><h3 style=font-size:14px;color:#c0392b>'+esc(poi.name)+'</h3>';
      if (poi.rating) info += '<span style=font-size:11px;background:#c0392b;color:#fff;padding:1px 6px;border-radius:3px>'+esc(poi.rating)+'</span> ';
      info += '<p style=font-size:12px;color:#555>'+esc(poi.description||'')+'</p>';
      if (poi.address) info += '<p style=font-size:11px;color:#888>'+esc(poi.address)+'</p>';
      if (poi.shop_name) info += '<p style=font-size:11px;color:#e67e22>'+esc(poi.shop_name)+'</p>';
      info += '<p style=font-size:11px;color:#999>'+esc(poi.province||'')+' '+esc(poi.city||'')+'</p></div>';
      marker.on('click', function() { new AMap.InfoWindow({ content: info, offset: new AMap.Pixel(0,-28) }).open(map, marker.getPosition()); });
    })(m, p);
    markers.push(m);
  });
  map.add(markers);
  updateStats(arr);
}

function filterData() {
  var arr = allPois;
  if (filterLevel && filterLevel !== 'all') {
    if (filterLevel === 'leisure') arr = arr.filter(function(p){return p.rating && p.rating.indexOf('\u8857\u533a')>=0;});
    else arr = arr.filter(function(p){return p.rating === filterLevel;});
  }
  if (filterType && filterType !== 'all') {
    if (filterType === 'scenic') arr = arr.filter(function(p){return p.type === 'scenic' && (!p.rating || p.rating.indexOf('\u8857\u533a')<0);});
    else if (filterType === 'food') arr = arr.filter(function(p){return p.type === 'food';});
    else if (filterType === 'leisure') arr = arr.filter(function(p){return p.rating && p.rating.indexOf('\u8857\u533a')>=0;});
  }
  if (filterKeyword) {
    var kw = filterKeyword.toLowerCase();
    arr = arr.filter(function(p){ return (p.name&&p.name.toLowerCase().indexOf(kw)>=0)||(p.city&&p.city.toLowerCase().indexOf(kw)>=0); });
  }
  return arr;
}

function updateStats(arr) {
  document.getElementById('ct').textContent = arr.length;
  document.getElementById('cs').textContent = arr.filter(function(p){return p.type==='scenic' && (!p.rating || p.rating.indexOf('\u8857\u533a')<0);}).length;
  document.getElementById('cf').textContent = arr.filter(function(p){return p.type==='food';}).length;
  document.getElementById('cl').textContent = arr.filter(function(p){return p.rating && p.rating.indexOf('\u8857\u533a')>=0;}).length;
}

function esc(s) { if(!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function flyTo(lat, lng) { map.setZoomAndCenter(10, [lng, lat]); }

function setupFilters() {
  document.querySelectorAll('.lf,.cf').forEach(function(btn){
    btn.addEventListener('click', function(){
      document.querySelectorAll('.lf,.cf').forEach(function(b){b.classList.remove('a');});
      this.classList.add('a');
      var l = this.getAttribute('data-l');
      var c = this.getAttribute('data-c');
      filterLevel = (l && l !== 'all') ? l : null;
      filterType = (c && c !== 'all') ? c : null;
      if (l) filterType = null;
      if (c) filterLevel = null;
      renderMap();
    });
  });
}
