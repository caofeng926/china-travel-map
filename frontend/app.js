var clusterer = null;
var map, allPois = [], markers = [], filterLevel, filterType, filterKeyword;
var API_BASE = location.origin + location.pathname.replace(/\/$/, "").replace(/\/index\.html$/, "");
var AMAP_KEY = '6341f96e11ef424295330e635f174132';
var AMAP_SECRET = 'b8af7f12aafdc31fe67ee671a6871dd6';
window._AMapSecurityConfig = { securityJsCode: AMAP_SECRET };
window._onAmapLoad = function() { initMap(); };
var s = document.createElement("script");
s.src = "https://webapi.amap.com/maps?v=2.0&key=" + AMAP_KEY + "&callback=_onAmapLoad";
s.onerror = function() { document.getElementById("pl").innerHTML = '<div class=loading>Gaode load failed</div>'; };
document.head.appendChild(s);

function initMap() {
  map = new AMap.Map("map", { center: [109.5, 36.5], zoom: 7, mapStyle: "amap://styles/light", features: ["bg","road","building","point"] });
  setupFilters();
  loadData();
}

function loadData() {
  fetch(API_BASE + "/api/pois?page_size=4000")
    .then(function(r){ return r.json(); })
    .then(function(d){ allPois = d.results || []; renderMap(); })
    .catch(function(e){ console.log(e); });
}

function getIconStyle(p) {
  if (p.rating && p.rating.indexOf("街区") >= 0) return { color: "#9b59b6", label: "�?, size: 28 };
  if (p.type === "food") return { color: "#e67e22", label: "F", size: 26 };
  if (p.rating === "5A") return { color: "#c0392b", label: "5", size: 32 };
  if (p.rating === "4A") return { color: "#e74c3c", label: "4", size: 28 };
  if (p.rating === "3A") return { color: "#e67e22", label: "3", size: 24 };
  if (p.rating === "2A") return { color: "#3498db", label: "2", size: 22 };
  if (p.type === "scenic") return { color: "#4361ee", label: "�?, size: 26 };
  return { color: "#4361ee", label: "S", size: 26 };
}

function renderMap() {
  if (clusterer) { clusterer.setMap(null); clusterer = null; }
  if (markers.length) { map.remove(markers); markers = []; }
  var arr = filterData();
  arr.forEach(function(p) {
    var st = getIconStyle(p);
    var m = new AMap.Marker({
      position: [p.lng, p.lat],
      content: '<div style="background:#fff;border-radius:50%;border:2px solid '+st.color+';width:'+st.size+'px;height:'+st.size+'px;text-align:center;line-height:'+(st.size-4)+'px;font-weight:700;font-size:'+(st.size>28?13:11)+'px;color:'+st.color+';box-shadow:0 2px 6px rgba(0,0,0,.3);cursor:pointer">'+st.label+'</div>',
      offset: new AMap.Pixel(-st.size/2, -st.size/2),
      title: p.name
    });
    (function(marker, poi) {
      var info = '<div style="min-width:220px"><h3 style="font-size:14px;color:#c0392b">'+esc(poi.name)+'</h3>';
      if (poi.rating) info += '<span style="font-size:11px;background:#c0392b;color:#fff;padding:1px 6px;border-radius:3px">'+esc(poi.rating)+'</span> ';
      info += '<p style="font-size:12px;color:#555">'+esc(poi.description||'')+'</p>';
      if (poi.address) info += '<p style="font-size:11px;color:#888">'+esc(poi.address)+'</p>';
      if (poi.shop_name) info += '<p style="font-size:11px;color:#e67e22">'+esc(poi.shop_name)+'</p>';
      info += '<p style="font-size:11px;color:#999">'+esc(poi.province||'')+' '+esc(poi.city||'')+'</p></div>';
      marker.on("click", function() { new AMap.InfoWindow({ content: info, offset: new AMap.Pixel(0,-28) }).open(map, marker.getPosition()); });
    })(m, p);
    markers.push(m);
  });
  map.add(markers);
  updateStats(arr);
}

function filterData() {
  var arr = allPois;
  if (filterLevel && filterLevel !== "all") {
    if (filterLevel === "leisure") arr = arr.filter(function(p){return p.rating && p.rating.indexOf("街区")>=0;});
    else arr = arr.filter(function(p){return p.rating === filterLevel;});
  }
  if (filterType && filterType !== "all") {
    if (filterType === "scenic") arr = arr.filter(function(p){return p.type === "scenic" && (!p.rating || p.rating.indexOf("街区")<0);});
    else if (filterType === "food") arr = arr.filter(function(p){return p.type === "food";});
    else if (filterType === "leisure") arr = arr.filter(function(p){return p.rating && p.rating.indexOf("街区")>=0;});
  }
  if (filterKeyword) {
    var kw = filterKeyword.toLowerCase();
    arr = arr.filter(function(p){ return (p.name&&p.name.toLowerCase().indexOf(kw)>=0)||(p.city&&p.city.toLowerCase().indexOf(kw)>=0); });
  }
  return arr;
}

function updateStats(arr) {
  document.getElementById("ct").textContent = arr.length;
  document.getElementById("cs").textContent = arr.filter(function(p){return p.type==="scenic" && (!p.rating || p.rating.indexOf("街区")<0);}).length;
  document.getElementById("cf").textContent = arr.filter(function(p){return p.type==="food";}).length;
  document.getElementById("cl").textContent = arr.filter(function(p){return p.rating && p.rating.indexOf("街区")>=0;}).length;
}

function esc(s) { if(!s) return ''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function flyTo(lat, lng) { map.setZoomAndCenter(10, [lng, lat]); }

function setupFilters() {
  document.querySelectorAll(".lf,.cf").forEach(function(btn){
    btn.addEventListener("click", function(){
      document.querySelectorAll(".lf,.cf").forEach(function(b){b.classList.remove("a");});
      this.classList.add("a");
      var l = this.getAttribute("data-l");
      var c = this.getAttribute("data-c");
      filterLevel = (l && l !== "all") ? l : null;
      filterType = (c && c !== "all") ? c : null;
      if (l) filterType = null;
      if (c) filterLevel = null;
      renderMap();
    });
  });
}
