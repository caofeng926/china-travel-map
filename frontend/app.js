﻿
// Truncate POI names so the resulting AMap URL stays well under the
// browser URL length limits even for places with very long official names.
function _navTruncate(s, max) {
  s = String(s == null ? '' : s);
  return s.length > max ? s.slice(0, max) : s;
}

// Briefly disable a button so a frantic double-tap doesn't open the
// AMap handoff URL twice while the native app is still launching.
function _markNavButtonBusy(btn) {
  if (!btn) return;
  btn.setAttribute('data-nav-busy', '1');
  btn.disabled = true;
  setTimeout(function() {
    btn.removeAttribute('data-nav-busy');
    btn.disabled = false;
  }, 1500);
}

// Open AMap navigation in a new tab. Mirrors the behaviour of the same
// helper in index.html but degrades gracefully when toast() is missing.
function navigateTo(lat, lng, name, opts) {
  opts = opts || {};
  if (typeof lat !== 'number' || typeof lng !== 'number' || isNaN(lat) || isNaN(lng)) {
    if (typeof status === 'function') status('坐标无效，无法导航');
    return;
  }
  var safeName = _navTruncate(name, 50);
  var url;
  if (opts.from && typeof opts.from.lng === 'number' && typeof opts.from.lat === 'number') {
    var fromName = opts.from.name ? ',' + encodeURIComponent(_navTruncate(opts.from.name, 50)) : '';
    url = 'https://uri.amap.com/navigation?from=' + opts.from.lng + ',' + opts.from.lat + fromName +
          '&to=' + lng + ',' + lat + (safeName ? ',' + encodeURIComponent(safeName) : '') +
          '&mode=' + (opts.mode || 'car') +
          '&policy=1&src=china-travel-map&coordinate=gaode&callnative=1';
  } else {
    url = 'https://uri.amap.com/marker?position=' + lng + ',' + lat +
          '&name=' + encodeURIComponent(safeName) +
          '&src=china-travel-map&coordinate=gaode&callnative=1';
  }
  var w = null;
  try { w = window.open(url, '_blank', 'noopener'); } catch (e) { w = null; }
  if (!w) {
    var a = document.createElement('a');
    a.href = url; a.target = '_blank'; a.rel = 'noopener noreferrer';
    a.style.display = 'none';
    document.body.appendChild(a);
    try { a.click(); } catch (e) {}
    a.remove();
    if (typeof status === 'function') status('浏览器拦截了新窗口，请在地址栏右侧允许弹窗后重试');
  }
}

window._navMode = window._navMode || 'car';

function _setNavMode(mode, originBtn) {
  if (['car', 'walk', 'bus'].indexOf(mode) < 0) return;
  window._navMode = mode;
  var container = originBtn && originBtn.parentElement;
  if (!container) return;
  var pills = container.querySelectorAll('[data-nav-mode]');
  for (var i = 0; i < pills.length; i++) {
    var p = pills[i];
    var active = p === originBtn;
    p.style.background = active ? '#1f6feb' : '#f0f0f0';
    p.style.color      = active ? '#fff'      : '#333';
    p.style.fontWeight = active ? '600'       : '400';
  }
}

document.addEventListener('click', function(ev) {
  var t = ev.target;
  if (!t || !t.getAttribute) return;
  var modeAttr = t.getAttribute('data-nav-mode');
  if (modeAttr) { _setNavMode(modeAttr, t); return; }
  var isHere  = t.getAttribute('data-nav-here')  !== null;
  var isRoute = t.getAttribute('data-nav-route') !== null;
  var isLegacy = !isHere && !isRoute && t.getAttribute('data-nav-btn') !== null;
  if (!isHere && !isRoute && !isLegacy) return;
  if (t.disabled || t.getAttribute('data-nav-busy') === '1') return;
  var lat = parseFloat(t.getAttribute('data-lat'));
  var lng = parseFloat(t.getAttribute('data-lng'));
  var name = t.getAttribute('data-name') || '';
  if (isRoute) {
    if (!window.userPosition || typeof window.userPosition.lat !== 'number') {
      if (typeof status === 'function') status('请先点击右下角定位按钮，再使用"规划路线"');
      return;
    }
    navigateTo(lat, lng, name, { from: window.userPosition, mode: window._navMode });
  } else {
    navigateTo(lat, lng, name);
  }
  _markNavButtonBusy(t);
});

var clusterer = null;
var map, allPois = [], markers = [], filterLevel, filterType, filterKeyword;
var API_BASE = location.origin + location.pathname.replace(/\/$/, '').replace(/\/index\.html$/, '');
var AMAP_KEY = '';  // injected at deploy time via .env / build; see .env.example
var AMAP_SECRET = '';  // injected at deploy time via .env / build; see .env.example
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
      var _hasPos = (typeof userPosition === 'object' && userPosition && typeof userPosition.lat === 'number');
      var _routeStyle = _hasPos
        ? 'flex:1;padding:5px 8px;background:#34a853;color:#fff;border:none;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;touch-action:manipulation'
        : 'flex:1;padding:5px 8px;background:#cccccc;color:#666;border:none;border-radius:4px;font-size:11px;font-weight:600;cursor:not-allowed;touch-action:manipulation';
      var _routeTitle = _hasPos ? '' : ' title=\"请先点击右下角定位按钮\"';
      if (_hasPos) {
        var _dist = getDistance(userPosition.lat, userPosition.lng, poi.lat, poi.lng);
        info += '<div style="font-size:11px;color:#27ae60;margin-top:6px">📍 距您 ' + _dist + '</div>';
      }
      info += '<div style="display:flex;gap:6px;margin-top:6px">';
      info += '<button type="button" data-nav-here data-lat="' + poi.lat + '" data-lng="' + poi.lng + '" data-name="' + esc(poi.name) + '" style="flex:1;padding:5px 8px;background:#4285f4;color:#fff;border:none;border-radius:4px;font-size:11px;font-weight:600;cursor:pointer;touch-action:manipulation">🧭 导航到这里</button>';
      info += '<button type="button" data-nav-route' + _routeTitle + (_hasPos ? '' : ' disabled') + ' data-lat="' + poi.lat + '" data-lng="' + poi.lng + '" data-name="' + esc(poi.name) + '" style="' + _routeStyle + '">🚗 规划路线</button>';
      info += '</div>';
      var _modes = [{k:'car',l:'🚗 驾车'},{k:'walk',l:'🚶 步行'},{k:'bus',l:'🚌 公交'}];
      var _curMode = window._navMode || 'car';
      info += '<div style="display:flex;gap:4px;margin-top:4px">';
      for (var _mi = 0; _mi < _modes.length; _mi++) {
        var _m = _modes[_mi];
        var _active = (_m.k === _curMode);
        var _mStyle = _active
          ? 'flex:1;padding:4px 6px;background:#1f6feb;color:#fff;border:none;border-radius:3px;font-size:10px;font-weight:600;cursor:pointer;touch-action:manipulation'
          : 'flex:1;padding:4px 6px;background:#f0f0f0;color:#333;border:none;border-radius:3px;font-size:10px;cursor:pointer;touch-action:manipulation';
        info += '<button type="button" data-nav-mode="' + _m.k + '" style="' + _mStyle + '">' + _m.l + '</button>';
      }
      info += '</div></div>';
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

function esc(s) { if(!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;'); }
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
